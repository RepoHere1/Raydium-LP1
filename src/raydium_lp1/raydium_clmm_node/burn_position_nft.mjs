/**
 * burn_position_nft.mjs — burn a CLMM position NFT when liquidity is already 0.
 * Removes Raydium UI ghost rows ($0 / 0% APR) left after partial closes.
 */

import {
  readStdinJson, bootRaydium, finish, failFromError,
  BN, PublicKey, TxVersion,
} from './_shared.mjs';

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

async function main() {
  const inp = await readStdinJson();
  const { raydium, connection } = await bootRaydium(inp);

  if (!inp.position_nft_mint) {
    return finish({ ok: false, error: 'position_nft_mint is required' });
  }
  const nftMint = new PublicKey(inp.position_nft_mint);
  const allPositions = await raydium.clmm.getOwnerPositionInfo({});
  const me = allPositions.find((p) => p?.nftMint?.toBase58?.() === nftMint.toBase58());
  if (!me) {
    return finish({
      ok: true,
      skipped: true,
      reason: 'nft_not_in_wallet',
      position_nft_burned: true,
    });
  }

  const liquidity = new BN(me.liquidity.toString());
  if (!liquidity.isZero()) {
    return finish({
      ok: false,
      error: `position still has liquidity ${liquidity.toString()}; run close_position.mjs first`,
      liquidity: liquidity.toString(),
    });
  }

  const poolData = await raydium.clmm.getPoolInfoFromRpc(me.poolId.toBase58());
  if (!poolData) return finish({ ok: false, error: `pool ${me.poolId.toBase58()} fetch failed` });
  const { poolInfo, poolKeys } = poolData;

  const { execute } = await raydium.clmm.closePosition({
    poolInfo,
    poolKeys,
    ownerPosition: me,
    txVersion: TxVersion.V0,
    computeBudgetConfig: {
      units: Number(inp.compute_units ?? 200_000),
      microLamports: Number(inp.priority_fee_micro_lamports ?? 2_000),
    },
  });
  const { txId } = await execute({ sendAndConfirm: false });
  await pollConfirm(connection, txId);

  const after = (await raydium.clmm.getOwnerPositionInfo({})).find(
    (p) => p?.nftMint?.toBase58?.() === nftMint.toBase58(),
  );

  return finish({
    ok: true,
    burn_signature: txId,
    position_nft_burned: !after,
    nft_still_present: Boolean(after),
    pool_id: me.poolId.toBase58(),
    note: 'burned empty position NFT',
  });
}

main().catch(failFromError);
