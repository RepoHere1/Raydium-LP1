/**
 * quote_sell.mjs — anti-slippage probe.
 *
 * Asks Jupiter for a sell quote at the FULL position size you plan to
 * deploy. Returns price impact + expected out so the Python side can decide
 * whether to skip the entry (your "lying-thieving sell tax" defense).
 *
 * v0.2 — added:
 *   - dual endpoint failover (lite-api → quote-api)
 *   - browser-like User-Agent (Cloudflare WAF defense)
 *   - explicit error.cause surfacing (Node fetch hides the real reason)
 *   - AbortSignal.timeout so we don't hang forever
 *
 * stdin:
 *   {
 *     "input_mint":   "<mint>",
 *     "output_mint":  "<mint>",
 *     "amount":       "1000000000",
 *     "slippage_bps": 100,
 *     "max_impact_pct": 5.0,
 *     "timeout_ms":   8000
 *   }
 *
 * stdout on success:
 *   {
 *     "ok": true,
 *     "in_amount":         "1000000000",
 *     "out_amount":        "987654321",
 *     "price_impact_pct":  0.012,
 *     "routes_count":      3,
 *     "verdict":           "ok" | "high_impact" | "no_route",
 *     "endpoint_used":     "https://lite-api.jup.ag/..."
 *   }
 */

import { readStdinJson, finish, failFromError } from './_shared.mjs';

const ENDPOINTS = [
  "https://lite-api.jup.ag/swap/v1/quote",     // newer, higher uptime
  "https://quote-api.jup.ag/v6/quote",         // legacy fallback
];

const BROWSER_HEADERS = {
  "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
  "Accept":          "application/json, text/plain, */*",
  "Accept-Language": "en-US,en;q=0.9",
  "Origin":          "https://jup.ag",
  "Referer":         "https://jup.ag/",
};

async function fetchOne(base, qs, timeout_ms) {
  const url = `${base}?${qs}`;
  let resp;
  try {
    resp = await fetch(url, {
      headers: BROWSER_HEADERS,
      signal:  AbortSignal.timeout(timeout_ms),
    });
  } catch (e) {
    // Node fetch hides underlying cause — surface it
    const cause = e?.cause?.code || e?.cause?.message || e?.code || "";
    throw new Error(`network error (${e.message}${cause ? `, cause=${cause}` : ""})`);
  }
  let body;
  try {
    body = await resp.json();
  } catch (e) {
    throw new Error(`non-JSON response (HTTP ${resp.status}): ${e.message}`);
  }
  if (!resp.ok || body.error) {
    throw new Error(`${base} HTTP ${resp.status}: ${body.error || JSON.stringify(body).substring(0,200)}`);
  }
  return { body, url };
}

async function main() {
  const inp = await readStdinJson();
  for (const k of ['input_mint', 'output_mint', 'amount']) {
    if (!inp[k]) return finish({ ok: false, error: `${k} required` });
  }
  const slippageBps   = Number(inp.slippage_bps ?? 100);
  const maxImpactPct  = Number(inp.max_impact_pct ?? 5);
  const timeout_ms    = Number(inp.timeout_ms ?? 8000);

  const qs = new URLSearchParams({
    inputMint:           inp.input_mint,
    outputMint:          inp.output_mint,
    amount:              String(inp.amount),
    slippageBps:         String(slippageBps),
    swapMode:            'ExactIn',
    onlyDirectRoutes:    'false',
    asLegacyTransaction: 'false',
  });

  // Try each endpoint until one works; collect errors for diagnostics
  let result = null;
  const errors = [];
  for (const base of ENDPOINTS) {
    try {
      result = await fetchOne(base, qs, timeout_ms);
      break;
    } catch (e) {
      errors.push(`${base}: ${e.message}`);
    }
  }
  if (!result) {
    return finish({
      ok:      false,
      error:   `all Jupiter endpoints failed`,
      tried:   errors,
      verdict: 'no_route',
    });
  }

  const { body, url } = result;
  const outAmt  = Number(body.outAmount);
  const impact  = Number(body.priceImpactPct || 0);
  const verdict =
    impact * 100 > maxImpactPct ? 'high_impact' :
    outAmt === 0                 ? 'no_route'    :
                                   'ok';

  return finish({
    ok:                       true,
    in_amount:                body.inAmount,
    out_amount:               body.outAmount,
    other_amount_threshold:   body.otherAmountThreshold,
    price_impact_pct:         impact,
    routes_count:             (body.routePlan || []).length,
    max_impact_pct_threshold: maxImpactPct,
    verdict,
    endpoint_used:            url.split('?')[0],
  });
}

main().catch(failFromError);
