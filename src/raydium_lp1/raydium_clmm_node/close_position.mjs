/**
 * close_position.mjs v0.4 — close + collect + optional Jupiter-swap to SOL.
 *
 * v0.3: payout_as="SOL" — after the SDK close confirms, swap any received
 * non-SOL token (e.g. USDC) back to SOL via Jupiter so you never get stuck
 * with dust tokens.
 */

import {
  readStdinJson, bootRaydium, finish, failFromError,
  BN, PublicKey, TxVersion,
} from './_shared.mjs';
import { VersionedTransaction } from '@solana/web3.js';

// v0.4 — HTTP-only confirmation, replaces sendAndConfirm:true which needs
// signatureSubscribe (WebSocket-only, missing on Alchemy/Helius free HTTP).
async function pollConfirm(connection, signature, timeoutMs = 60_000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    await new Promise(r => setTimeout(r, 2_000));
    try {
      const s = (await connection.getSignatureStatuses([signature]))?.value?.[0];
      if (s) {
        if (s.err) throw new Error("tx " + signature + " reverted: " + JSON.stringify(s.err));
        if (s.confirmationStatus === "confirmed" || s.confirmationStatus === "finalized") return;
      }
    } catch (e) { if (String(e).includes("reverted")) throw e; }
  }
  throw new Error("tx " + signature + " not confirmed within " + timeoutMs + "ms");
}

const WSOL_MINT     = "So11111111111111111111111111111111111111112";
const USDC_DUST_RAW = 10_000;  // $0.01 — don't swap less

const JUP_QUOTE = "https://lite-api.jup.ag/swap/v1/quote";
const JUP_SWAP  = "https://lite-api.jup.ag/swap/v1/swap";

const HEADERS = {
  "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0",
  "Accept":     "application/json",
  "Origin":     "https://jup.ag",
};

async function jupiterSwap({ connection, owner, inputMint, outputMint, amountRaw, slippageBps }) {
  const qs = new URLSearchParams({
    inputMint, outputMint,
    amount: String(amountRaw),
    slippageBps: String(slippageBps),
    swapMode: 'ExactIn',
  });
  let r = await fetch(`${JUP_QUOTE}?${qs}`, { headers: HEADERS, signal: AbortSignal.timeout(10_000) });
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
      computeUnitPriceMicroLamports: Number(inp.jupiter_priority_micro_lamports ?? inp.priority_fee_micro_lamports ?? 2_000),
    }),
    signal: AbortSignal.timeout(10_000),
  });
  const swap = await r.json();
  if (!r.ok || swap.error) throw new Error(`jupiter swap: ${swap.error || r.status}`);

  const raw = Buffer.from(swap.swapTransaction, 'base64');
  const tx  = VersionedTransaction.deserialize(raw);
  tx.sign([owner]);
  const sig = await connection.sendTransaction(tx, { skipPreflight: false, maxRetries: 3 });
  await pollConfirm(connection, sig);   // v0.4: HTTP-only confirm
  return { signature: sig, in_amount: quote.inAmount, out_amount: quote.outAmount };
}

async function main() {
  const inp = await readStdinJson();
  const { raydium, owner, connection } = await bootRaydium(inp);

  if (!inp.position_nft_mint) {
    return finish({ ok: false, error: 'position_nft_mint is required' });
  }
  const nftMint = new PublicKey(inp.position_nft_mint);

  const allPositions = await raydium.clmm.getOwnerPositionInfo({});
  const me = allPositions.find((p) => p?.nftMint?.toBase58?.() === nftMint.toBase58());
  if (!me) {
    return finish({ ok: false, error: `position ${inp.position_nft_mint} not found in owner ${owner.publicKey.toBase58()}` });
  }

  const poolData = await raydium.clmm.getPoolInfoFromRpc(me.poolId.toBase58());
  if (!poolData) return finish({ ok: false, error: `pool ${me.poolId.toBase58()} fetch failed` });
  const { poolInfo, poolKeys } = poolData;

  const liquidity   = new BN(me.liquidity.toString());
  const slippageBps = Number(inp.slippage_bps ?? 100);
  const slippage    = slippageBps / 10000;

  let closeResult;
  if (liquidity.isZero() && !inp.keep_position) {
    const { execute } = await raydium.clmm.closePosition({
      poolInfo, poolKeys, ownerPosition: me, txVersion: TxVersion.V0,
    });
    const { txId } = await execute({ sendAndConfirm: false });   // v0.4: HTTP polling
    await pollConfirm(raydium.connection, txId);
    closeResult = {
      signature: txId, position_closed: true,
      amount_a_received: '0', amount_b_received: '0',
      fees_a_claimed: '0',    fees_b_claimed: '0',
      note: 'liquidity was already 0; closed empty NFT',
    };
  } else {
    const { execute, extInfo } = await raydium.clmm.decreaseLiquidity({
      poolInfo, poolKeys, ownerPosition: me,
      liquidity, amountMinA: new BN(0), amountMinB: new BN(0),
      slippage, closePosition: !inp.keep_position,
      ownerInfo: {                            // v0.4: SDK requires this
        useSOLBalance: true,                  // auto-unwrap WSOL → SOL on close
      },
      txVersion: TxVersion.V0,
      computeBudgetConfig: {
        units: Number(inp.compute_units ?? 280_000),
        microLamports: Number(inp.priority_fee_micro_lamports ?? 2_000),
      },
    });
    const { txId } = await execute({ sendAndConfirm: false });   // v0.4: HTTP polling
    await pollConfirm(raydium.connection, txId);
    closeResult = {
      signature:         txId,
      position_closed:   !inp.keep_position,
      amount_a_received: extInfo?.amountA?.toString?.() ?? '?',
      amount_b_received: extInfo?.amountB?.toString?.() ?? '?',
      fees_a_claimed:    extInfo?.feeA?.toString?.()    ?? '?',
      fees_b_claimed:    extInfo?.feeB?.toString?.()    ?? '?',
    };
  }

  const payoutAs = (inp.payout_as || '').toUpperCase();
  let payoutSwap = { performed: false, reason: 'payout_as not requested' };

  if (payoutAs === 'SOL') {
    const mintA = String(poolInfo.mintA.address);
    const mintB = String(poolInfo.mintB.address);
    let convertMint = null, convertAmount = null;
    if (mintA !== WSOL_MINT && Number(closeResult.amount_a_received) > USDC_DUST_RAW) {
      convertMint = mintA; convertAmount = closeResult.amount_a_received;
    } else if (mintB !== WSOL_MINT && Number(closeResult.amount_b_received) > USDC_DUST_RAW) {
      convertMint = mintB; convertAmount = closeResult.amount_b_received;
    }
    if (!convertMint) {
      payoutSwap = { performed: false, reason: 'nothing to convert (already SOL or below dust)' };
    } else {
      try {
        const r = await jupiterSwap({
          connection, owner,
          inputMint: convertMint, outputMint: WSOL_MINT,
          amountRaw: convertAmount, slippageBps,
        });
        payoutSwap = {
          performed:           true,
          signature:           r.signature,
          swapped_in_mint:     convertMint,
          swapped_in_amount:   r.in_amount,
          swapped_out_mint:    WSOL_MINT,
          swapped_out_amount:  r.out_amount,
        };
      } catch (e) {
        payoutSwap = { performed: false, reason: `swap failed: ${e.message}` };
      }
    }
  }

  return finish({
    ok:                true,
    close_signature:   closeResult.signature,
    amount_a_received: closeResult.amount_a_received,
    amount_b_received: closeResult.amount_b_received,
    fees_a_claimed:    closeResult.fees_a_claimed,
    fees_b_claimed:    closeResult.fees_b_claimed,
    position_closed:   closeResult.position_closed,
    note:              closeResult.note,
    payout_swap:       payoutSwap,
  });
}

main().catch(failFromError);
