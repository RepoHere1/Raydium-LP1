/**
 * close_position.mjs v0.6 — close + collect + burn NFT + sweep trash → SOL.
 *
 * Universal rules:
 * 1. After remove-liquidity, if the position NFT still exists with liquidity 0,
 *    run an explicit closePosition (burn) so Raydium UI does not show $0 ghosts.
 * 2. After close, swap any non-SOL / non-stable (USDC, USDT, USD1) received on the
 *    pool legs to SOL via Jupiter, up to trash_swap_max_attempts (default 2).
 */

import {
  readStdinJson, bootRaydium, finish, failFromError,
  BN, PublicKey, TxVersion,
} from './_shared.mjs';
import { VersionedTransaction } from '@solana/web3.js';
import { TOKEN_PROGRAM_ID } from '@solana/spl-token';

const ZERO_PUBKEY = '11111111111111111111111111111111';

/** RPC pool often has rewardDefaultInfos=[] while poolKeys still has live reward slots (SDK 6030). */
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
    await new Promise(r => setTimeout(r, 2_000));
    try {
      const s = (await connection.getSignatureStatuses([signature]))?.value?.[0];
      if (s) {
        if (s.err) throw new Error('tx ' + signature + ' reverted: ' + JSON.stringify(s.err));
        if (s.confirmationStatus === 'confirmed' || s.confirmationStatus === 'finalized') return;
      }
    } catch (e) { if (String(e).includes('reverted')) throw e; }
  }
  throw new Error('tx ' + signature + ' not confirmed within ' + timeoutMs + 'ms');
}

const WSOL_MINT = 'So11111111111111111111111111111111111111112';
const USDC_MINT = 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v';
const USDT_MINT = 'Es9vMFrzaCERmJfrF4H2FYD4KConky11McCe8BenwNYB';
const USD1_MINT = 'USD1ttGY1N17NEEHLmELoaybftRBUSErhqYiQzvEmuB';
const KEEP_MINTS = new Set([WSOL_MINT, USDC_MINT, USDT_MINT, USD1_MINT]);
const TRASH_DUST_RAW = 10_000;

const JUP_QUOTE = 'https://lite-api.jup.ag/swap/v1/quote';
const JUP_SWAP = 'https://lite-api.jup.ag/swap/v1/swap';
const HEADERS = {
  'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
  Accept: 'application/json',
  Origin: 'https://jup.ag',
};

async function jupiterSwap({
  connection, owner, inputMint, outputMint, amountRaw, slippageBps, priorityMicro,
}) {
  const qs = new URLSearchParams({
    inputMint, outputMint,
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

function buildTrashKeepSet(inp) {
  const keep = new Set(KEEP_MINTS);
  if (Array.isArray(inp.trash_keep_mints)) {
    for (const m of inp.trash_keep_mints) {
      if (m) keep.add(String(m));
    }
  }
  return keep;
}

function isTrashMint(mint, keepSet) {
  return Boolean(mint) && !keepSet.has(mint);
}

async function findOwnerPosition(raydium, nftMint) {
  const allPositions = await raydium.clmm.getOwnerPositionInfo({});
  return allPositions.find((p) => p?.nftMint?.toBase58?.() === nftMint.toBase58()) ?? null;
}

/** Burn empty NFT still owned after decreaseLiquidity (Raydium ghost rows). */
async function ensureBurnEmptyNft({
  raydium, connection, inp, nftMint, poolInfo, poolKeys,
}) {
  if (inp.keep_position || inp.ensure_burn_nft === false) {
    return { performed: false, reason: inp.keep_position ? 'keep_position' : 'ensure_burn_disabled' };
  }
  const still = await findOwnerPosition(raydium, nftMint);
  if (!still) {
    return { performed: false, already_gone: true, reason: 'nft_not_in_wallet' };
  }
  const liquidity = new BN(still.liquidity.toString());
  if (!liquidity.isZero()) {
    return {
      performed: false,
      reason: 'liquidity_nonzero',
      liquidity: liquidity.toString(),
    };
  }
  const { execute } = await raydium.clmm.closePosition({
    poolInfo,
    poolKeys,
    ownerPosition: still,
    txVersion: TxVersion.V0,
    computeBudgetConfig: {
      units: Number(inp.burn_compute_units ?? inp.compute_units ?? 200_000),
      microLamports: Number(inp.priority_fee_micro_lamports ?? 2_000),
    },
  });
  const { txId } = await execute({ sendAndConfirm: false });
  await pollConfirm(connection, txId);
  const after = await findOwnerPosition(raydium, nftMint);
  return {
    performed: true,
    burn_signature: txId,
    nft_still_present: Boolean(after),
    note: 'burned empty position NFT (liquidity was 0)',
  };
}

async function sweepTrashLegs({
  connection, owner, legs, slippageBps, priorityMicro, maxAttempts, trashOutputMint, keepSet,
}) {
  const outputMint = trashOutputMint || WSOL_MINT;
  const results = [];
  for (const { mint, amountRaw, label } of legs) {
    if (!isTrashMint(mint, keepSet) || Number(amountRaw) <= TRASH_DUST_RAW) {
      results.push({
        mint, label, performed: false, reason: 'not_trash_or_below_dust', amount_raw: String(amountRaw),
      });
      continue;
    }
    let lastErr = null;
    let success = null;
    for (let attempt = 1; attempt <= maxAttempts; attempt++) {
      try {
        const r = await jupiterSwap({
          connection, owner,
          inputMint: mint,
          outputMint: outputMint,
          amountRaw,
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
    if (success) {
      results.push(success);
    } else {
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
      error: `position ${inp.position_nft_mint} not found in owner ${owner.publicKey.toBase58()}`,
    });
  }

  const poolData = await raydium.clmm.getPoolInfoFromRpc(me.poolId.toBase58());
  if (!poolData) return finish({ ok: false, error: `pool ${me.poolId.toBase58()} fetch failed` });
  let { poolInfo, poolKeys } = poolData;
  poolInfo = await poolInfoWithRewardDefaults({ raydium, connection, poolInfo, poolKeys });

  const liquidity = new BN(me.liquidity.toString());
  const slippageBps = Number(inp.slippage_bps ?? 100);
  const slippage = slippageBps / 10000;
  const priorityMicro = Number(
    inp.jupiter_priority_micro_lamports ?? inp.priority_fee_micro_lamports ?? 2_000,
  );
  const sweepTrash = inp.sweep_trash_to_sol !== false;
  const maxAttempts = Math.max(1, Number(inp.trash_swap_max_attempts ?? 2));
  const trashKeep = buildTrashKeepSet(inp);
  const trashOutputMint = String(inp.trash_output_mint || WSOL_MINT);

  let closeResult;
  if (liquidity.isZero() && !inp.keep_position) {
    const { execute } = await raydium.clmm.closePosition({
      poolInfo, poolKeys, ownerPosition: me, txVersion: TxVersion.V0,
    });
    const { txId } = await execute({ sendAndConfirm: false });
    await pollConfirm(raydium.connection, txId);
    closeResult = {
      signature: txId, position_closed: true,
      amount_a_received: '0', amount_b_received: '0',
      fees_a_claimed: '0', fees_b_claimed: '0',
      note: 'liquidity was already 0; closed empty NFT',
    };
  } else {
    const { execute, extInfo } = await raydium.clmm.decreaseLiquidity({
      poolInfo, poolKeys, ownerPosition: me,
      liquidity, amountMinA: new BN(0), amountMinB: new BN(0),
      slippage, closePosition: !inp.keep_position,
      ownerInfo: { useSOLBalance: true },
      txVersion: TxVersion.V0,
      computeBudgetConfig: {
        units: Number(inp.compute_units ?? 280_000),
        microLamports: Number(inp.priority_fee_micro_lamports ?? 2_000),
      },
    });
    const { txId } = await execute({ sendAndConfirm: false });
    await pollConfirm(raydium.connection, txId);
    closeResult = {
      signature: txId,
      position_closed: !inp.keep_position,
      amount_a_received: extInfo?.amountA?.toString?.() ?? '0',
      amount_b_received: extInfo?.amountB?.toString?.() ?? '0',
      fees_a_claimed: extInfo?.feeA?.toString?.() ?? '0',
      fees_b_claimed: extInfo?.feeB?.toString?.() ?? '0',
    };
  }

  const mintA = String(poolInfo.mintA.address);
  const mintB = String(poolInfo.mintB.address);
  let trashSwaps = [];
  if (sweepTrash) {
    trashSwaps = await sweepTrashLegs({
      connection,
      owner,
      slippageBps,
      priorityMicro,
      maxAttempts,
      trashOutputMint,
      keepSet: trashKeep,
      legs: [
        { mint: mintA, amountRaw: closeResult.amount_a_received, label: 'mintA' },
        { mint: mintB, amountRaw: closeResult.amount_b_received, label: 'mintB' },
      ],
    });
  }

  let nftBurn = {
    performed: false,
    reason: 'not_requested',
  };
  if (!inp.keep_position && inp.ensure_burn_nft !== false) {
    try {
      nftBurn = await ensureBurnEmptyNft({
        raydium,
        connection,
        inp,
        nftMint,
        poolInfo,
        poolKeys,
      });
    } catch (e) {
      nftBurn = { performed: false, error: String(e), reason: 'burn_failed' };
    }
  }

  const anyAbandoned = trashSwaps.some((s) => s.abandoned_unsellable);
  const anyPerformed = trashSwaps.some((s) => s.performed);

  return finish({
    ok: true,
    close_signature: closeResult.signature,
    amount_a_received: closeResult.amount_a_received,
    amount_b_received: closeResult.amount_b_received,
    fees_a_claimed: closeResult.fees_a_claimed,
    fees_b_claimed: closeResult.fees_b_claimed,
    position_closed: closeResult.position_closed,
    position_nft_burned: Boolean(nftBurn.performed) && !nftBurn.nft_still_present,
    nft_burn: nftBurn,
    note: closeResult.note,
    sweep_trash_to_sol: sweepTrash,
    trash_output_mint: trashOutputMint,
    trash_swap_max_attempts: maxAttempts,
    trash_swaps: trashSwaps,
    payout_swap: {
      performed: anyPerformed,
      abandoned_unsellable: anyAbandoned,
      trash_swaps: trashSwaps,
    },
  });
}

main().catch(failFromError);
