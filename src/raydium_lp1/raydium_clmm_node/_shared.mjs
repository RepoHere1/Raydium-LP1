/**
 * _shared.mjs — common boot for every CLMM Node script.
 *
 *   - reads JSON from stdin
 *   - loads keypair from disk (Solana CLI format: JSON array of bytes)
 *   - boots @raydium-io/raydium-sdk-v2 Raydium client against Mainnet
 *   - prints exactly ONE JSON line to stdout and exits
 *
 * stdin contract (common fields every script accepts):
 *   {
 *     "rpc_url":       "https://...",   // required
 *     "keypair_path":  "/path/key.json",// required (Solana CLI JSON-array file)
 *     "priority_fee_micro_lamports": 50000,  // optional, default 50_000
 *     ... script-specific fields ...
 *   }
 *
 * stdout contract:
 *   on success:  {"ok": true, ...result fields...}
 *   on failure:  {"ok": false, "error": "...", "stack": "..."}
 *   process exit code: 0 on success, 1 on failure
 */

import { readFileSync } from 'node:fs';
import { Connection, Keypair, PublicKey, ComputeBudgetProgram, sendAndConfirmTransaction } from '@solana/web3.js';
import { Raydium, TxVersion, parseTokenAccountResp } from '@raydium-io/raydium-sdk-v2';
import { TOKEN_PROGRAM_ID, TOKEN_2022_PROGRAM_ID } from '@solana/spl-token';
import BN from 'bn.js';
import bs58 from 'bs58';

export async function readStdinJson() {
  return new Promise((resolve, reject) => {
    let buf = '';
    process.stdin.setEncoding('utf-8');
    process.stdin.on('data', (chunk) => { buf += chunk; });
    process.stdin.on('end',  () => {
      try { resolve(JSON.parse(buf || '{}')); }
      catch (e) { reject(new Error(`stdin not valid JSON: ${e.message}`)); }
    });
    process.stdin.on('error', reject);
  });
}

export function loadKeypairFromFile(path) {
  const raw = readFileSync(path, 'utf-8').trim();
  const arr = JSON.parse(raw);
  if (!Array.isArray(arr)) {
    throw new Error(`keypair file ${path} must be a JSON array of 64 bytes`);
  }
  return Keypair.fromSecretKey(Uint8Array.from(arr));
}

export async function fetchTokenAccountData(connection, owner) {
  const solAccountResp = await connection.getAccountInfo(owner.publicKey);
  const tokenAccountResp = await connection.getTokenAccountsByOwner(owner.publicKey, {
    programId: TOKEN_PROGRAM_ID,
  });
  let merged = tokenAccountResp.value;
  try {
    const token2022Req = await connection.getTokenAccountsByOwner(owner.publicKey, {
      programId: TOKEN_2022_PROGRAM_ID,
    });
    merged = [...tokenAccountResp.value, ...token2022Req.value];
  } catch { /* TOKEN_2022 optional */ }
  return parseTokenAccountResp({
    owner: owner.publicKey,
    solAccountResp,
    tokenAccountResp: { context: tokenAccountResp.context, value: merged },
  });
}

export async function bootRaydium({ rpc_url, keypair_path }) {
  if (!rpc_url)      throw new Error('rpc_url is required');
  if (!keypair_path) throw new Error('keypair_path is required');

  const connection = new Connection(rpc_url, { commitment: 'confirmed' });
  const owner      = loadKeypairFromFile(keypair_path);
  const tokenAccountData = await fetchTokenAccountData(connection, owner);
  const raydium    = await Raydium.load({
    connection,
    owner,
    cluster: 'mainnet',
    disableFeatureCheck: true,
    blockhashCommitment: 'confirmed',
    tokenAccounts: tokenAccountData.tokenAccounts,
    tokenAccountRawInfos: tokenAccountData.tokenAccountRawInfos,
  });
  return { raydium, connection, owner, tokenAccountData };
}

export function finish(obj) {
  process.stdout.write(JSON.stringify(obj) + '\n');
  process.exit(obj.ok ? 0 : 1);
}

/** Catch-all unhandled error → fail JSON. */
export function failFromError(err) {
  finish({
    ok: false,
    error: err?.message || String(err),
    stack: err?.stack ? err.stack.split('\n').slice(0, 4).join(' | ') : undefined,
  });
}

export { BN, bs58, PublicKey, TxVersion, ComputeBudgetProgram, sendAndConfirmTransaction };
