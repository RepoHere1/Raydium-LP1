import { readStdinJson, bootRaydium, finish } from './_shared.mjs';

async function main() {
  const inp = await readStdinJson();
  const { raydium } = await bootRaydium(inp);
  const all = await raydium.clmm.getOwnerPositionInfo({});
  const rows = (all || []).map((p) => ({
    position_nft_mint: p?.nftMint?.toBase58?.() ?? null,
    pool_id: p?.poolId?.toBase58?.() ?? null,
    liquidity: p?.liquidity?.toString?.() ?? '0',
    tick_lower: p?.tickLower,
    tick_upper: p?.tickUpper,
  })).filter((r) => r.position_nft_mint && r.pool_id);
  return finish({ ok: true, positions: rows, count: rows.length });
}

main().catch((e) => finish({ ok: false, error: String(e), stack: e?.stack }));
