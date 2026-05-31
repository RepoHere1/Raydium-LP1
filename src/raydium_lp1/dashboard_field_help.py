"""Field and section copy for the local settings dashboard.

Each field maps to ``(help, live_hint)``. ``live_hint`` is rendered on the page as a
visible **Suggested:** line and summarized in the floating ``#dash-tip`` panel on
hover (native ``title`` is not used for long copy because embedded browsers often
omit it).

Section titles map to ``(section_help, section_rec)`` for visible blurbs plus
hover on the section heading.
"""

from __future__ import annotations

from typing import Any

FIELD_HELP: dict[str, tuple[str, str]] = {
    "min_apr": (
        "Minimum APR (percent) after TVL and 24h volume gates. The scanner evaluates "
        "liquidity and volume before APR so dust pools do not clutter the APR bucket.",
        "Majors on Raydium often print roughly 25% to 45% APR; triple-digit rows are "
        "usually smaller or newer pools. If your funnel is empty, lower this in steps "
        "of 25 after you have raised min TVL.",
    ),
    "min_liquidity_usd": (
        "Minimum pool TVL (USD) for economic interest — filters thin pools you would not "
        "want to LP for yield. Not the same as hard_exit_min_tvl_usd (exit depth).",
        "Try 25k to 150k for exploratory scans, 250k to 2M for majors. Pair with min volume.",
    ),
    "min_volume_24h_usd": (
        "Minimum Raydium-reported 24h notional volume in USD. Cuts stale pools that "
        "show a balance but no trading.",
        "Absolute floors like 5k to 50k help; also set Min Vol/TVL under Momentum so "
        "relative activity must look healthy.",
    ),
    "hard_exit_min_tvl_usd": (
        "hard_exit_min_tvl_usd: cannot-exit depth floor (USD) — reject pools too shallow "
        "to sell back to SOL at acceptable impact. Use min_liquidity_usd for yield interest; "
        "use this for hard exit safety only.",
        "Common range 500 to 5000 USD; raise if Jupiter sell quotes fail or impact spikes.",
    ),
    "max_position_usd": (
        "Cap on notional size the planner uses per position when reasoning about impact "
        "and capacity (see wallet section for SOL sizing).",
        "Keep well below typical TVL of pairs you target so your clip is a small slice "
        "of the book.",
    ),
    "apr_field": (
        "Which Raydium APR window feeds ``apr`` in the scanner (for example apr24h, "
        "apr7d). Must match the API field name.",
        "apr24h reacts fastest; apr7d smooths spikes for calmer lists.",
    ),
    "pool_sort_field": (
        "Raydium list sort column when fetching pages. Official api-v3 values include "
        "liquidity, volume24h, fee24h, apr24h, apr7d, apr30d, default (24h volume), and more.",
        "Chasing high headline APR: use apr24h + desc (or apr7d for smoother weekly yield). "
        "If you sort by liquidity or volume but keep a high min_apr, the first pages are often "
        "the wrong shape and you will reject most rows for APR alone.",
    ),
    "sort_type": (
        "Raydium API sort direction: desc = highest first, asc = lowest first.",
        "Almost always desc for scans.",
    ),
    "pages": (
        "How many Raydium list pages to pull each scan. Each page costs HTTP time.",
        "Start with 2 to 5; raise only after filters are tight so you are not paging "
        "through endless dust.",
    ),
    "page_size": (
        "Pools per Raydium page (API pageSize).",
        "100 is typical; lower if you want smaller bursts.",
    ),
    "pool_type": (
        "Raydium poolType query parameter (for example all, Standard, or your network "
        "default).",
        "Match what you trade; Standard is common for classic AMM style lists.",
    ),
    "page_delay_seconds": (
        "Pause between Raydium page requests to reduce rate limiting.",
        "0.2 to 0.8 s is a polite default when paging deeply.",
    ),
    "http_timeout_seconds": (
        "Per-request HTTP timeout for Raydium and route probes.",
        "15 to 30 s is reasonable on congested networks.",
    ),
    "max_pool_age_hours": (
        "Reject pools older than this many hours when open time is known. Zero disables "
        "the max-age filter.",
        "168 h (one week) matches many sweet-spot windows; shorten if you only want "
        "fresh launches.",
    ),
    "min_pool_age_hours": (
        "Reject pools younger than this to skip the first minutes of launch volatility.",
        "6 to 24 h is a common anti-rug delay; 0 disables.",
    ),
    "min_burn_percent": (
        "Minimum LP burn percent Raydium reports. Zero disables.",
        "100% burn is often required for strict meme filters; lower if you include "
        "partial-burn pools.",
    ),
    "verify_pool_on_chain": (
        "When enabled, extra Solana RPC checks validate pool accounts before trusting "
        "list data.",
        "Slower but safer for live capital; keep on for production-style runs.",
    ),
    "verify_pool_raydium_api": (
        "Cross-check pool metadata against Raydium endpoints when enabled.",
        "Useful when list responses are cached or odd.",
    ),
    "require_verified_raydium_pool": (
        "Fail pools that do not pass Raydium verification flags when the API exposes "
        "them.",
        "Turn on to drop unverified community pairs.",
    ),
    "require_pool_id": (
        "Reject rows with empty pool id so downstream routing always has an address.",
        "Leave enabled for any route or swap path.",
    ),
    "momentum_enabled": (
        "Compute momentum tiers and scores for ranking and optional gating.",
        "Enable when you want time-series style ranking instead of APR-only sorts.",
    ),
    "min_momentum_score": (
        "Floor on the numeric momentum score when momentum is enabled.",
        "Raise gradually once the funnel passes enough pools; start near your "
        "historical median from dry runs.",
    ),
    "require_momentum_score": (
        "If enabled, pools that fail the momentum score floor are rejected even when "
        "other gates pass.",
        "Use when you want momentum as a hard veto, not just a sort key.",
    ),
    "momentum_hold_hours": (
        "Lookback window in hours for momentum-style signals inside the scanner.",
        "10 h matches short swing probes; 24 to 72 h for slower tape.",
    ),
    "momentum_top_hot": (
        "How many top momentum names to keep in the hot shortlist for reporting.",
        "20 to 40 is a readable dashboard band; raise if you study more names per loop.",
    ),
    "momentum_hot_min_combined_score": (
        "Minimum combined momentum score for tier HOT (green rows + MoM LIVE pick). "
        "Default 72; lower to 60–65 for more HOT labels in choppy markets.",
        "Try 65 when you want more HOTs; 72–80 when you want only the strongest fee-rush names.",
    ),
    "momentum_hot_min_apr": (
        "Minimum APR % required for tier HOT (in addition to combined score and vol/TVL). "
        "Default 200; align with min_apr or lower slightly to tag more names HOT.",
        "200 matches legacy behavior; 150–180 if min_apr is already 200+.",
    ),
    "sort_candidates_by_momentum": (
        "Order dry-run candidates by momentum instead of only APR/TVL.",
        "Turn on when APR sorts lie (fee-sorted pages with inflated tiny pools).",
    ),
    "lp_selection_mode": (
        "LIVE open target: apr = highest APR in shortlist; momentum = highest combined score among tier HOT only.",
        "Use dashboard APR pick / MoM HOT buttons — re-scan after switching.",
    ),
    "momentum_min_volume_tvl_ratio": (
        "Minimum 24h volume divided by TVL for momentum sweet spot logic.",
        "0.3 to 1.0 catches real turnover; your 0.5 is a solid active-pool default.",
    ),
    "momentum_sweet_min_pool_age_hours": (
        "Lower bound of the momentum sweet-spot age band in hours.",
        "6 h skips brand-new listings; tighten if you want only seasoned pools.",
    ),
    "momentum_sweet_max_pool_age_hours": (
        "Upper bound of the momentum sweet-spot age band in hours.",
        "168 h (one week) matches typical meme attention cycles; shorten for launch "
        "only plays.",
    ),
    "momentum_min_tvl_usd": (
        "Minimum TVL for pools considered in momentum scoring paths.",
        "250 USD is very low and will still admit micro pools; try 5k to 50k if you "
        "want momentum only on real books.",
    ),
    "momentum_detective_enabled": (
        "Extra momentum diagnostics and probes (more RPC / API chatter when on).",
        "Enable while tuning; disable in tight loops once stable.",
    ),
    "momentum_probe_market_lists": (
        "When on, momentum logic may probe supplemental market lists (more calls).",
        "Use during investigation; off for lean production scans.",
    ),
    "require_sell_route": (
        "Require a working sell-side route (for example Jupiter) before accepting a "
        "pool.",
        "Keep on whenever you intend to exit back to a quote asset.",
    ),
    "use_robust_routing": (
        "Use the more defensive routing path with extra checks and fallbacks where "
        "implemented.",
        "Enable when quotes are flaky or you see occasional route failures.",
    ),
    "max_route_price_impact_pct": (
        "Maximum acceptable Jupiter (or configured sources) price impact percent on "
        "probed exit size.",
        "1% to 3% is tight; 5% is common for smaller clips on illiquid legs; above 5% "
        "is usually stress territory.",
    ),
    "route_sources_json": (
        "JSON array of route providers to query, for example [\"jupiter\",\"raydium\"].",
        "Start with jupiter plus raydium; adjust only if you know your stack supports "
        "more sources.",
    ),
    "write_rejections": (
        "Append each rejection to a CSV for offline sorting and histogram review.",
        "Enable while dialling gates; disable if disk noise matters.",
    ),
    "rejections_csv_path": (
        "Filesystem path for the rejections CSV when write_rejections is on.",
        "Use a path under reports/ so git ignores stay predictable.",
    ),
    "fee_guard_enabled": (
        "Master switch: block micro CLMM deposits, cap priority fees, limit retries and session spend.",
        "Leave on. This is what stops 25¢ opens from burning ~0.04 SOL rent per attempt.",
    ),
    "min_clmm_deposit_sol": (
        "Minimum SOL deposited in a CLMM open; below this fee guard rejects the tx.",
        "0.008 SOL minimum; 0.02–0.05 SOL is safer once rent is included.",
    ),
    "max_priority_fee_micro_lamports": (
        "Hard cap on Solana priority fee (micro-lamports per compute unit). Was 50_000 by default — now capped low.",
        "2000 is conservative; raise only if txs never land.",
    ),
    "max_open_retries": (
        "How many open attempts per dashboard/CLI click. Each attempt can cost rent + fees.",
        "Keep at 1.",
    ),
    "max_session_spend_sol": (
        "Estimated SOL budget per session (reports/fee_session_ledger.json); blocks further spends when exceeded.",
        "0.12 SOL default; raise only for deliberate testing.",
    ),
    "max_fee_pct_of_deposit": (
        "Reject opens when estimated rent+fees exceed this percent of deposit size.",
        "35% default; micro deposits fail this check on purpose.",
    ),
    "max_rent_escrow_pct_of_deposit": (
        "Hard cap on estimated non-recoverable tick-array rent as % of LP deposit (pre-trade). "
        "Blocks literal full-range style traps before broadcast.",
        "10% default — never let sunk escrow exceed one-tenth of deposit. Raise only for large positions.",
    ),
    "clmm_open_rent_sol": (
        "Estimated one-time rent for CLMM NFT + tick accounts (the main fee trap on small opens).",
        "0.042 SOL is a realistic mainnet estimate.",
    ),
    "position_size_sol": (
        "SOL notional budget per position used for capacity and sizing hints.",
        "Set from wallet balance minus reserve; dry runs can use small fractions.",
    ),
    "reserve_sol": (
        "SOL kept unallocated for fees and buffer.",
        "0.05 to 0.3 SOL is typical depending on priority fees and position count.",
    ),
    "emergency_close_enabled": (
        "Allow emergency-close logic in the runner when conditions trip.",
        "Off until you trust automation; on with tight slippage caps in production.",
    ),
    "emergency_max_slippage_pct": (
        "Maximum slippage fraction (0 to 1) emergency exits may use.",
        "0.02 to 0.05 for liquid pairs; higher only if you accept bad fills.",
    ),
    "emergency_base_symbol": (
        "Quote symbol emergency exits aim for (for example SOL or USDC).",
        "Match your primary inventory token.",
    ),
    "emergency_alerts_path": (
        "Optional path for alert text when emergency paths fire.",
        "Point to a file your notifier watches, or leave default if unused.",
    ),
    "track_liquidity_health": (
        "Record TVL snapshots over time for drift detection.",
        "Enable when monitoring for rug-style liquidity pulls.",
    ),
    "liquidity_history_path": (
        "JSONL or path used for liquidity history when tracking is on.",
        "Keep under reports/ for easy rotation.",
    ),
    "lp_planning_enabled": (
        "Turn on concentrated LP band planning in dry-run outputs.",
        "Enable after core scanning is stable.",
    ),
    "lp_active_strategy": (
        "centered_tight_range: narrow band on spot. asymmetric_single_asset: one-sided band (bullish above / bearish below). "
        "volatility_atr_width: width from day min/max swing. trailing_dynamic_skew: band skewed with momentum. "
        "standard_full_range: wide centered band (max 80% width, not literal min/max ticks). auto_volatility_pick: chooses tight vs ATR from churn. "
        "LIVE opens use this setting on the next CLMM deposit (see LP style column on dashboard).",
        "Change before each experiment; dashboard groups LIVE fills by lp_style_label for comparison.",
    ),
    "lp_fee_bps": (
        "Pool fee tier in basis points for paper fee estimates on the dashboard (25 = 0.25%).",
        "Match your target Raydium pool tier when known.",
    ),
    "demo_paper_sol": (
        "Paper SOL balance shown on the DRY_RUN wallet panel only.",
        "10 SOL is a sensible default for slot math demos.",
    ),
    "lp_range_mode": (
        "How range width is chosen (project-specific string; see docs).",
        "Use project defaults until you customize strategy code.",
    ),
    "lp_default_range_width_pct": (
        "Default symmetric band width percent around spot when planning LP.",
        "10% to 30% for moderate vol pairs; wider for meme names.",
    ),
    "lp_range_width_candidates_json": (
        "JSON array of band widths to score in parallel during planning.",
        "[12,20,30,50] is a reasonable sweep grid.",
    ),
    "lp_skew_use_momentum": (
        "Shift LP bands using momentum direction when enabled.",
        "Pairs with momentum enabled; off for symmetric testing.",
    ),
    "lp_open_pay_token_only": (
        "When on (default), every LIVE CLMM open deposits only an allowed quote leg (SOL, USDC, or USDT) "
        "and places the band on that side so you never fund the memecoin leg unless you turn this off.",
        "Leave on for quote-only inventory; pools without a quote leg are skipped for LIVE opens.",
    ),
    "lp_pay_prefer_symbol": (
        "Which pay token to use when a pool has multiple quotes (rare). Empty uses emergency_base_symbol (usually SOL).",
        "Set USDC if you size positions in stablecoin rather than SOL.",
    ),
    "lp_pay_funding_enabled": (
        "When on (default), LIVE opens that pay in USDC/USDT auto-swap SOL via Jupiter if the wallet "
        "stable balance is below deposit size (+ buffer). SOL pay legs skip swapping.",
        "Turn off only if you pre-fund stables manually. Applies to all LIVE opens including manual trades from ANOMALIES.",
    ),
    "lp_close_sweep_trash_to_sol": (
        "When on (default), after every CLMM close, non-stable tokens received (memecoin / trash legs) "
        "are swapped to SOL via Jupiter immediately.",
        "USDC/USDT/USD1 are kept; unsellable trash stops after 2 attempts to limit fee waste.",
    ),
    "lp_close_trash_swap_attempts": (
        "How many Jupiter swap attempts per trash mint after a close (default 2). "
        "After that the token is marked abandoned_unsellable and no further swap txs are sent.",
    ),
    "lp_pay_funding_buffer_pct": (
        "Extra fraction added on top of the LP deposit when checking stable balance (default 0.03 = 3%).",
        "Covers rounding and tiny slippage so the CLMM open does not fail for being $0.01 short.",
    ),
    "lp_pay_funding_sol_price_usd": (
        "Fallback SOL/USD for sizing the funding swap when Jupiter quote probes are unavailable. 0 = use 180.",
        "CLI --sol-price also feeds live opens when set.",
    ),
    "lp_full_range_parallel": (
        "Also simulate a full-range style leg beside concentrated bands.",
        "Useful for comparing fee capture vs passive full range.",
    ),
    "lp_full_range_budget_fraction": (
        "Fraction of LP budget allocated to the parallel full-range leg.",
        "Small fractions like 0.1 to 0.3 keep focus on the main band.",
    ),
    "lp_main_budget_fraction": (
        "Fraction allocated to the primary concentrated strategy.",
        "Should complement full_range_budget_fraction if both are used.",
    ),
    "lp_max_positions_per_mint": (
        "Cap concurrent planned positions per base mint.",
        "1 to 3 prevents over-concentration in one ticker.",
    ),
    "manual_live_min_pool_liquidity_usd": (
        "When you open a specific pool by id (open_live_lp_cli.py or dashboard POST with pool_id), "
        "pool TVL must be at least this USD or the open stops immediately and an alert is written.",
        "Default $1000 blocks micro pools; scanner min_liquidity_usd can stay lower for shortlists.",
    ),
    "manual_live_require_sell_route": (
        "On manual pool-id opens, the non-pay (alt) token must have a Jupiter/Raydium sell route "
        "to allowed quotes within the impact cap.",
        "Leave on so opens like SOL/IDLE fail before signing when the alt leg cannot exit.",
    ),
    "manual_live_max_route_price_impact_pct": (
        "Max price impact % for manual-open sell-route probes. 0 uses max_route_price_impact_pct.",
        "Tighter than global (e.g. 3) if you only manual-open majors.",
    ),
    "manual_live_alerts_path": (
        "JSON log of blocked manual LIVE attempts (TVL too low, no sell route, etc.).",
        "Check after a failed CLI open; path is relative to repo root unless absolute.",
    ),
    "super_brainiac_min_liquidity_usd": (
        "Minimum pool TVL for the SUPER-BRAINIAC universe scan (default $5,000).",
        "Higher = safer depth; lower = more candidates but thinner books.",
    ),
    "super_brainiac_deposit_usd": (
        "USD size for experiment LIVE opens (default $3). Uses pay-token-only + fee guard.",
        "Does not bypass manual-live or session fee caps.",
    ),
    "super_brainiac_target_apr_pct": (
        "Label threshold for «jackpot» APR in scoring UI (default 999.99). Ranking uses expected fee $.",
        "Almost no pool truly sustains 1000% APR; treat as experiment dial not a promise.",
    ),
    "super_brainiac_auto_open_live": (
        "When true, each brainiac cycle can open the top pick without a dashboard prompt.",
        "Leave false until you trust scan + scoring; use Run once with LIVE confirm first.",
    ),
    "super_brainiac_scan_pages": (
        "Raydium list pages per detective scan (each page = HTTP round trip).",
        "8 pages × 100 pools is a good start; raise only if filters are tight.",
    ),
    "super_brainiac_prefer_fee_pct_min": (
        "Fee-tier boost band lower bound (pool feeRate as %, e.g. 1 = 1%).",
        "Pools inside min–max get a score multiplier; outside can still win on volume.",
    ),
    "super_brainiac_prefer_fee_pct_max": (
        "Fee-tier boost band upper bound (default 4%).",
        "Pairs well with memecoin CLMM tiers at 1–4%.",
    ),
    "super_brainiac_min_confidence": (
        "Minimum in-range × width confidence before LIVE open (0–1).",
        "Raise to avoid opens when day-range does not overlap your band.",
    ),
    "super_brainiac_continuous_interval_sec": (
        "Seconds between scans in CLI loop mode.",
        "Dashboard uses manual Run scan unless you run scripts/super_brainiac_possibilities.py loop.",
    ),
    "super_brainiac_report_path": (
        "Latest scan leaderboard + top pick JSON for dashboard panel.",
        "reports/super_brainiac_latest.json by default.",
    ),
    "super_brainiac_require_pay_alt_pair_only": (
        "Detective-only: require exactly one pay leg (SOL/USDC/USDT) and one alt/memecoin. "
        "Blocks SOL/USDC, SOL/USDT, USDC/USDT style pools.",
        "Leave on for PAY + newish token experiments.",
    ),
    "strategy": (
        "Which strategy module the runner loads.",
        "Pick the strategy you actually run in production.",
    ),
    "network": (
        "Logical network name (for example mainnet-beta).",
        "Must match RPCs and Raydium deployment you target.",
    ),
    "risk_profile": (
        "Opaque tag carried into reports for your own classification.",
        "Use conservative or aggressive labels for downstream analytics.",
    ),
    "dry_run": (
        "When true, do not broadcast transactions; log and plan only.",
        "Always on until execution paths are verified.",
    ),
    "raydium_api_base": (
        "Base URL for Raydium HTTP APIs used by the scanner.",
        "Leave at the official host unless you proxy intentionally.",
    ),
    "solana_rpc_urls_lines": (
        "One Solana JSON-RPC URL per line; first healthy URL wins per call pattern.",
        "Provide two or more independent providers for resilience.",
    ),
    "allowed_quote_symbols_csv": (
        "Comma-separated quote symbols a pool must include (for example SOL,USDC).",
        "SOL,USDC is a common pair for routing flexibility.",
    ),
    "blocked_token_symbols_csv": (
        "Comma-separated symbols always rejected when present on a pool.",
        "Add tickers you never want to inventory.",
    ),
    "blocked_mints_lines": (
        "One mint address per line that disqualifies any pool touching it.",
        "Use for known scam mints or personal never-list tokens.",
    ),
    "dashboard_path": (
        "Where the scanner writes latest.json consumed by this dashboard.",
        "Default reports/dashboard.json is fine for local loops.",
    ),
    "scan_loop": (
        "Hint in settings; prefer the CLI ``--loop`` flag for real looping.",
        "Document-only unless your launcher reads it.",
    ),
    "scan_loop_interval_seconds": (
        "Suggested seconds between scans when looping externally.",
        "60 to 300 s balances freshness vs API load.",
    ),
    "spawn_verdict_watcher": (
        "Whether auxiliary verdict watcher subprocess should start from your stack "
        "launcher.",
        "Match whatever your process supervisor expects.",
    ),
}


SECTION_BLURB: dict[str, tuple[str, str]] = {
    "Liquidity gates": (
        "These gates shrink Raydium’s long tail before you spend RPC on routing.",
        "Raise min TVL and min 24h volume before you lower min APR. Use hard TVL for "
        "cannot-exit depths; use min TVL for economic interest.",
    ),
    "Raydium paging": (
        "Controls how list pages are fetched (sort column, direction, depth).",
        "Keep pages small (2–5) until filters are tight. fee sort shows many illiquid "
        "rows; pair with strong TVL/volume floors.",
    ),
    "Age, burn, verification": (
        "Time-in-market, LP burn, and optional Raydium/RPC cross-checks.",
        "min pool age 6–24h reduces launch noise; max age 0 = off. Full burn is a "
        "stricter meme filter. On-chain verify costs latency but catches bad rows.",
    ),
    "Momentum": (
        "Ranks and optionally vetoes pools using turnover, age sweet spot, and score.",
        "Turn on require momentum pass once min score is calibrated. Align "
        "momentum_min_tvl_usd with min_liquidity_usd so momentum never runs on dust.",
    ),
    "Routes and reporting": (
        "Sell-route probes (e.g. Jupiter) and how strict price impact must be.",
        "5% impact is loose for small clips; 1–3% is stricter. Enable rejections CSV "
        "while tuning gates.",
    ),
    "Wallet and emergency": (
        "Sizing and optional emergency exit behaviour.",
        "Reserve SOL for fees; keep emergency close off until automation is trusted.",
    ),
    "LP order entry (CLMM)": (
        "Choose how the next CLMM position is ranged and pay-token rules. Manual LIVE opens "
        "(explicit pool id) also enforce min pool TVL and optional alt sell-route checks below.",
        "Keep manual min TVL at $1000+; use open_live_lp_cli.py POOL_ID for targeted opens.",
    ),
    "Network metadata": (
        "Strategy tag, RPC list, allow/block lists, and paths for dashboard output.",
        "Use two RPC providers; allowed quotes SOL,USDC is a flexible default.",
    ),
}


def attach_field_help(sections: list[dict[str, Any]]) -> None:
    for sec in sections:
        for field in sec.get("fields", []):
            key = field.get("key")
            if not isinstance(key, str):
                continue
            pair = FIELD_HELP.get(key)
            if not pair:
                continue
            help_text, live_hint = pair
            field["help"] = help_text
            if live_hint:
                field["live_hint"] = live_hint


def attach_section_help(sections: list[dict[str, Any]]) -> None:
    for sec in sections:
        title = sec.get("title")
        if not isinstance(title, str):
            continue
        blurb = SECTION_BLURB.get(title)
        if not blurb:
            continue
        intro, rec = blurb
        sec["section_help"] = intro
        sec["section_rec"] = rec
