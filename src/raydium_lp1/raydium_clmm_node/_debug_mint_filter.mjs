import { bootRaydium } from './_shared.mjs';
import { PublicKey } from '@solana/web3.js';

const inp = JSON.parse(process.argv[2]);
const poolId = process.argv[3];
const { raydium } = await bootRaydium(inp);
const poolData = await raydium.clmm.getPoolInfoFromRpc(poolId);
const e = poolData.poolInfo;
const usdc = new PublicKey('EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v');
const mintB = new PublicKey(e.mintB.address);
const raw = raydium.account.tokenAccountRawInfos || [];
const hits = raw.filter((k) => k.accountInfo?.mint?.equals?.(mintB));
const hitsUsdc = raw.filter((k) => k.accountInfo?.mint?.equals?.(usdc));
console.log(JSON.stringify({
  mintA: String(e.mintA.address),
  mintB: String(e.mintB.address),
  mintBProgram: String(e.mintB.programId || ''),
  rawCount: raw.length,
  hitsMintB: hits.length,
  hitsUsdc: hitsUsdc.length,
  usdcPks: hitsUsdc.map((k) => k.pubkey.toBase58()),
}, null, 2));
