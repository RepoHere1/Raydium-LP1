import { bootRaydium, fetchTokenAccountData } from './_shared.mjs';
import { PublicKey } from '@solana/web3.js';
import BN from 'bn.js';

const inp = JSON.parse(process.argv[2]);
const poolId = process.argv[3];
const { raydium, connection, owner } = await bootRaydium(inp);
const poolData = await raydium.clmm.getPoolInfoFromRpc(poolId);
const e = poolData.poolInfo;
const tokenAccountData = await fetchTokenAccountData(connection, owner);
raydium.account.updateTokenAccount(tokenAccountData);
raydium.account.fetchWalletTokenAccounts = async () => undefined;

const mintA = new PublicKey(e.mintA.address);
const mintB = new PublicKey(e.mintB.address);
const S = new BN(0);
const K = new BN(150000);
const h = false;
const B = false;
const d = false;

const rA = await raydium.account.getOrCreateTokenAccount({
  tokenProgram: e.mintA.programId,
  mint: mintA,
  owner: raydium.ownerPubKey,
  createInfo: h || S.isZero() ? { payer: raydium.ownerPubKey, amount: S } : undefined,
  skipCloseAccount: !h,
  notUseTokenAccount: h,
  associatedOnly: h ? false : d,
  checkCreateATAOwner: false,
});
const rB = await raydium.account.getOrCreateTokenAccount({
  tokenProgram: e.mintB.programId,
  mint: mintB,
  owner: raydium.ownerPubKey,
  createInfo: B || K.isZero() ? { payer: raydium.ownerPubKey, amount: K } : undefined,
  skipCloseAccount: !B,
  notUseTokenAccount: B,
  associatedOnly: B ? false : d,
  checkCreateATAOwner: false,
});
console.log(JSON.stringify({
  A: rA.account?.toBase58?.() || null,
  B: rB.account?.toBase58?.() || null,
}, null, 2));
