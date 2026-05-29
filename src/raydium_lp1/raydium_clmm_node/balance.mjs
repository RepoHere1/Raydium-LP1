/**
 * balance.mjs — read-only wallet balance snapshot.
 *
 * stdin (extends _shared.mjs common fields):
 *   { rpc_url, keypair_path }
 *
 * stdout on success:
 *   {
 *     "ok": true,
 *     "address":      "<wallet pubkey>",
 *     "sol_balance":  0.1234,      // native SOL (decimal, not lamports)
 *     "lamports":     123456789,
 *     "usdc_balance": 25.08,       // if user has a USDC token account; null otherwise
 *     "wsol_balance": 0,           // wrapped SOL ATA balance; usually 0
 *     "rpc_url":      "<URL minus apikey>",
 *     "block_height": 412345678
 *   }
 */

import { readStdinJson, loadKeypairFromFile, finish, failFromError, PublicKey } from './_shared.mjs';
import { Connection, LAMPORTS_PER_SOL } from '@solana/web3.js';
import { getAssociatedTokenAddress, getAccount, TOKEN_PROGRAM_ID } from '@solana/spl-token';

const USDC = new PublicKey('EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v');
const WSOL = new PublicKey('So11111111111111111111111111111111111111112');

async function main() {
  const inp = await readStdinJson();
  if (!inp.rpc_url)      return finish({ ok: false, error: 'rpc_url required' });
  if (!inp.keypair_path) return finish({ ok: false, error: 'keypair_path required' });

  const conn  = new Connection(inp.rpc_url, { commitment: 'confirmed' });
  const owner = loadKeypairFromFile(inp.keypair_path);
  const addr  = owner.publicKey;

  // SOL native
  const lamports = await conn.getBalance(addr);

  // USDC + WSOL ATAs (may not exist yet — that's not an error)
  async function tokenBal(mint, decimals) {
    try {
      const ata = await getAssociatedTokenAddress(mint, addr);
      const acc = await getAccount(conn, ata);
      return Number(acc.amount) / 10 ** decimals;
    } catch (e) {
      // TokenAccountNotFoundError just means user hasn't received any of this token yet
      if (e.name === 'TokenAccountNotFoundError') return 0;
      throw e;
    }
  }
  const [usdc, wsol] = await Promise.all([tokenBal(USDC, 6), tokenBal(WSOL, 9)]);

  const block_height = await conn.getBlockHeight();

  // Mask api-key in URL for display
  const rpc_masked = inp.rpc_url.replace(/api-key=[^&]+/, 'api-key=***');

  return finish({
    ok:           true,
    address:      addr.toBase58(),
    sol_balance:  lamports / LAMPORTS_PER_SOL,
    lamports,
    usdc_balance: usdc,
    wsol_balance: wsol,
    rpc_url:      rpc_masked,
    block_height,
  });
}

main().catch(failFromError);
