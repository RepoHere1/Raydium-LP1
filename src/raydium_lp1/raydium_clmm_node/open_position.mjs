/**
 * open_position.mjs v0.12 — Raydium CLMM position opener.
 *
 * v0.13: full_range + pay_mint_only bootstraps other leg via narrow-band probe + Jupiter.
 * v0.14: wide_range = centered band (max 80% width); literal pool min/max ticks disabled.
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
import { VersionedTransaction } from '@solana/web3.js';
import Decimal from 'decimal.js';

const WSOL_MINT = 'So11111111111111111111111111111111111111112';
// Raydium CLMM tick limits (sdk-v2 constants.ts)
const MIN_TICK = -443636;
const MAX_TICK = 443636;

function poolFullRangeTicks(tickSpacing) {
  const ts = Math.max(1, Number(tickSpacing) || 1);
  const lo = Math.ceil(MIN_TICK / ts) * ts;
  const hi = Math.floor(MAX_TICK / ts) * ts;
  return { lo, hi };
}
const JUP_QUOTE = 'https://lite-api.jup.ag/swap/v1/quote';
const JUP_SWAP = 'https://lite-api.jup.ag/swap/v1/swap';
const JUP_HEADERS = {
  'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
  Accept: 'application/json',
  Origin: 'https://jup.ag',
};

async function pollConfirm(connection, signature, timeoutMs = 60_000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    await new Promise(r => setTimeout(r, 2_000));
    const s = (await connection.getSignatureStatuses([signature]))?.value?.[0];
    if (s) {
      if (s.err) throw new Error('tx ' + signature + ' reverted: ' + JSON.stringify(s.err));
      if (s.confirmationStatus === 'confirmed' || s.confirmationStatus === 'finalized') return;
    }
  }
  throw new Error('tx ' + signature + ' not confirmed within ' + timeoutMs + 'ms');
}

async function jupiterSwap({
  connection, owner, inputMint, outputMint, amountRaw, slippageBps, priorityMicro, swapMode = 'ExactIn',
}) {
  const qs = new URLSearchParams({
    inputMint, outputMint,
    amount: String(amountRaw),
    slippageBps: String(slippageBps),
    swapMode,
  });
  let r = await fetch(`${JUP_QUOTE}?${qs}`, { headers: JUP_HEADERS, signal: AbortSignal.timeout(15_000) });
  const quote = await r.json();
  if (!r.ok || quote.error) throw new Error(`jupiter quote: ${quote.error || r.status}`);

  r = await fetch(JUP_SWAP, {
    method: 'POST',
    headers: { ...JUP_HEADERS, 'Content-Type': 'application/json' },
    body: JSON.stringify({
      quoteResponse: quote,
      userPublicKey: owner.publicKey.toBase58(),
      wrapAndUnwrapSol: true,
      asLegacyTransaction: false,
      computeUnitPriceMicroLamports: Number(priorityMicro ?? 2_000),
    }),
    signal: AbortSignal.timeout(15_000),
  });
  const swap = await r.json();
  if (!r.ok || swap.error) throw new Error(`jupiter swap: ${swap.error || r.status}`);

  const tx = VersionedTransaction.deserialize(Buffer.from(swap.swapTransaction, 'base64'));
  tx.sign([owner]);
  const sig = await connection.sendTransaction(tx, { skipPreflight: false, maxRetries: 3 });
  await pollConfirm(connection, sig);
  return { signature: sig, in_amount: quote.inAmount, out_amount: quote.outAmount };
}

function tokenBalanceRaw(raydium, mintStr) {
  let total = new BN(0);
  for (const acc of raydium.account.tokenAccounts || []) {
    const m = acc?.mint?.toBase58?.() ?? String(acc?.mint ?? '');
    if (m === mintStr) {
      const amt = acc?.amount;
      if (amt?.add) total = total.add(amt);
      else if (amt != null) total = total.add(new BN(String(amt)));
    }
  }
  return total;
}

async function fundOtherLegIfNeeded({
  raydium, connection, owner, payMintStr, otherMintStr, otherAmountMax, slippageBps, priorityMicro,
}) {
  if (!otherAmountMax || !otherAmountMax.gt(new BN(0))) return { funded: false, reason: 'no_other_leg' };
  const have = tokenBalanceRaw(raydium, otherMintStr);
  if (have.gte(otherAmountMax)) return { funded: false, reason: 'already_have_other_leg', have: have.toString() };
  const need = otherAmountMax.sub(have).add(new BN(1));
  const slip = Math.max(150, slippageBps);
  let swap = null;
  let mode = 'ExactOut';
  try {
    swap = await jupiterSwap({
      connection, owner,
      inputMint: payMintStr,
      outputMint: otherMintStr,
      amountRaw: need.toString(),
      slippageBps: slip,
      priorityMicro,
      swapMode: 'ExactOut',
    });
  } catch (exactOutErr) {
    const probes = payMintStr === WSOL_MINT
      ? [5_000_000, 10_000_000, 20_000_000, 35_000_000, 50_000_000]
      : [need.toString()];
    let bestIn = null;
    for (const amt of probes) {
      const qs = new URLSearchParams({
        inputMint: payMintStr,
        outputMint: otherMintStr,
        amount: String(amt),
        slippageBps: String(slip),
        swapMode: 'ExactIn',
      });
      let r = await fetch(`${JUP_QUOTE}?${qs}`, { headers: JUP_HEADERS, signal: AbortSignal.timeout(12_000) });
      const quote = await r.json();
      if (!r.ok || quote.error) continue;
      try {
        if (new BN(quote.outAmount).gte(need)) {
          bestIn = String(Math.ceil(Number(quote.inAmount) * 1.08));
          break;
        }
      } catch (_) { /* skip */ }
    }
    if (!bestIn) {
      throw new Error(`ExactOut failed (${exactOutErr.message}); ExactIn quote could not cover other leg`);
    }
    mode = 'ExactIn';
    swap = await jupiterSwap({
      connection, owner,
      inputMint: payMintStr,
      outputMint: otherMintStr,
      amountRaw: bestIn,
      slippageBps: slip,
      priorityMicro,
      swapMode: 'ExactIn',
    });
  }
  return {
    funded: true,
    signature: swap.signature,
    out_amount: swap.out_amount,
    in_amount: swap.in_amount,
    swap_mode: mode,
  };
}

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

  const literalPoolFull = Boolean(inp.literal_pool_full_range);
  const wideRange = Boolean(inp.wide_range || (inp.full_range && !literalPoolFull));
  if (wideRange) {
    const maxWide = Math.min(80, Math.max(10, Number(inp.wide_range_width_pct ?? 80)));
    const half = Math.min(40, maxWide / 2);
    const lowerPctBelow = Number(inp.tick_lower_pct_below ?? half);
    const upperPctAbove = Number(inp.tick_upper_pct_above ?? half);
    const loPct = Math.min(lowerPctBelow, maxWide / 2);
    const hiPct = Math.min(upperPctAbove, maxWide / 2);
    priceLower = spot * (1 - loPct / 100);
    priceUpper = spot * (1 + hiPct / 100);
    lo = priceToValidTick(new Decimal(priceLower), decA, decB, tickSpacing);
    hi = priceToValidTick(new Decimal(priceUpper), decA, decB, tickSpacing);
    if (lo === null || hi === null) {
      return { error: `wide_range tick conversion failed; lo=${lo} hi=${hi}` };
    }
    lo = Math.min(lo, hi);
    hi = Math.max(lo, hi);
    return {
      spot,
      priceLower,
      priceUpper,
      lo,
      hi,
      tickSpacing,
      decA,
      decB,
      tickCurrent,
      singleSide: null,
      wide_range: true,
      wide_range_width_pct: maxWide,
      full_range: false,
    };
  }
  if (literalPoolFull) {
    return {
      error: 'literal_pool_full_range is disabled (use wide_range, max 80% width)',
      hint: 'True min/max ticks cost ~0.15 SOL rent on small deposits',
    };
  }

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

/** Fit full-range open into one pay-token budget (swap slice + deposit slice). */
async function fitFullRangePayBudget({
  poolInfo, raydium, connection, owner, inp, lo, hi, tryBaseIn, fundSlippageBps,
}) {
  const mintAStr = String(poolInfo.mintA.address ?? poolInfo.mintA.address?.toString?.() ?? '');
  const mintBStr = String(poolInfo.mintB.address ?? poolInfo.mintB.address?.toString?.() ?? '');
  const payMintStr = tryBaseIn ? mintAStr : mintBStr;
  const otherMintStr = tryBaseIn ? mintBStr : mintAStr;
  const inputDecimals = tryBaseIn
    ? (poolInfo.mintA?.decimals ?? poolInfo.mintDecimalsA)
    : (poolInfo.mintB?.decimals ?? poolInfo.mintDecimalsB);
  const slippage = fundSlippageBps / 10000;
  const epochInfo = await raydium.connection.getEpochInfo();
  const budgetHuman = Number(inp.input_amount_human);
  if (!(budgetHuman > 0)) return null;

  await refreshOwnerTokenAccounts(raydium, connection, owner);
  const payBalRaw = tokenBalanceRaw(raydium, payMintStr);
  const budgetRaw = new BN(new Decimal(budgetHuman).mul(10 ** inputDecimals).toFixed(0));
  const capRaw = payBalRaw.muln(95).divn(100);
  const maxBudgetRaw = budgetRaw.gt(capRaw) ? capRaw : budgetRaw;
  if (maxBudgetRaw.lte(new BN(0))) return null;

  const splits = [0.52, 0.45, 0.38, 0.32, 0.28, 0.22];
  let otherLegFunding = null;

  for (const split of splits) {
    await refreshOwnerTokenAccounts(raydium, connection, owner);
    const swapRaw = maxBudgetRaw.muln(Math.round(split * 100)).divn(100);
    let depositRaw = maxBudgetRaw.sub(swapRaw);
    if (depositRaw.lte(new BN(0))) continue;

    if (swapRaw.gt(new BN(0))) {
      try {
        otherLegFunding = await jupiterSwap({
          connection, owner,
          inputMint: payMintStr,
          outputMint: otherMintStr,
          amountRaw: swapRaw.toString(),
          slippageBps: fundSlippageBps,
          priorityMicro: Number(inp.jupiter_priority_micro_lamports ?? inp.priority_fee_micro_lamports ?? 2_000),
          swapMode: 'ExactIn',
        });
        otherLegFunding = { funded: true, ...otherLegFunding, swap_mode: 'ExactIn' };
        await refreshOwnerTokenAccounts(raydium, connection, owner);
      } catch (_) {
        continue;
      }
    }

    const haveOther = tokenBalanceRaw(raydium, otherMintStr);
    for (let shrink = 0; shrink < 8; shrink++) {
      const probe = await PoolUtils.getLiquidityAmountOutFromAmountIn({
        poolInfo, inputA: tryBaseIn,
        tickLower: lo, tickUpper: hi,
        amount: depositRaw, slippage, add: true, epochInfo, amountHasFee: true,
      });
      const liqBN = probe?.liquidity;
      if (!liqBN || !liqBN.gt(new BN(0))) {
        depositRaw = depositRaw.muln(85).divn(100);
        if (depositRaw.lte(new BN(0))) break;
        continue;
      }
      let otherMax = tryBaseIn
        ? (probe.amountSlippageB?.amount ?? new BN(0))
        : (probe.amountSlippageA?.amount ?? new BN(0));
      if (otherMax.gt(haveOther)) otherMax = haveOther.muln(98).divn(100);
      if (otherMax.lte(new BN(0))) break;
      const amountHuman = Number(depositRaw.toString()) / 10 ** inputDecimals;
      return {
        probe,
        inputAmount: depositRaw,
        tryBaseIn,
        amountHuman,
        otherAmountMax: otherMax,
        otherLegFunding,
        pay_budget: {
          budget_human: budgetHuman,
          swap_fraction: split,
          deposit_human: amountHuman,
        },
      };
    }
  }
  return null;
}

/** Full-range using wallet ZINC + USDC toward a total USD budget (not pay-only). */
async function fitFullRangeWalletInventory({
  poolInfo, raydium, connection, owner, inp, lo, hi, fundSlippageBps,
}) {
  const mintAStr = String(poolInfo.mintA.address ?? poolInfo.mintA.address?.toString?.() ?? '');
  const mintBStr = String(poolInfo.mintB.address ?? poolInfo.mintB.address?.toString?.() ?? '');
  const slippage = fundSlippageBps / 10000;
  const epochInfo = await raydium.connection.getEpochInfo();
  const spot = Number(poolInfo.price);
  const budgetUsd = Number(inp.total_budget_usd ?? inp.input_amount_human);
  if (!(budgetUsd > 0) || !(spot > 0)) return null;

  await refreshOwnerTokenAccounts(raydium, connection, owner);
  let zincBal = tokenBalanceRaw(raydium, mintAStr);
  let usdcBal = tokenBalanceRaw(raydium, mintBStr);
  const decA = poolInfo.mintA?.decimals ?? 9;
  const decB = poolInfo.mintB?.decimals ?? 6;

  const targetZincUsd = budgetUsd * 0.48;
  const targetZincRaw = new BN(
    Math.max(1, Math.floor((targetZincUsd / spot) * 10 ** decA))
  );
  if (zincBal.lt(targetZincRaw) && usdcBal.gt(new BN(200_000))) {
    const deficit = targetZincRaw.sub(zincBal).muln(108).divn(100);
    try {
      await jupiterSwap({
        connection, owner,
        inputMint: mintBStr,
        outputMint: mintAStr,
        amountRaw: deficit.toString(),
        slippageBps: Math.max(fundSlippageBps, 1500),
        priorityMicro: Number(inp.jupiter_priority_micro_lamports ?? inp.priority_fee_micro_lamports ?? 2_000),
        swapMode: 'ExactOut',
      });
      await refreshOwnerTokenAccounts(raydium, connection, owner);
      zincBal = tokenBalanceRaw(raydium, mintAStr);
      usdcBal = tokenBalanceRaw(raydium, mintBStr);
    } catch (_) { /* fit loop may still swap */ }
  }

  const tryOrders = zincBal.lte(new BN(0))
    ? [
        { tryBaseIn: false, depositMint: mintBStr, otherMint: mintAStr, depDec: decB, otherBal: zincBal },
        { tryBaseIn: true, depositMint: mintAStr, otherMint: mintBStr, depDec: decA, otherBal: usdcBal },
      ]
    : [
        { tryBaseIn: true, depositMint: mintAStr, otherMint: mintBStr, depDec: decA, otherBal: usdcBal },
        { tryBaseIn: false, depositMint: mintBStr, otherMint: mintAStr, depDec: decB, otherBal: zincBal },
      ];

  for (const order of tryOrders) {
    const zincHuman = Number(zincBal.toString()) / 10 ** decA;
    const usdcHuman = Number(usdcBal.toString()) / 10 ** decB;
    let otherMax = order.otherBal.muln(98).divn(100);

    let depositRaw = (order.tryBaseIn ? zincBal : usdcBal).muln(92).divn(100);
    const totalUsd = zincHuman * spot + usdcHuman;
    if (totalUsd > budgetUsd * 1.05 && budgetUsd > 0) {
      const scale = Math.min(1, (budgetUsd * 0.98) / totalUsd);
      depositRaw = depositRaw.muln(Math.floor(scale * 100)).divn(100);
      otherMax = otherMax.muln(Math.floor(scale * 100)).divn(100);
    }
    if (depositRaw.lte(new BN(0)) && otherMax.lte(new BN(0))) continue;

    for (let shrink = 0; shrink < 10; shrink++) {
      const probe = await PoolUtils.getLiquidityAmountOutFromAmountIn({
        poolInfo, inputA: order.tryBaseIn,
        tickLower: lo, tickUpper: hi,
        amount: depositRaw.gt(new BN(0)) ? depositRaw : new BN(1),
        slippage, add: true, epochInfo, amountHasFee: true,
      });
      const liqBN = probe?.liquidity;
      if (!liqBN || !liqBN.gt(new BN(0))) {
        depositRaw = depositRaw.muln(88).divn(100);
        if (depositRaw.lte(new BN(0))) break;
        continue;
      }
      let needOther = order.tryBaseIn
        ? (probe.amountSlippageB?.amount ?? new BN(0))
        : (probe.amountSlippageA?.amount ?? new BN(0));
      let haveOtherNow = tokenBalanceRaw(raydium, order.otherMint);
      const payMintStr = order.tryBaseIn ? mintAStr : mintBStr;
      const payBalNow = order.tryBaseIn ? zincBal : usdcBal;
      if (needOther.gt(haveOtherNow)) {
        const deficit = needOther.sub(haveOtherNow).muln(112).divn(100);
        try {
          await jupiterSwap({
            connection, owner,
            inputMint: payMintStr,
            outputMint: order.otherMint,
            amountRaw: deficit.toString(),
            slippageBps: fundSlippageBps,
            priorityMicro: Number(inp.jupiter_priority_micro_lamports ?? inp.priority_fee_micro_lamports ?? 2_000),
            swapMode: 'ExactOut',
          });
          await refreshOwnerTokenAccounts(raydium, connection, owner);
          haveOtherNow = tokenBalanceRaw(raydium, order.otherMint);
        } catch (_) {
          const swapIn = payBalNow.muln(40).divn(100);
          if (swapIn.lte(new BN(0))) {
            depositRaw = depositRaw.muln(88).divn(100);
            continue;
          }
          try {
            await jupiterSwap({
              connection, owner,
              inputMint: payMintStr,
              outputMint: order.otherMint,
              amountRaw: swapIn.toString(),
              slippageBps: fundSlippageBps,
              priorityMicro: Number(inp.jupiter_priority_micro_lamports ?? inp.priority_fee_micro_lamports ?? 2_000),
              swapMode: 'ExactIn',
            });
            await refreshOwnerTokenAccounts(raydium, connection, owner);
            haveOtherNow = tokenBalanceRaw(raydium, order.otherMint);
          } catch (e2) {
            depositRaw = depositRaw.muln(88).divn(100);
            continue;
          }
        }
      }
      otherMax = haveOtherNow.muln(98).divn(100);
      if (needOther.gt(otherMax)) needOther = otherMax;
      if (needOther.lte(new BN(0))) {
        depositRaw = depositRaw.muln(88).divn(100);
        continue;
      }
      const amountHuman = Number(depositRaw.toString()) / 10 ** order.depDec;
      return {
        probe,
        inputAmount: depositRaw,
        tryBaseIn: order.tryBaseIn,
        amountHuman,
        otherAmountMax: needOther,
        otherLegFunding: { funded: false, reason: 'wallet_inventory' },
        wallet_inventory: {
          budget_usd: budgetUsd,
          zinc_human: zincHuman,
          usdc_human: usdcHuman,
          zinc_usd: zincHuman * spot,
          deposit_human: amountHuman,
          use_all_alt: true,
        },
      };
    }
  }
  return null;
}

/** When full-range + pay-only returns liq=0, fund alt leg using a tight band then retry min/max ticks. */
async function bootstrapFullRangePayOnly({
  poolInfo, raydium, connection, owner, inp,
  lo, hi, tryBaseIn, fundSlippageBps, bandTickSteps,
}) {
  const tickSpacing = poolInfo.config?.tickSpacing ?? poolInfo.tickSpacing ?? 1;
  const tickCurrent = Number(
    poolInfo.tickCurrent ?? poolInfo.tick ?? poolInfo.currentTick ?? 0
  );
  if (!Number.isFinite(tickCurrent)) return null;

  const bootSteps = Math.max(8, Number(bandTickSteps ?? 32));
  const mintAStr = String(poolInfo.mintA.address ?? poolInfo.mintA.address?.toString?.() ?? '');
  const mintBStr = String(poolInfo.mintB.address ?? poolInfo.mintB.address?.toString?.() ?? '');
  const payMintStr = tryBaseIn ? mintAStr : mintBStr;
  const otherMintStr = tryBaseIn ? mintBStr : mintAStr;
  // Pay-only bootstrap: use a one-sided band so the pay token alone yields non-zero liq.
  let bootLo;
  let bootHi;
  if (tryBaseIn) {
    bootLo = alignTickUp(tickCurrent + tickSpacing, tickSpacing);
    bootHi = bootLo + bootSteps * tickSpacing;
  } else {
    bootHi = alignTickDown(tickCurrent - tickSpacing, tickSpacing);
    bootLo = bootHi - bootSteps * tickSpacing;
  }
  const inputDecimals = tryBaseIn
    ? (poolInfo.mintA?.decimals ?? poolInfo.mintDecimalsA)
    : (poolInfo.mintB?.decimals ?? poolInfo.mintDecimalsB);
  const slippage = fundSlippageBps / 10000;
  const epochInfo = await raydium.connection.getEpochInfo();
  const spanFull = Math.max(tickSpacing, hi - lo);
  const spanBoot = Math.max(tickSpacing, bootHi - bootLo);
  const otherScale = Math.min(80, Math.max(2, Math.ceil(spanFull / spanBoot)));

  let amountHuman = Number(inp.input_amount_human);
  let otherLegFunding = null;

  for (let attempt = 0; attempt < 14; attempt++) {
    const inputAmount = new BN(
      new Decimal(amountHuman).mul(10 ** inputDecimals).toFixed(0)
    );
    if (inputAmount.lte(new BN(0))) break;

    const bootProbe = await PoolUtils.getLiquidityAmountOutFromAmountIn({
      poolInfo, inputA: tryBaseIn,
      tickLower: bootLo, tickUpper: bootHi,
      amount: inputAmount, slippage, add: true, epochInfo, amountHasFee: true,
    });
    const bootLiq = bootProbe?.liquidity;
    if (!bootLiq || typeof bootLiq.gt !== 'function' || !bootLiq.gt(new BN(0))) {
      amountHuman *= 0.72;
      continue;
    }

    let otherMax = tryBaseIn
      ? (bootProbe.amountSlippageB?.amount ?? new BN(0))
      : (bootProbe.amountSlippageA?.amount ?? new BN(0));
    if (otherMax.lte(new BN(0))) {
      amountHuman *= 0.72;
      continue;
    }
    otherMax = otherMax.muln(otherScale).muln(108).divn(100);

    await refreshOwnerTokenAccounts(raydium, connection, owner);
    const payBal = tokenBalanceRaw(raydium, payMintStr);
    const maxPayForSwap = payBal.muln(92).divn(100);
    if (maxPayForSwap.lte(new BN(0))) return null;

    try {
      otherLegFunding = await fundOtherLegIfNeeded({
        raydium, connection, owner,
        payMintStr, otherMintStr, otherAmountMax: otherMax,
        slippageBps: fundSlippageBps,
        priorityMicro: Number(inp.jupiter_priority_micro_lamports ?? inp.priority_fee_micro_lamports ?? 2_000),
      });
      if (otherLegFunding?.funded) {
        await refreshOwnerTokenAccounts(raydium, connection, owner);
      }
    } catch (_) {
      otherMax = otherMax.muln(70).divn(100);
      try {
        otherLegFunding = await fundOtherLegIfNeeded({
          raydium, connection, owner,
          payMintStr, otherMintStr, otherAmountMax: otherMax,
          slippageBps: fundSlippageBps,
          priorityMicro: Number(inp.jupiter_priority_micro_lamports ?? inp.priority_fee_micro_lamports ?? 2_000),
        });
        if (otherLegFunding?.funded) {
          await refreshOwnerTokenAccounts(raydium, connection, owner);
        }
      } catch (e2) {
        amountHuman *= 0.68;
        continue;
      }
    }

    const haveOther = tokenBalanceRaw(raydium, otherMintStr);
    const cappedOther = haveOther.muln(98).divn(100);
    if (cappedOther.lte(new BN(0))) {
      amountHuman *= 0.68;
      continue;
    }
    if (otherMax.gt(cappedOther)) otherMax = cappedOther;

    const fullProbe = await PoolUtils.getLiquidityAmountOutFromAmountIn({
      poolInfo, inputA: tryBaseIn,
      tickLower: lo, tickUpper: hi,
      amount: inputAmount, slippage, add: true, epochInfo, amountHasFee: true,
    });
    const fullLiq = fullProbe?.liquidity;
    if (fullLiq && typeof fullLiq.gt === 'function' && fullLiq.gt(new BN(0))) {
      return {
        probe: fullProbe,
        inputAmount,
        tryBaseIn,
        amountHuman,
        otherAmountMax: otherMax,
        otherLegFunding,
        bootstrap: { bootLo, bootHi, otherScale, bootLiq: bootLiq.toString() },
      };
    }

    // Funded alt but full-range probe still 0 — shrink pay deposit and retry.
    amountHuman *= 0.68;
  }
  return null;
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

  const wideRange = Boolean(inp.wide_range || (inp.full_range && !inp.literal_pool_full_range));
  const fundSlippageBps = Number(
    inp.slippage_bps ?? (wideRange ? 2500 : (inp.single_side ? 100 : 800))
  );

  let band = null;
  if (wideRange && (inp.wallet_inventory_wide_range || inp.wallet_inventory_full_range)) {
    const inputMintStr0 = String(inp.input_mint || '');
    const mintAStr0 = String(poolInfo.mintA.address ?? poolInfo.mintA.address?.toString?.() ?? '');
    const baseIn0 =
      inputMintStr0 === mintAStr0 ||
      inputMintStr0 === String(poolInfo.mintA.address?.toString?.() ?? '');
    const frBand = computeTickBand(poolInfo, { ...inp, band_tick_steps: widthStepsList[0] });
    if (!frBand.error) {
      const invFit = await fitFullRangeWalletInventory({
        poolInfo, raydium, connection, owner, inp,
        lo: frBand.lo, hi: frBand.hi, tryBaseIn: baseIn0, fundSlippageBps,
      });
      if (invFit) {
        band = frBand;
        band._liq = invFit.probe;
        band._finalBaseIn = invFit.tryBaseIn;
        band._inputAmount = invFit.inputAmount;
        band._slippage = fundSlippageBps / 10000;
        band._band_tick_steps = widthStepsList[0];
        band._fitted_human = invFit.amountHuman;
        band._otherAmountMax = invFit.otherAmountMax;
        band._otherLegFunding = invFit.otherLegFunding;
        band._wallet_inventory = invFit.wallet_inventory;
      }
    }
  }

  if (wideRange && payMintOnly && !band?._liq) {
    const inputMintStr0 = String(inp.input_mint || '');
    const mintAStr0 = String(poolInfo.mintA.address ?? poolInfo.mintA.address?.toString?.() ?? '');
    const baseIn0 =
      inputMintStr0 === mintAStr0 ||
      inputMintStr0 === String(poolInfo.mintA.address?.toString?.() ?? '');
    const frBand = computeTickBand(poolInfo, { ...inp, band_tick_steps: widthStepsList[0] });
    if (!frBand.error) {
      const budgetFit = await fitFullRangePayBudget({
        poolInfo, raydium, connection, owner, inp,
        lo: frBand.lo, hi: frBand.hi, tryBaseIn: baseIn0, fundSlippageBps,
      });
      if (budgetFit) {
        band = frBand;
        band._liq = budgetFit.probe;
        band._finalBaseIn = budgetFit.tryBaseIn;
        band._inputAmount = budgetFit.inputAmount;
        band._slippage = fundSlippageBps / 10000;
        band._band_tick_steps = widthStepsList[0];
        band._fitted_human = budgetFit.amountHuman;
        band._otherAmountMax = budgetFit.otherAmountMax;
        band._otherLegFunding = budgetFit.otherLegFunding;
        band._full_range_pay_budget = budgetFit.pay_budget;
      }
    }
  }

  for (const ws of widthStepsList) {
    if (band?._liq) break;
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
    const slippage = fundSlippageBps / 10000;
    const epochInfo = await raydium.connection.getEpochInfo();
    for (const tryBaseIn of tryBaseInOrder) {
      let amountHuman = Number(inp.input_amount_human);
      const payMintStr = tryBaseIn ? mintAStr : mintBStr;
      const otherMintStr = tryBaseIn ? mintBStr : mintAStr;
      let fitted = false;
      for (let shrink = 0; shrink < 16; shrink++) {
        const inputAmount = new BN(
          new Decimal(amountHuman).mul(10 ** inputDecimals).toFixed(0)
        );
        if (inputAmount.lte(new BN(0))) break;
        const probe = await PoolUtils.getLiquidityAmountOutFromAmountIn({
          poolInfo, inputA: tryBaseIn,
          tickLower: lo, tickUpper: hi,
          amount: inputAmount, slippage, add: true, epochInfo, amountHasFee: true,
        });
        const liqBN = probe?.liquidity;
        if (!liqBN || typeof liqBN.gt !== "function" || !liqBN.gt(new BN(0))) {
          amountHuman *= 0.6;
          continue;
        }
        let otherMax = tryBaseIn
          ? (probe.amountSlippageB?.amount ?? new BN(0))
          : (probe.amountSlippageA?.amount ?? new BN(0));
        if (wideRange && payMintOnly && otherMax.gt(new BN(0))) {
          await refreshOwnerTokenAccounts(raydium, connection, owner);
          try {
            await fundOtherLegIfNeeded({
              raydium, connection, owner,
              payMintStr, otherMintStr, otherMax,
              slippageBps: fundSlippageBps,
              priorityMicro: Number(inp.jupiter_priority_micro_lamports ?? inp.priority_fee_micro_lamports ?? 2_000),
            });
            await refreshOwnerTokenAccounts(raydium, connection, owner);
          } catch (_) {
            amountHuman *= 0.65;
            continue;
          }
          const haveOther = tokenBalanceRaw(raydium, otherMintStr);
          const need = otherMax.muln(95).divn(100);
          if (haveOther.lt(need)) {
            amountHuman *= 0.65;
            continue;
          }
          otherMax = haveOther.muln(98).divn(100);
        }
        band._liq = probe;
        band._finalBaseIn = tryBaseIn;
        band._inputAmount = inputAmount;
        band._slippage = slippage;
        band._band_tick_steps = ws;
        band._fitted_human = amountHuman;
        band._otherAmountMax = otherMax;
        fitted = true;
        break;
      }
      if (fitted) break;
    }
    if (band?._liq) break;

    if (wideRange && payMintOnly && !band?._liq) {
      const inputMintStr = String(inp.input_mint || '');
      const mintAStr = String(poolInfo.mintA.address ?? poolInfo.mintA.address?.toString?.() ?? '');
      const baseIn =
        inputMintStr === mintAStr ||
        inputMintStr === String(poolInfo.mintA.address?.toString?.());
      const boot = await bootstrapFullRangePayOnly({
        poolInfo, raydium, connection, owner, inp,
        lo, hi, tryBaseIn: baseIn, fundSlippageBps, bandTickSteps: ws,
      });
      if (boot) {
        band._liq = boot.probe;
        band._finalBaseIn = boot.tryBaseIn;
        band._inputAmount = boot.inputAmount;
        band._slippage = fundSlippageBps / 10000;
        band._band_tick_steps = ws;
        band._fitted_human = boot.amountHuman;
        band._otherAmountMax = boot.otherAmountMax;
        band._otherLegFunding = boot.otherLegFunding;
        band._full_range_bootstrap = boot.bootstrap;
        break;
      }
    }
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

  const mintAStr = String(poolInfo.mintA.address ?? poolInfo.mintA.address?.toString?.() ?? '');
  const mintBStr = String(poolInfo.mintB.address ?? poolInfo.mintB.address?.toString?.() ?? '');
  const straddling = !band.singleSide;

  // Map probe slippage to the non-base leg; SDK uses it as amountA when base=MintB.
  let otherAmountMax = band._otherAmountMax ?? (finalBaseIn
    ? (liq.amountSlippageB?.amount ?? new BN(0))
    : (liq.amountSlippageA?.amount ?? new BN(0)));
  if (payMintOnly && !straddling) {
    otherAmountMax = new BN(0);
  }

  let otherLegFunding = band._otherLegFunding ?? null;
  if (straddling && otherAmountMax.gt(new BN(0)) && !band._otherAmountMax) {
    const payMintStr = finalBaseIn ? mintAStr : mintBStr;
    const otherMintStr = finalBaseIn ? mintBStr : mintAStr;
    try {
      otherLegFunding = await fundOtherLegIfNeeded({
        raydium, connection, owner,
        payMintStr, otherMintStr, otherAmountMax,
        slippageBps: fundSlippageBps,
        priorityMicro: Number(inp.jupiter_priority_micro_lamports ?? inp.priority_fee_micro_lamports ?? 2_000),
      });
      if (otherLegFunding?.funded) {
        await refreshOwnerTokenAccounts(raydium, connection, owner);
      }
    } catch (e) {
      return finish({
        ok: false,
        error: `straddle other-leg funding failed: ${e.message}`,
        other_amount_max: otherAmountMax.toString(),
        pay_mint: payMintStr,
        other_mint: otherMintStr,
      });
    }
    const haveOther = tokenBalanceRaw(raydium, otherMintStr);
    if (haveOther.lt(otherAmountMax)) {
      if (haveOther.lte(new BN(0))) {
        return finish({
          ok: false,
          error: wideRange
            ? 'wide_range: insufficient other leg after funding (try larger USDC deposit, e.g. $3+)'
            : 'insufficient other leg balance after funding',
          other_amount_max: otherAmountMax.toString(),
          other_leg_have: haveOther.toString(),
        });
      }
      otherAmountMax = haveOther;
    }
    if (otherAmountMax.gt(new BN(1000))) {
      otherAmountMax = otherAmountMax.muln(98).divn(100);
    }
  }

  await refreshOwnerTokenAccounts(raydium, connection, owner);
  const haveA = tokenBalanceRaw(raydium, mintAStr);
  const haveB = tokenBalanceRaw(raydium, mintBStr);
  const inputMintStrCap = String(inp.input_mint || '');
  const payWithNativeSol = inputMintStrCap === WSOL_MINT;
  let baseAmount = inputAmount;
  if (payWithNativeSol) {
    const lamportsNow = await connection.getBalance(owner.publicKey);
    const reserveLamports = Number(inp.min_open_lamports ?? 25_000_000);
    const spendable = Math.max(0, lamportsNow - reserveLamports);
    const capNative = new BN(String(spendable));
    if (baseAmount.gt(capNative)) baseAmount = capNative;
  } else if (finalBaseIn) {
    const capA = haveA.muln(94).divn(100);
    const capB = haveB.muln(94).divn(100);
    if (baseAmount.gt(capA)) baseAmount = capA;
    if (otherAmountMax.gt(capB)) otherAmountMax = capB;
  } else {
    const capB = haveB.muln(94).divn(100);
    const capA = haveA.muln(94).divn(100);
    if (baseAmount.gt(capB)) baseAmount = capB;
    if (otherAmountMax.gt(capA)) otherAmountMax = capA;
  }
  if (baseAmount.lte(new BN(0))) {
    return finish({ ok: false, error: 'deposit amount zero after wallet cap' });
  }
  if (straddling && otherAmountMax.lte(new BN(0))) {
    return finish({
      ok: false,
      error: 'wide_range straddle requires both legs; fund alt leg and retry',
      base_amount: baseAmount.toString(),
      other_amount_max: otherAmountMax.toString(),
    });
  }
  if (otherAmountMax.gt(new BN(0))) {
    otherAmountMax = otherAmountMax.muln(105).divn(100);
  }

  const inputMintStr = String(inp.input_mint || '');
  const useSolBalance = inputMintStr === WSOL_MINT;

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
    const lamportsNow = await connection.getBalance(owner.publicKey);
    const minLamports = Number(
      inp.min_open_lamports ?? 25_000_000
    );
    if (lamportsNow < minLamports) {
      return finish({
        ok: false,
        error: `insufficient SOL for CLMM open rent (have ${lamportsNow}, need ${minLamports})`,
        lamports: lamportsNow,
        hint: 'Keep ~0.03+ SOL free; Token-2022 NFT avoids Metaplex metadata rent',
      });
    }

    ({ execute, extInfo } = await raydium.clmm.openPositionFromBase({
      poolInfo, poolKeys,
      tickLower:      lo,
      tickUpper:      hi,
      base:           finalBaseIn ? 'MintA' : 'MintB',
      baseAmount,
      otherAmountMax,
      associatedOnly: true,
      withMetadata:   'no-create',
      nft2022:        Boolean(inp.nft2022),
      ownerInfo: {
        useSOLBalance: useSolBalance,
      },
      txVersion:      TxVersion.V0,
      computeBudgetConfig: {
        units:        Number(inp.compute_units ?? (wideRange ? 350_000 : 200_000)),
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
    wide_range:            Boolean(band?.wide_range ?? wideRange),
    wide_range_width_pct:  band?.wide_range_width_pct ?? inp.wide_range_width_pct ?? null,
    full_range:            false,
    fitted_deposit_human:  band._fitted_human ?? null,
    single_side_mode:      inp.single_side ?? null,
    pay_mint_only:         payMintOnly,
    pay_symbol:            inp.pay_symbol ?? null,
    input_amount_lamports: inputAmount.toString(),
    other_amount_max:      otherAmountMax.toString(),
    other_leg_funding:     otherLegFunding,
    pool_id:               inp.pool_id,
    owner:                 owner.publicKey.toBase58(),
    final_baseIn:          finalBaseIn,
  });
}

main().catch(failFromError);
