/**
 * Probe CLMM pool ticks + liquidity for a one-sided SOL deposit.
 * Usage: node scripts/probe_clmm_pool.mjs [pool_id]
 */
import { readFileSync, existsSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { Connection, PublicKey } from '@solana/web3.js';
import { Raydium, PoolUtils, TickUtil } from '@raydium-io/raydium-sdk-v2';
import BN from 'bn.js';
import Decimal from 'decimal.js';

const POOL = process.argv[2] || 'BSPFA8d9qeZdsTubmS6FvriYadx2mzoi6jesauD6hi4e';
const SOL = 'So11111111111111111111111111111111111111112';
const AMOUNT_SOL = Number(process.argv[3] || 0.005);

const HERE = dirname(fileURLToPath(import.meta.url));
const envPath = resolve(HERE, '..', '.env');
const env = {};
if (existsSync(envPath)) {
  for (const ln of readFileSync(envPath, 'utf8').split(/\r?\n/)) {
    const m = ln.match(/^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*)$/);
    if (m) env[m[1]] = m[2].trim().replace(/^["']|["']$/g, '');
  }
}
const rpc = env.SOLANA_RPC_URL || process.env.SOLANA_RPC_URL;
if (!rpc) {
  console.error('SOLANA_RPC_URL missing');
  process.exit(1);
}

const conn = new Connection(rpc, 'confirmed');
const raydium = await Raydium.load({ connection: conn, cluster: 'mainnet', disableFeatureCheck: true });
const { poolInfo } = await raydium.clmm.getPoolInfoFromRpc(POOL);
const decA = poolInfo.mintA.decimals;
const decB = poolInfo.mintB.decimals;
const spacing = poolInfo.config?.tickSpacing ?? poolInfo.tickSpacing ?? 1;
const tc = poolInfo.tickCurrent;
const mintA = String(poolInfo.mintA.address);
const mintB = String(poolInfo.mintB.address);
const lamports = new BN(new Decimal(AMOUNT_SOL).mul(1e9).toFixed(0));
const epochInfo = await conn.getEpochInfo();

console.log(JSON.stringify({
  pool: POOL,
  price: poolInfo.price,
  tickCurrent: tc,
  tickSpacing: spacing,
  mintA, mintB,
  mintA_symbol: poolInfo.mintA.symbol,
  mintB_symbol: poolInfo.mintB.symbol,
  amount_lamports: lamports.toString(),
}, null, 2));

const baseIn = SOL === mintA;
const attempts = [];

for (const [label, lo, hi] of [
  ['above_tc+1step', Math.ceil((tc + spacing) / spacing) * spacing, Math.ceil((tc + spacing) / spacing) * spacing + 10 * spacing],
  ['straddle_tc', tc - 5 * spacing, tc + 5 * spacing],
  ['below_tc', tc - 12 * spacing, tc - spacing],
]) {
  for (const tryA of [true, false]) {
    try {
      const probe = PoolUtils.getLiquidityAmountOutFromAmountIn({
        poolInfo, inputA: tryA,
        tickLower: Math.min(lo, hi), tickUpper: Math.max(lo, hi),
        amount: lamports, slippage: 0.01, add: true, epochInfo, amountHasFee: true,
      });
      const liq = probe?.liquidity?.toString?.() ?? '0';
      attempts.push({ label, tryA, lo, hi, liquidity: liq });
    } catch (e) {
      attempts.push({ label, tryA, lo, hi, error: e.message });
    }
  }
}

console.log('\nattempts:', JSON.stringify(attempts, null, 2));
