/**
 * tick_probe.mjs v3 — encoding-tolerant .env reader + tick-conversion probe.
 */

import { readFileSync, existsSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { Connection } from '@solana/web3.js';
import { Raydium, TickUtil, PoolUtils } from '@raydium-io/raydium-sdk-v2';
import Decimal from 'decimal.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const CANDIDATES = [
  resolve(HERE, '..', '..', '..', '.env'),
  resolve(HERE, '..', '..', '.env'),
  resolve(HERE, '..', '.env'),
  resolve(HERE, '.env'),
];

function decodeAny(buf) {
  // UTF-16 LE BOM
  if (buf.length >= 2 && buf[0] === 0xFF && buf[1] === 0xFE) {
    return { enc: 'utf16le-bom', text: buf.toString('utf16le', 2) };
  }
  // UTF-16 BE BOM
  if (buf.length >= 2 && buf[0] === 0xFE && buf[1] === 0xFF) {
    // swap bytes then decode as utf16le
    const swapped = Buffer.alloc(buf.length - 2);
    for (let i = 0; i < swapped.length; i += 2) {
      swapped[i] = buf[i + 3]; swapped[i + 1] = buf[i + 2];
    }
    return { enc: 'utf16be-bom', text: swapped.toString('utf16le') };
  }
  // UTF-8 BOM
  if (buf.length >= 3 && buf[0] === 0xEF && buf[1] === 0xBB && buf[2] === 0xBF) {
    return { enc: 'utf8-bom', text: buf.toString('utf8', 3) };
  }
  // Heuristic: lots of 0x00 → likely UTF-16 without BOM
  let zeros = 0;
  for (let i = 0; i < Math.min(buf.length, 200); i++) if (buf[i] === 0) zeros++;
  if (zeros > 30) return { enc: 'utf16le-noBom', text: buf.toString('utf16le') };
  return { enc: 'utf8', text: buf.toString('utf8') };
}

let envPath = null;
let envText = '';
let encUsed = '';
for (const p of CANDIDATES) {
  if (existsSync(p)) {
    envPath = p;
    try {
      const buf = readFileSync(p);
      console.log(`  file size: ${buf.length} bytes, first 8 bytes: ${[...buf.slice(0, 8)].map(b => b.toString(16).padStart(2,'0')).join(' ')}`);
      const dec = decodeAny(buf);
      envText = dec.text;
      encUsed = dec.enc;
    } catch (e) {
      console.log(`  read fail: ${e.message}`);
    }
    break;
  }
}
console.log('  using:', envPath || 'NONE', `(encoding: ${encUsed})`);

const env = {};
for (const rawLn of envText.split(/\r?\n/)) {
  const ln = rawLn.replace(/^﻿/, '');  // strip stray BOM at start of any line
  const m = ln.match(/^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*?)\s*$/);
  if (m) env[m[1]] = m[2].replace(/^["']|["']$/g, '').trim();
}
const interesting = Object.keys(env).filter(k => /SOLANA|RPC|KEYPAIR|WALLET/.test(k));
console.log('  .env keys loaded:', interesting);
console.log('  total keys:', Object.keys(env).length);
console.log('  SOLANA_RPC_URL set?', !!env.SOLANA_RPC_URL, env.SOLANA_RPC_URL ? `(len=${env.SOLANA_RPC_URL.length})` : '');
console.log('  first 60 chars of envText (escaped):', JSON.stringify(envText.slice(0, 60)));

const rpc = env.SOLANA_RPC_URL;
if (!rpc) {
  console.log(JSON.stringify({ok:false, error:'SOLANA_RPC_URL missing (see diagnostics above)'}));
  process.exit(1);
}

const POOL = '3ucNos4NbumPLZNWztqGHNFFgkHeRMBQAVemeeomsUxv';

const conn = new Connection(rpc, 'confirmed');
const raydium = await Raydium.load({ connection: conn, cluster: 'mainnet', disableFeatureCheck: true });
const rpcPool = await raydium.clmm.getPoolInfoFromRpc(POOL);
const rpcInfo = rpcPool.poolInfo;
let apiInfo = null;
try {
  const apiResp = await raydium.api.fetchPoolById({ ids: POOL });
  apiInfo = Array.isArray(apiResp) ? apiResp[0] : (apiResp?.data?.[0] || apiResp);
} catch (e) { console.log('  api.fetchPoolById failed:', e.message); }

function sum(info, label) {
  if (!info) return { label, present: false };
  return { label, present: true, keys: Object.keys(info).slice(0,30),
           price: info.price, mintA_decimals: info.mintA?.decimals,
           mintB_decimals: info.mintB?.decimals, mintA_symbol: info.mintA?.symbol,
           config: info.config };
}
console.log('\n--- POOL INFO COMPARISON ---');
console.log(JSON.stringify({ rpc: sum(rpcInfo,'rpc'), api: sum(apiInfo,'api') }, null, 2));

const TARGET_PRICE = 85.03;
console.log(`\n--- TICK CONVERSION ATTEMPTS for price=${TARGET_PRICE} ---`);
for (const [infoLabel, info] of [['rpc', rpcInfo], ['api', apiInfo]]) {
  if (!info) continue;
  console.log(`\n  POOL=${infoLabel}`);
  for (const baseIn of [true, false]) {
    try {
      const r = TickUtil.getPriceAndTick({ poolInfo: info, price: new Decimal(TARGET_PRICE), baseIn });
      console.log(`    getPriceAndTick(baseIn=${baseIn}): tick=${r?.tick}, price=${r?.price}`);
    } catch (e) { console.log(`    getPriceAndTick(baseIn=${baseIn}): ERROR ${e.message}`); }
  }
  for (const baseIn of [true, false]) {
    try {
      const t = TickUtil.priceToTick({ poolInfo: info, price: new Decimal(TARGET_PRICE), baseIn });
      console.log(`    priceToTick(baseIn=${baseIn}): ${t}`);
    } catch (e) { console.log(`    priceToTick(baseIn=${baseIn}): ERROR ${e.message}`); }
  }
  for (const [decA, decB] of [[9,6], [6,9]]) {
    try {
      const sqrtX = TickUtil.priceToSqrtPriceX64(new Decimal(TARGET_PRICE), decA, decB);
      const t = TickUtil.getTickAtSqrtPrice(sqrtX);
      console.log(`    priceToSqrtPriceX64(${decA},${decB}) → tick=${t}, sqrtX=${sqrtX?.toString?.()?.slice(0,30)}`);
    } catch (e) { console.log(`    priceToSqrtPriceX64(${decA},${decB}): ERROR ${e.message}`); }
  }
}
console.log('\n--- DONE ---');
