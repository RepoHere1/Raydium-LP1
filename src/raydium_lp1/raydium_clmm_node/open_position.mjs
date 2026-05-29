/**
 * open_position.mjs v0.11 — Raydium CLMM position opener.
 *
 * v0.7: SDK probe revealed the working path:
 *   TickUtil.priceToSqrtPriceX64(price, mintA.decimals, mintB.decimals)
 *     → sqrtX64
 *   TickUtil.getTickAtSqrtPrice(sqrtX64) → tick
 * (The SDK's higher-level getPriceAndTick and priceToTick are buggy in
 *  0.2.49-alpha — they NaN and throw "e.div is not a function" respectively.)
 *
 * Modes:
 *   single_side: "above"  → band entirely above current price → only mintA needed
 *   single_side: "below"  → band entirely below current price → only mintB needed
 *   single_side: null     → straddling band (both tokens needed)
 */

import {
  readStdinJson, bootRaydium, finish, failFromError, fetchTokenAccountData,
  BN, PublicKey, TxVersion,
} from './_shared.mjs';
import { PoolUtils, TickUtil } from '@raydium-io/raydium-sdk-v2';
import Decimal from 'decimal.js';

async function refreshOwnerTokenAccounts(raydium, connection, owner) {
  const tokenAccountData = await fetchTokenAccountData(connection, owner);
  if (typeof raydium.account.updateTokenAccount === 'function') {
    raydium.account.updateTokenAccount(tokenAccountData);
  }
  return tokenAccountData;
}

function priceToValidTick(priceDecimal, decA, decB, tickSpacing) {
  const sqrtX = TickUtil.priceToSqrtPriceX64(priceDecimal, decA, decB);
  const rawTick = TickUtil.getTickAtSqrtPrice(sqrtX);
  if (!Number.isFinite(rawTick)) return null;
  // Snap to nearest valid tick spacing
  return Math.round(rawTick / tickSpacing) * tickSpacing;
}

function alignTickUp(tick, spacing) {
  return Math.ceil(tick / spacing) * spacing;
}

function alignTickDown(tick, spacing) {
  return Math.floor(tick / spacing) * spacing;
}

function computeTickBand(poolInfo, inp) {
  const spot = Number(poolInfo.price);
  const singleSide = inp.single_side || null;
  const decA = poolInfo.mintA?.decimals ?? poolInfo.mintDecimalsA;
  const decB = poolInfo.mintB?.decimals ?? poolInfo.mintDecimalsB;
  const tickSpacing = poolInfo.config?.tickSpacing ?? poolInfo.tickSpacing ?? 1;
  const tickCurrent = Number(
    poolInfo.tickCurrent ?? poolInfo.tick ?? poolInfo.currentTick ?? 0
  );

  let priceLower, priceUpper, lo, hi;
  const minSteps = Math.max(2, Number(inp.min_tick_steps ?? 2));
  const widthSteps = Math.max(4, Number(inp.band_tick_steps ?? 10));

  if (singleSide === "above" && Number.isFinite(tickCurrent)) {
    lo = alignTickUp(tickCurrent + tickSpacing, tickSpacing);
    hi = lo + widthSteps * tickSpacing;
    priceLower = spot * (1 + Number(inp.single_side_start_pct ?? 0.5) / 100);
    priceUpper = spot * (1 + (Number(inp.single_side_start_pct ?? 0.5) + Number(inp.single_side_width_pct ?? 15)) / 100);
  } else if (singleSide === "below" && Number.isFinite(tickCurrent)) {
    hi = alignTickDown(tickCurrent - tickSpacing, tickSpacing);
    lo = hi - widthSteps * tickSpacing;
    priceUpper = spot * (1 - Number(inp.single_side_start_pct ?? 0.5) / 100);
    priceLower = spot * (1 - (Number(inp.single_side_start_pct ?? 0.5) + Number(inp.single_side_width_pct ?? 15)) / 100);
  } else if (singleSide === "above") {
    const start = Number(inp.single_side_start_pct ?? 1);
    const width = Number(inp.single_side_width_pct ?? 5);
    priceLower = spot * (1 + start / 100);
    priceUpper = spot * (1 + (start + width) / 100);
    lo = priceToValidTick(new Decimal(priceLower), decA, decB, tickSpacing);
    hi = priceToValidTick(new Decimal(priceUpper), decA, decB, tickSpacing);
  } else if (singleSide === "below") {
    const start = Number(inp.single_side_start_pct ?? 1);
    const width = Number(inp.single_side_width_pct ?? 5);
    priceUpper = spot * (1 - start / 100);
    priceLower = spot * (1 - (start + width) / 100);
    lo = priceToValidTick(new Decimal(priceLower), decA, decB, tickSpacing);
    hi = priceToValidTick(new Decimal(priceUpper), decA, decB, tickSpacing);
  } else {
    const lowerPctBelow = Number(inp.tick_lower_pct_below ?? 10);
    const upperPctAbove = Number(inp.tick_upper_pct_above ?? 10);
    priceLower = spot * (1 - lowerPctBelow / 100);
    priceUpper = spot * (1 + upperPctAbove / 100);
    lo = priceToValidTick(new Decimal(priceLower), decA, decB, tickSpacing);
    hi = priceToValidTick(new Decimal(priceUpper), decA, decB, tickSpacing);
  }

  if (lo === null || hi === null) {
    return { error: `tick conversion produced NaN; lo=${lo} hi=${hi}` };
  }
  lo = Math.min(lo, hi);
  hi = Math.max(lo, hi);
  if (lo === hi) {
    return { error: `tick band collapsed at tick=${lo}; widen the band` };
  }
  return { spot, priceLower, priceUpper, lo, hi, tickSpacing, decA, decB, tickCurrent, singleSide };
}

async function main() {
  const inp = await readStdinJson();
  const { raydium, owner, connection } = await bootRaydium(inp);

  // 1. Fetch pool
  const poolPk = new PublicKey(inp.pool_id);
  const poolData = await raydium.clmm.getPoolInfoFromRpc(poolPk.toBase58());
  if (!poolData || !poolData.poolInfo) {
    return finish({ ok: false, error: `pool ${inp.pool_id} not found or not CLMM` });
  }
  const { poolInfo, poolKeys } = poolData;
  const payMintOnly = Boolean(inp.pay_mint_only);

  const widthStepsList = [
    Number(inp.band_tick_steps ?? 10),
    16,
    24,
    32,
  ].filter((v, i, a) => Number.isFinite(v) && v > 0 && a.indexOf(v) === i);

  let band = null;
  for (const ws of widthStepsList) {
    band = computeTickBand(poolInfo, { ...inp, band_tick_steps: ws });
    if (band.error) continue;
    const { lo, hi, tickSpacing, decA, decB, tickCurrent } = band;
    const inputMintStr = String(inp.input_mint || '');
    const mintAStr = String(poolInfo.mintA.address ?? poolInfo.mintA.address?.toString?.() ?? '');
    const mintBStr = String(poolInfo.mintB.address ?? poolInfo.mintB.address?.toString?.() ?? '');
    let baseIn =
      inputMintStr === mintAStr ||
      inputMintStr === String(poolInfo.mintA.address?.toString?.());
    if (payMintOnly && inputMintStr && inputMintStr !== mintAStr && inputMintStr !== mintBStr) {
      return finish({
        ok: false,
        error: `pay_mint_only: input_mint ${inputMintStr} is not mintA or mintB for this pool`,
      });
    }
    const tryBaseInOrder = payMintOnly ? [baseIn] : [baseIn, !baseIn];
    const inputDecimals = baseIn ? decA : decB;
    const inputAmount = new BN(
      new Decimal(inp.input_amount_human).mul(10 ** inputDecimals).toFixed(0)
    );
    const slippage = Number(inp.slippage_bps ?? 100) / 10000;
    const epochInfo = await raydium.connection.getEpochInfo();
    for (const tryBaseIn of tryBaseInOrder) {
      const probe = await PoolUtils.getLiquidityAmountOutFromAmountIn({
        poolInfo, inputA: tryBaseIn,
        tickLower: lo, tickUpper: hi,
        amount: inputAmount, slippage, add: true, epochInfo, amountHasFee: true,
      });
      const liqBN = probe?.liquidity;
      if (liqBN && typeof liqBN.gt === "function" && liqBN.gt(new BN(0))) {
        band._liq = probe;
        band._finalBaseIn = tryBaseIn;
        band._inputAmount = inputAmount;
        band._slippage = slippage;
        band._band_tick_steps = ws;
        break;
      }
    }
    if (band._liq) break;
  }

  if (!band || !band._liq) {
    const last = computeTickBand(poolInfo, inp);
    const inputMintStr = String(inp.input_mint || '');
    const baseIn =
      inputMintStr === String(poolInfo.mintA.address) ||
      inputMintStr === String(poolInfo.mintA.address?.toString?.());
    const decA = last.decA ?? poolInfo.mintA?.decimals;
    const decB = last.decB ?? poolInfo.mintB?.decimals;
    const inputDecimals = baseIn ? decA : decB;
    const inputAmount = new BN(
      new Decimal(inp.input_amount_human).mul(10 ** inputDecimals).toFixed(0)
    );
    return finish({
      ok: false,
      error: "SDK computed liquidity=0 for all tick bands (would fail on-chain with error 6047)",
      diagnostic: {
        spot: last.spot,
        tickCurrent: last.tickCurrent,
        priceLower: last.priceLower,
        priceUpper: last.priceUpper,
        tickLower: last.lo,
        tickUpper: last.hi,
        tickSpacing: last.tickSpacing,
        decA, decB,
        mintA_address: String(poolInfo.mintA?.address ?? ''),
        mintB_address: String(poolInfo.mintB?.address ?? ''),
        input_amount_lamports: inputAmount.toString(),
        hint: "Try more SOL (0.005+), wider band, or a SOL/USDC pool; amount may be below CLMM minimum for this spacing",
      },
    });
  }

  const { lo, hi, spot, priceLower, priceUpper, tickSpacing, _liq: liq, _finalBaseIn: finalBaseIn, _inputAmount: inputAmount, tickCurrent, _band_tick_steps: bandSteps } = band;

  // Refresh wallet ATAs so USDC/SPL pays work after a new token account is funded.
  await refreshOwnerTokenAccounts(raydium, connection, owner);

  const inputMintStr = String(inp.input_mint || '');
  const wsolMint = 'So11111111111111111111111111111111111111112';
  const useSolBalance = inputMintStr === wsolMint;

  // Map probe slippage to the non-base leg; SDK uses it as amountA when base=MintB.
  let otherAmountMax = finalBaseIn
    ? (liq.amountSlippageB?.amount ?? new BN(0))
    : (liq.amountSlippageA?.amount ?? new BN(0));
  if (payMintOnly) {
    otherAmountMax = new BN(0);
  }

  // SDK getOrCreateTokenAccount always re-fetches and can drop freshly funded ATAs.
  const origFetch = raydium.account.fetchWalletTokenAccounts?.bind(raydium.account);
  if (origFetch) {
    raydium.account.fetchWalletTokenAccounts = async () => ({
      tokenAccounts: raydium.account.tokenAccounts,
      tokenAccountRawInfos: raydium.account.tokenAccountRawInfos,
    });
  }

  let execute, extInfo;
  try {
    ({ execute, extInfo } = await raydium.clmm.openPositionFromBase({
      poolInfo, poolKeys,
      tickLower:      lo,
      tickUpper:      hi,
      base:           finalBaseIn ? 'MintA' : 'MintB',
      baseAmount:     inputAmount,
      otherAmountMax,
      associatedOnly: true,
      ownerInfo: {
        useSOLBalance: useSolBalance,
      },
      txVersion:      TxVersion.V0,
      computeBudgetConfig: {
        units:        Number(inp.compute_units ?? 200_000),
        microLamports: Number(inp.priority_fee_micro_lamports ?? 2_000),
      },
    }));
  } finally {
    if (origFetch) {
      raydium.account.fetchWalletTokenAccounts = origFetch;
    }
  }

  // 7. Broadcast — sendAndConfirm uses signatureSubscribe which Alchemy/Helius
  // free tier doesn't support on HTTP. Send manually, poll via HTTP statuses.
  const { txId } = await execute({ sendAndConfirm: false });

  // Poll for confirmation up to 60 seconds via getSignatureStatuses (HTTP only)
  let confirmed = false;
  let confirmErr = null;
  for (let i = 0; i < 30; i++) {
    await new Promise(r => setTimeout(r, 2_000));
    try {
      const status = await raydium.connection.getSignatureStatuses([txId]);
      const s = status?.value?.[0];
      if (s) {
        if (s.err) { confirmErr = JSON.stringify(s.err); break; }
        if (s.confirmationStatus === "confirmed" || s.confirmationStatus === "finalized") {
          confirmed = true;
          break;
        }
      }
    } catch (_) { /* keep polling */ }
  }

  return finish({
    ok:                    !confirmErr,
    signature:             txId,
    confirmed,
    confirm_error:         confirmErr,
    position_nft_mint:     extInfo?.nftMint?.toBase58() || null,
    tick_lower:            lo,
    tick_upper:            hi,
    price_lower:           priceLower,
    price_upper:           priceUpper,
    spot_price:            spot,
    tick_current:          tickCurrent,
    band_tick_steps:       bandSteps,
    tick_spacing:          tickSpacing,
    single_side_mode:      inp.single_side ?? null,
    pay_mint_only:         payMintOnly,
    pay_symbol:            inp.pay_symbol ?? null,
    input_amount_lamports: inputAmount.toString(),
    other_amount_max:      otherAmountMax.toString(),
    pool_id:               inp.pool_id,
    owner:                 owner.publicKey.toBase58(),
    final_baseIn:          finalBaseIn,
  });
}

main().catch(failFromError);
