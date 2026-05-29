/** Probe CLMM liquidity bands — run from this directory. */
import { readFileSync, existsSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { Connection } from '@solana/web3.js';
import { Raydium, PoolUtils } from '@raydium-io/raydium-sdk-v2';
import BN from 'bn.js';
import Decimal from 'decimal.js';

const POOL = process.argv[2] || 'BSPFA8d9qeZdsTubmS6FvriYadx2mzoi6jesauD6hi4e';
const AMOUNT_SOL = Number(process.argv[3] || 0.005);
const SOL = 'So11111111111111111111111111111111111111112';

const HERE = dirname(fileURLToPath(import.meta.url));
const envPath = resolve(HERE, '..', '..', '..', '.env');
const env = {};
if (existsSync(envPath)) {
  for (const ln of readFileSync(envPath, 'utf8').split(/\r?\n/)) {
    const m = ln.match(/^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*)$/);
    if (m) env[m[1]] = m[2].trim().replace(/^["']|["']$/g, '');
  }
}
const rpc = env.SOLANA_RPC_URL;
const conn = new Connection(rpc, 'confirmed');
const raydium = await Raydium.load({ connection: conn, cluster: 'mainnet', disableFeatureCheck: true });
const { poolInfo } = await raydium.clmm.getPoolInfoFromRpc(POOL);
const spacing = poolInfo.config?.tickSpacing ?? poolInfo.tickSpacing ?? 1;
const tc = poolInfo.tickCurrent;
const mintA = String(poolInfo.mintA.address);
const lamports = new BN(new Decimal(AMOUNT_SOL).mul(1e9).toFixed(0));
const epochInfo = await conn.getEpochInfo();
const baseIn = SOL === mintA;

console.log({ price: poolInfo.price, tickCurrent: tc, tickSpacing: spacing, mintA, mintB: String(poolInfo.mintB.address), baseIn });

const attempts = [];
for (const [label, lo, hi] of [
  ['above', Math.ceil((tc + spacing) / spacing) * spacing, Math.ceil((tc + spacing) / spacing) * spacing + 10 * spacing],
  ['straddle', tc - 5 * spacing, tc + 5 * spacing],
]) {
  for (const tryA of [true, false]) {
    const probe = await PoolUtils.getLiquidityAmountOutFromAmountIn({
      poolInfo, inputA: tryA,
      tickLower: Math.min(lo, hi), tickUpper: Math.max(lo, hi),
      amount: lamports, slippage: 0.01, add: true, epochInfo, amountHasFee: true,
    });
    const liqBN = probe?.liquidity;
    const ok = liqBN && typeof liqBN.gt === 'function' && liqBN.gt(new BN(0));
    attempts.push({
      label, tryA, lo, hi,
      liquidity: liqBN?.toString?.() ?? null,
      ok,
      keys: probe ? Object.keys(probe) : [],
      amountA: probe?.amountSlippageA?.amount?.toString?.(),
      amountB: probe?.amountSlippageB?.amount?.toString?.(),
    });
  }
}
console.log(JSON.stringify(attempts, null, 2));
