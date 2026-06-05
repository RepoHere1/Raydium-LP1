/**
 * harvest_clmm_fees.mjs — Raydium CLMM fee harvest (liquidity unchanged).
 *
 * Same on-chain action as Raydium UI "Harvest": decreaseLiquidity with liquidity=0.
 * Unlike the UI default, optional sweep sends *non-pay* fee tokens to pay-type via Jupiter;
 * pay-type fees are kept (not swapped to junker).
 *
 * stdin: {
 *   position_nft_mint, slippage_bps?, priority_fee_micro_lamports?, compute_units?,
 *   trash_output_mint?, trash_keep_mints?, sweep_non_pay_to_pay_type?: true,
 *   trash_swap_max_attempts?, pay_mint_for_sol_balance?
 * }
 */

import {
  readStdinJson, bootRaydium, finish, failFromError,
  BN, PublicKey, TxVersion,
} from './_shared.mjs';
import { VersionedTransaction } from '@solana/web3.js';
import { TOKEN_PROGRAM_ID } from '@solana/spl-token';

const ZERO_PUBKEY = '11111111111111111111111111111111';
const WSOL_MINT = 'So11111111111111111111111111111111111111112';
const USDC_MINT = 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v';
const USDT_MINT = 'Es9vMFrzaCERmJfrF4H2FYD4KConky11McCe8BenwNYB';
const USD1_MINT = 'USD1ttGY1N17NEEHLmELoaybftRBUSErhqYiQzvEmuB';
const DEFAULT_KEEP = new Set([WSOL_MINT, USDC_MINT, USDT_MINT, USD1_MINT]);
const TRASH_DUST_RAW = 10_000;

const JUP_QUOTE = 'https://lite-api.jup.ag/swap/v1/quote';
const JUP_SWAP = 'https://lite-api.jup.ag/swap/v1/swap';
const HEADERS = {
  'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
  Accept: 'application/json',
  Origin: 'https://jup.ag',
};

function isRealRewardSlot(rk) {
  const mint = String(rk?.mint?.address ?? rk?.mint ?? '');
  const vault = String(rk?.vault ?? '');
  return mint && mint !== ZERO_PUBKEY && vault && vault !== ZERO_PUBKEY;
}

async function poolInfoWithRewardDefaults({ raydium, connection, poolInfo, poolKeys }) {
  const merged = [];
  const seen = new Set();
  for (const ex of poolInfo.rewardDefaultInfos || []) {
    const m = String(ex?.mint?.address ?? '');
    if (m && m !== ZERO_PUBKEY) {
      merged.push(ex);
      seen.add(m);
    }
  }
  for (const rk of poolKeys.rewardInfos || []) {
    if (!isRealRewardSlot(rk)) continue;
    const mintAddr = String(rk.mint?.address ?? rk.mint);
    if (seen.has(mintAddr)) continue;
    const acct = await connection.getAccountInfo(new PublicKey(mintAddr));
    merged.push({
      mint: {
        address: mintAddr,
        programId: acct?.owner?.toBase58?.() ?? TOKEN_PROGRAM_ID.toBase58(),
      },
      perSecond: 0,
    });
    seen.add(mintAddr);
  }
  if (!merged.length) return poolInfo;
  return { ...poolInfo, rewardDefaultInfos: merged };
}

async function pollConfirm(connection, signature, timeoutMs = 60_000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    await new Promise((r) => setTimeout(r, 2_000));
    try {
      const s = (await connection.getSignatureStatuses([signature]))?.value?.[0];
      if (s) {
        if (s.err) throw new Error('tx ' + signature + ' reverted: ' + JSON.stringify(s.err));
        if (s.confirmationStatus === 'confirmed' || s.confirmationStatus === 'finalized') return;
      }
    } catch (e) {
      if (String(e).includes('reverted')) throw e;
    }
  }
  throw new Error('tx ' + signature + ' not confirmed within ' + timeoutMs + 'ms');
}

async function jupiterSwap({
  connection, owner, inputMint, outputMint, amountRaw, slippageBps, priorityMicro,
}) {
  const qs = new URLSearchParams({
    inputMint,
    outputMint,
    amount: String(amountRaw),
    slippageBps: String(slippageBps),
    swapMode: 'ExactIn',
  });
  let r = await fetch(`${JUP_QUOTE}?${qs}`, { headers: HEADERS, signal: AbortSignal.timeout(12_000) });
  const quote = await r.json();
  if (!r.ok || quote.error) throw new Error(`jupiter quote: ${quote.error || r.status}`);

  r = await fetch(JUP_SWAP, {
    method: 'POST',
    headers: { ...HEADERS, 'Content-Type': 'application/json' },
    body: JSON.stringify({
      quoteResponse: quote,
      userPublicKey: owner.publicKey.toBase58(),
      wrapAndUnwrapSol: true,
      asLegacyTransaction: false,
      computeUnitPriceMicroLamports: Number(priorityMicro ?? 2_000),
    }),
    signal: AbortSignal.timeout(12_000),
  });
  const swap = await r.json();
  if (!r.ok || swap.error) throw new Error(`jupiter swap: ${swap.error || r.status}`);

  const tx = VersionedTransaction.deserialize(Buffer.from(swap.swapTransaction, 'base64'));
  tx.sign([owner]);
  const sig = await connection.sendTransaction(tx, { skipPreflight: false, maxRetries: 3 });
  await pollConfirm(connection, sig);
  return { signature: sig, in_amount: quote.inAmount, out_amount: quote.outAmount };
}

function buildKeepSet(inp) {
  const keep = new Set(DEFAULT_KEEP);
  if (Array.isArray(inp.trash_keep_mints)) {
    for (const m of inp.trash_keep_mints) {
      if (m) keep.add(String(m));
    }
  }
  const payOut = String(inp.trash_output_mint || inp.pay_output_mint || WSOL_MINT);
  keep.add(payOut);
  return keep;
}

function shouldSwapFeeMint(mint, keepSet) {
  return Boolean(mint) && !keepSet.has(mint);
}

async function findOwnerPosition(raydium, nftMint) {
  const allPositions = await raydium.clmm.getOwnerPositionInfo({});
  return allPositions.find((p) => p?.nftMint?.toBase58?.() === nftMint.toBase58()) ?? null;
}

async function sweepFeeLegs({
  connection, owner, legs, slippageBps, priorityMicro, maxAttempts, trashOutputMint, keepSet,
}) {
  const outputMint = trashOutputMint || WSOL_MINT;
  const results = [];
  for (const { mint, amountRaw, label } of legs) {
    const raw = Number(amountRaw || 0);
    if (!shouldSwapFeeMint(mint, keepSet) || raw <= TRASH_DUST_RAW) {
      results.push({
        mint,
        label,
        performed: false,
        reason: raw <= TRASH_DUST_RAW ? 'below_dust_or_zero' : 'pay_type_kept',
        amount_raw: String(amountRaw),
      });
      continue;
    }
    let lastErr = null;
    let success = null;
    for (let attempt = 1; attempt <= maxAttempts; attempt++) {
      try {
        const r = await jupiterSwap({
          connection,
          owner,
          inputMint: mint,
          outputMint,
          amountRaw: raw,
          slippageBps,
          priorityMicro,
        });
        success = {
          performed: true,
          mint,
          label,
          attempt,
          signature: r.signature,
          swapped_in_amount: r.in_amount,
          swapped_out_amount: r.out_amount,
        };
        break;
      } catch (e) {
        lastErr = e;
      }
    }
    if (success) results.push(success);
    else {
      results.push({
        performed: false,
        abandoned_unsellable: true,
        mint,
        label,
        attempts: maxAttempts,
        amount_raw: String(amountRaw),
        reason: lastErr?.message || 'swap failed',
      });
    }
  }
  return results;
}

async function main() {
  const inp = await readStdinJson();
  const { raydium, owner, connection } = await bootRaydium(inp);

  if (!inp.position_nft_mint) {
    return finish({ ok: false, error: 'position_nft_mint is required' });
  }
  const nftMint = new PublicKey(inp.position_nft_mint);
  const me = await findOwnerPosition(raydium, nftMint);
  if (!me) {
    return finish({
      ok: false,
      error: `position ${inp.position_nft_mint} not found for owner`,
    });
  }
  if (me.liquidity.isZero()) {
    return finish({
      ok: false,
      error: 'position has zero liquidity; use close/burn instead of harvest',
      position_nft_mint: inp.position_nft_mint,
    });
  }

  const poolData = await raydium.clmm.getPoolInfoFromRpc(me.poolId.toBase58());
  if (!poolData) return finish({ ok: false, error: 'pool fetch failed' });
  let { poolInfo, poolKeys } = poolData;
  poolInfo = await poolInfoWithRewardDefaults({ raydium, connection, poolInfo, poolKeys });

  const payOutMint = String(inp.trash_output_mint || inp.pay_output_mint || WSOL_MINT);
  const useSOLBalance = Boolean(inp.use_sol_balance ?? payOutMint === WSOL_MINT);
  const sweepToPay = inp.sweep_non_pay_to_pay_type !== false;
  const slippageBps = Number(inp.slippage_bps ?? 100);
  const slippage = slippageBps / 10000;
  const priorityMicro = Number(
    inp.jupiter_priority_micro_lamports ?? inp.priority_fee_micro_lamports ?? 2_000,
  );
  const computeUnits = Number(inp.compute_units ?? 200_000);
  const maxAttempts = Math.max(1, Number(inp.trash_swap_max_attempts ?? 2));
  const keepSet = buildKeepSet(inp);

  const { execute, extInfo } = await raydium.clmm.decreaseLiquidity({
    poolInfo,
    poolKeys,
    ownerPosition: me,
    liquidity: new BN(0),
    amountMinA: new BN(0),
    amountMinB: new BN(0),
    slippage,
    closePosition: false,
    ownerInfo: { useSOLBalance },
    txVersion: TxVersion.V0,
    computeBudgetConfig: {
      units: computeUnits,
      microLamports: Number(inp.priority_fee_micro_lamports ?? 2_000),
    },
  });
  const { txId } = await execute({ sendAndConfirm: false });
  await pollConfirm(raydium.connection, txId);

  const mintA = String(poolInfo.mintA.address);
  const mintB = String(poolInfo.mintB.address);
  const feesA = extInfo?.feeA?.toString?.() ?? '0';
  const feesB = extInfo?.feeB?.toString?.() ?? '0';

  let feeSwaps = [];
  if (sweepToPay) {
    feeSwaps = await sweepFeeLegs({
      connection,
      owner,
      slippageBps,
      priorityMicro,
      maxAttempts,
      trashOutputMint: payOutMint,
      keepSet,
      legs: [
        { mint: mintA, amountRaw: feesA, label: 'fee_mintA' },
        { mint: mintB, amountRaw: feesB, label: 'fee_mintB' },
      ],
    });
  }

  return finish({
    ok: true,
    signature: txId,
    harvest_signature: txId,
    pool_id: me.poolId.toBase58(),
    position_nft_mint: inp.position_nft_mint,
    mint_a: mintA,
    mint_b: mintB,
    mint_a_symbol: poolInfo.mintA.symbol,
    mint_b_symbol: poolInfo.mintB.symbol,
    fees_a_claimed: feesA,
    fees_b_claimed: feesB,
    pay_output_mint: payOutMint,
    sweep_non_pay_to_pay_type: sweepToPay,
    fee_swaps: feeSwaps,
    note:
      'Raydium harvest = decreaseLiquidity(0). Non-pay fee leg swapped to pay-type when enabled.',
  });
}

main().catch(failFromError);
