/**
 * close_empty_token_accounts.mjs — reclaim ~0.002 SOL rent per empty SPL ATA.
 * Skips WSOL/USDC/USDT, non-zero balances, and optional keep_mints (e.g. position NFTs).
 */

import {
  readStdinJson,
  loadKeypairFromFile,
  finish,
  failFromError,
} from './_shared.mjs';
import { Connection, Transaction } from '@solana/web3.js';
import {
  TOKEN_PROGRAM_ID,
  TOKEN_2022_PROGRAM_ID,
  createCloseAccountInstruction,
} from '@solana/spl-token';

const WSOL = 'So11111111111111111111111111111111111111112';
const USDC = 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v';
const USDT = 'Es9vMFrzaCERmJfrF4H2FYD4KConky11McCe8BenwNYB';
const DEFAULT_KEEP = new Set([WSOL, USDC, USDT]);

async function listEmptyAccounts(connection, owner, keepMints) {
  const rows = [];
  for (const programId of [TOKEN_PROGRAM_ID, TOKEN_2022_PROGRAM_ID]) {
    const resp = await connection.getParsedTokenAccountsByOwner(owner.publicKey, {
      programId,
    }, 'confirmed');
    for (const item of resp.value || []) {
      const pubkey = item.pubkey;
      const parsed = item.account?.data?.parsed?.info;
      if (!parsed) continue;
      const mint = String(parsed.mint || '');
      const amount = BigInt(parsed.tokenAmount?.amount || '0');
      if (amount !== 0n) continue;
      if (keepMints.has(mint)) continue;
      rows.push({
        account: pubkey,
        mint,
        programId,
        lamports: item.account?.lamports ?? 0,
      });
    }
  }
  return rows;
}

async function pollConfirm(connection, signature, timeoutMs = 60_000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    await new Promise((r) => setTimeout(r, 2_000));
    try {
      const s = (await connection.getSignatureStatuses([signature]))?.value?.[0];
      if (s) {
        if (s.err) throw new Error(`tx ${signature} reverted: ${JSON.stringify(s.err)}`);
        if (s.confirmationStatus === 'confirmed' || s.confirmationStatus === 'finalized') return;
      }
    } catch (e) {
      if (String(e).includes('reverted')) throw e;
    }
  }
  throw new Error(`tx ${signature} not confirmed within ${timeoutMs}ms`);
}

async function closeChunk(connection, owner, chunk) {
  const tx = new Transaction();
  for (const row of chunk) {
    tx.add(
      createCloseAccountInstruction(
        row.account,
        owner.publicKey,
        owner.publicKey,
        [],
        row.programId,
      ),
    );
  }
  const { blockhash } = await connection.getLatestBlockhash('confirmed');
  tx.feePayer = owner.publicKey;
  tx.recentBlockhash = blockhash;
  tx.sign(owner);
  const signature = await connection.sendRawTransaction(tx.serialize(), {
    skipPreflight: false,
    maxRetries: 3,
  });
  await pollConfirm(connection, signature);
  return signature;
}

async function main() {
  const inp = await readStdinJson();
  const rpc = inp.rpc_url;
  const keypairPath = inp.keypair_path;
  if (!rpc || !keypairPath) {
    return finish({ ok: false, error: 'rpc_url and keypair_path required' });
  }

  const connection = new Connection(rpc, { commitment: 'confirmed' });
  const owner = loadKeypairFromFile(keypairPath);
  const keepMints = new Set(DEFAULT_KEEP);
  for (const m of inp.keep_mints || []) {
    if (m) keepMints.add(String(m));
  }

  const empty = await listEmptyAccounts(connection, owner, keepMints);
  if (inp.preview_only) {
    const lamports = empty.reduce((s, r) => s + Number(r.lamports || 0), 0);
    return finish({
      ok: true,
      preview_only: true,
      count: empty.length,
      recoverable_lamports: lamports,
      recoverable_sol: lamports / 1e9,
      accounts: empty.map((r) => ({
        account: r.account.toBase58(),
        mint: r.mint,
        lamports: r.lamports,
      })),
    });
  }

  const results = [];
  const batchSize = Math.max(1, Math.min(4, Number(inp.batch_size ?? 3)));
  for (let i = 0; i < empty.length; i += batchSize) {
    const chunk = empty.slice(i, i + batchSize);
    try {
      const signature = await closeChunk(connection, owner, chunk);
      for (const row of chunk) {
        results.push({
          ok: true,
          account: row.account.toBase58(),
          mint: row.mint,
          lamports: row.lamports,
          signature,
        });
      }
    } catch (e) {
      for (const row of chunk) {
        results.push({
          ok: false,
          account: row.account.toBase58(),
          mint: row.mint,
          error: String(e?.message || e),
        });
      }
    }
  }

  const okCount = results.filter((r) => r.ok).length;
  const recovered = results.filter((r) => r.ok).reduce((s, r) => s + Number(r.lamports || 0), 0);
  return finish({
    ok: okCount === results.length,
    closed: okCount,
    failed: results.length - okCount,
    recoverable_lamports: recovered,
    recoverable_sol: recovered / 1e9,
    results,
  });
}

main().catch((e) => failFromError(e));
