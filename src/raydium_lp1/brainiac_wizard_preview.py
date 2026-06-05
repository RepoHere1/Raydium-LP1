"""Human-readable preview summary for Brainiac wizard."""

from __future__ import annotations

from typing import Any, Mapping


def print_preview_summary(report: Mapping[str, Any]) -> None:
    """Print a short plan after preview JSON (so preview mode feels responsive)."""

    pt = report.get("pretrade_analysis") or {}
    plan = report.get("placement_plan") or {}
    bp = plan.get("brainiac_placement") or {}
    consensus = report.get("pre_live_consensus") or {}
    print("\n=== Preview complete (no on-chain txs) ===\n")
    print(f"  Pair:        {report.get('pair')}")
    print(f"  Pay / alt:   {report.get('pay_type')} / {report.get('non_pay')}")
    print(
        f"  Skew:        {plan.get('skew')}  "
        f"band below {plan.get('tick_lower_pct_below')}% / above {plan.get('tick_upper_pct_above')}%"
    )
    print(f"  In-range:    {bp.get('in_range_factor_at_skew')}")
    leader = bp.get("fee_model_leader") or {}
    print(f"  Model APR:   {leader.get('theoretical_apr_pct')}%")
    if consensus and not consensus.get("skipped"):
        print(
            f"  Consensus:   {consensus.get('agree_count')}/{consensus.get('scan_count')} scans agree "
            f"(median skew {consensus.get('median_skew')}, std {consensus.get('skew_std')})"
        )
        print(f"               min in-range {consensus.get('min_in_range_factor')} — {consensus.get('recommendation')}")
    if pt.get("issues"):
        print("\n  Issues:")
        for issue in pt.get("issues") or []:
            print(f"    - {issue}")
    if pt.get("proceed_recommendation"):
        print(f"\n  {pt.get('proceed_recommendation')}")
    fund = report.get("fund_non_pay_would_usd")
    if fund is not None:
        print(f"\n  Would fund non-pay: ~${fund} (skipped when skip_fund_swap=yes)")
    print("\n  To LIVE open: run wizard again, set Preview only = n, type LIVE at confirm.\n")


def print_live_report_summary(report: Mapping[str, Any]) -> None:
    """Short human summary after LIVE (fees use this-run ledger delta, not whole session)."""

    loss = report.get("permanent_loss_usd") or {}
    w = report.get("wallet_usd") or {}
    op = report.get("open") or {}
    print("\n=== LIVE result ===\n")
    print(f"  Ok:          {report.get('ok')}")
    print(f"  Pair:        {report.get('pair')}")
    print(f"  Pay / alt:   {report.get('pay_type_symbol')} / {report.get('non_pay_symbol')}")
    pl = report.get("placement") or {}
    print(
        f"  Skew:        {pl.get('skew')}  "
        f"below {pl.get('tick_lower_pct_below')}% / above {pl.get('tick_upper_pct_above')}%"
    )
    if op.get("signature"):
        print(f"  Tx:          {op.get('signature')}")
    if op.get("nft"):
        print(f"  NFT:         {op.get('nft')}")
    if op.get("error") or op.get("clmm_error"):
        print(f"  Error:       {op.get('error') or op.get('clmm_error')}")
    consensus = report.get("pre_live_consensus") or {}
    if consensus and not consensus.get("skipped"):
        print(
            f"  Consensus:   {consensus.get('agree_count')}/{consensus.get('scan_count')} scans "
            f"(median skew {consensus.get('median_skew')}, min IR {consensus.get('min_in_range_factor')})"
        )
    print(f"  Wallet delta: ${w.get('delta_usd')} USD (SOL+USDC total)")
    print(f"  Fees (run):  ${loss.get('network_fees_this_run_usd')} USD")
    print(f"  In LP:       ${loss.get('deposit_in_lp_usd')} USD")
    if loss.get("interpretation"):
        print(f"\n  {loss.get('interpretation')}\n")
