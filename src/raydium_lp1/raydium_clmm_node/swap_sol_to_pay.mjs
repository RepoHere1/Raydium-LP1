/**
 * swap_sol_to_pay.mjs — Jupiter swap native SOL → pay token (USDC/USDT/USD1).
 *
 * stdin: { rpc_url, keypair_path, output_mint, amount_lamports, slippage_bps?,
 *          priority_fee_micro_lamports?, jupiter_priority_micro_lamports? }
 */

import { readStdinJson, bootRaydium, finish, failFromError } from './_shared.mjs';
import { VersionedTransaction } from '@solana/web3.js';

const WSOL_MINT = 'So11111111111111111111111111111111111111112';
const JUP_QUOTE = 'https://lite-api.jup.ag/swap/v1/quote';
const JUP_SWAP = 'https://lite-api.jup.ag/swap/v1/swap';
const HEADERS = {
  'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
  Accept: 'application/json',
  Origin: 'https://jup.ag',
};

async function pollConfirm(connection, signature, timeoutMs = 60_000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    await new Promise((r) => setTimeout(r, 2_000));
    const s = (await connection.getSignatureStatuses([signature]))?.value?.[0];
    if (s) {
      if (s.err) throw new Error(`tx reverted: ${JSON.stringify(s.err)}`);
      if (s.confirmationStatus === 'confirmed' || s.confirmationStatus === 'finalized') return;
    }
  }
  throw new Error(`tx ${signature} not confirmed within ${timeoutMs}ms`);
}

async function jupiterSwap({ connection, owner, inputMint, outputMint, amountRaw, slippageBps, priorityMicro }) {
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
  return {
    signature: sig,
    in_amount: quote.inAmount,
    out_amount: quote.outAmount,
  };
}

async function main() {
  const inp = await readStdinJson();
  const outputMint = String(inp.output_mint || '');
  const amountLamports = Number(inp.amount_lamports || 0);
  if (!outputMint) return finish({ ok: false, error: 'output_mint required' });
  const inputMint = String(inp.input_mint || WSOL_MINT);
  const amountRaw = inp.amount_raw != null
    ? String(Math.floor(Number(inp.amount_raw)))
    : String(Math.floor(amountLamports));

  if (inputMint === WSOL_MINT) {
    if (!Number.isFinite(amountLamports) || amountLamports <= 0) {
      if (!inp.amount_raw || Number(inp.amount_raw) <= 0) {
        return finish({ ok: false, error: 'amount_lamports must be > 0 for SOL input' });
      }
    }
  } else if (!amountRaw || Number(amountRaw) <= 0) {
    return finish({ ok: false, error: 'amount_raw must be > 0 for SPL input' });
  }

  const { owner, connection } = await bootRaydium(inp);
  const slippageBps = Number(inp.slippage_bps ?? 150);
  const priorityMicro = Number(
    inp.jupiter_priority_micro_lamports ?? inp.priority_fee_micro_lamports ?? 2_000,
  );

  const swap = await jupiterSwap({
    connection,
    owner,
    inputMint,
    outputMint,
    amountRaw,
    slippageBps,
    priorityMicro,
  });

  return finish({
    ok: true,
    signature: swap.signature,
    input_mint: inputMint,
    output_mint: outputMint,
    in_amount: swap.in_amount,
    out_amount: swap.out_amount,
    amount_lamports: Math.floor(amountLamports),
    slippage_bps: slippageBps,
  });
}

main().catch(failFromError);
