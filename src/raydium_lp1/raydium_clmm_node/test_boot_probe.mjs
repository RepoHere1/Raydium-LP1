import { bootRaydium, BN, readStdinJson } from './_shared.mjs';
import { PoolUtils } from '@raydium-io/raydium-sdk-v2';
import Decimal from 'decimal.js';
import { readFileSync } from 'fs';
import { homedir } from 'os';
import { join } from 'path';

function alignTickDown(tick, spacing) {
  return Math.floor(tick / spacing) * spacing;
}

const env = Object.fromEntries(
  readFileSync(join(process.cwd(), '../../../.env'), 'utf8')
    .split('\n')
    .filter((l) => l.includes('=') && !l.startsWith('#'))
    .map((l) => {
      const i = l.indexOf('=');
      return [l.slice(0, i).trim(), l.slice(i + 1).trim().replace(/^["']|["']$/g, '')];
    }),
);

const kp = env.SOLANA_KEYPAIR_PATH?.replace('~', homedir());
const { raydium } = await bootRaydium({ rpc_url: env.SOLANA_RPC_URL, keypair_path: kp });
const poolId = 'AoPimKYHxNTHAXXtqoespdaYVBVvEvjtYNvxGfmRdE2p';
const poolData = await raydium.clmm.getPoolInfoFromRpc(poolId);
const { poolInfo } = poolData;
const tickSpacing = poolInfo.config?.tickSpacing ?? 120;
const tickCurrent = Number(poolInfo.tickCurrent);
const bootSteps = 32;
const bootHi = alignTickDown(tickCurrent - tickSpacing, tickSpacing);
const bootLo = bootHi - bootSteps * tickSpacing;
const amt = new BN(new Decimal(2.55).mul(1e6).toFixed(0));
const epochInfo = await raydium.connection.getEpochInfo();
for (const tryBaseIn of [false, true]) {
  const p = await PoolUtils.getLiquidityAmountOutFromAmountIn({
    poolInfo, inputA: tryBaseIn, tickLower: bootLo, tickUpper: bootHi,
    amount: amt, slippage: 0.25, add: true, epochInfo, amountHasFee: true,
  });
  console.log('boot below', { tryBaseIn, bootLo, bootHi, liq: p?.liquidity?.toString?.(), otherA: p?.amountSlippageA?.amount?.toString?.(), otherB: p?.amountSlippageB?.amount?.toString?.() });
}
const lo = -443520, hi = 443520;
const p2 = await PoolUtils.getLiquidityAmountOutFromAmountIn({
  poolInfo, inputA: false, tickLower: lo, tickUpper: hi,
  amount: amt, slippage: 0.25, add: true, epochInfo, amountHasFee: true,
});
console.log('full', {
  liq: p2?.liquidity?.toString?.(),
  otherA: p2?.amountSlippageA?.amount?.toString?.(),
  otherB: p2?.amountSlippageB?.amount?.toString?.(),
});
