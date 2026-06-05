import { readStdinJson, bootRaydium, finish } from './_shared.mjs';

async function main() {
  const inp = await readStdinJson();
  const { raydium } = await bootRaydium(inp);
  const poolId = inp.pool_id;
  const poolData = await raydium.clmm.getPoolInfoFromRpc(poolId);
  if (!poolData) return finish({ ok: false, error: 'pool not found' });
  const { poolInfo, poolKeys } = poolData;
  return finish({
    ok: true,
    rewardDefaultInfos: (poolInfo.rewardDefaultInfos || []).map((r, i) => ({
      i,
      mint: r.mint?.address,
      programId: r.mint?.programId,
      perSecond: r.perSecond,
    })),
    rewardInfosKeys: (poolKeys.rewardInfos || []).map((r, i) => ({
      i,
      mint: r.mint?.address,
      vault: r.vault,
    })),
  });
}

main().catch((e) => finish({ ok: false, error: String(e), stack: e?.stack }));
