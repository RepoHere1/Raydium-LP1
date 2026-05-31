"""Post-trade SOL ledger analysis: fees, rent, escrow, net wallet delta."""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass
class TxCostBreakdown:
    signature: str
    fee_lamports: int
    fee_sol: float
    pre_balance_sol: float | None
    post_balance_sol: float | None
    wallet_delta_sol: float | None
    status: str
    err: str | None
    account_keys: list[str] = field(default_factory=list)
    writable_accounts: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "signature": self.signature,
            "fee_lamports": self.fee_lamports,
            "fee_sol": round(self.fee_sol, 9),
            "pre_balance_sol": self.pre_balance_sol,
            "post_balance_sol": self.post_balance_sol,
            "wallet_delta_sol": self.wallet_delta_sol,
            "status": self.status,
            "err": self.err,
            "writable_accounts": self.writable_accounts,
        }


def _rpc_post(rpc: str, method: str, params: list) -> Any:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(rpc, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=45) as resp:
        payload = json.loads(resp.read().decode())
    if payload.get("error"):
        raise RuntimeError(str(payload["error"]))
    return payload.get("result")


def analyze_transaction(
    signature: str,
    *,
    wallet: str,
    rpc_url: str,
) -> TxCostBreakdown:
    """Fetch one confirmed tx and estimate wallet SOL change + network fee."""

    tx = _rpc_post(
        rpc_url,
        "getTransaction",
        [
            signature,
            {"encoding": "json", "commitment": "confirmed", "maxSupportedTransactionVersion": 0},
        ],
    )
    if not tx:
        raise RuntimeError(f"transaction not found: {signature}")

    meta = tx.get("meta") or {}
    fee_lamports = int(meta.get("fee") or 0)
    err = meta.get("err")
    status = "failed" if err else "ok"

    pre = meta.get("preBalances") or []
    post = meta.get("postBalances") or []
    msg = tx.get("transaction") or {}
    keys = (msg.get("message") or {}).get("accountKeys") or []
    acct_keys = [
        k if isinstance(k, str) else str(k.get("pubkey") or "")
        for k in keys
    ]
    wallet_ix = None
    for i, k in enumerate(acct_keys):
        if k == wallet:
            wallet_ix = i
            break

    pre_sol = post_sol = delta = None
    if wallet_ix is not None and wallet_ix < len(pre) and wallet_ix < len(post):
        pre_sol = int(pre[wallet_ix]) / 1e9
        post_sol = int(post[wallet_ix]) / 1e9
        delta = post_sol - pre_sol

    writable = sum(1 for k in keys if isinstance(k, dict) and k.get("writable"))

    return TxCostBreakdown(
        signature=signature,
        fee_lamports=fee_lamports,
        fee_sol=fee_lamports / 1e9,
        pre_balance_sol=pre_sol,
        post_balance_sol=post_sol,
        wallet_delta_sol=delta,
        status=status,
        err=json.dumps(err) if err else None,
        account_keys=acct_keys[:12],
        writable_accounts=writable,
    )


def analyze_open_bundle(
    result: Mapping[str, Any],
    *,
    wallet: str,
    rpc_url: str,
    rent_escrow_estimate: Mapping[str, Any] | None = None,
    deposit_usd: float | None = None,
) -> dict[str, Any]:
    """Analyze CLMM open result (main tx + optional funding swap)."""

    sigs: list[str] = []
    clmm = result.get("clmm") or result
    main_sig = str(clmm.get("signature") or result.get("tx") or "")
    if main_sig:
        sigs.append(main_sig)
    funding = clmm.get("other_leg_funding") or {}
    fund_sig = str(funding.get("signature") or "")
    if fund_sig:
        sigs.append(fund_sig)

    txs = []
    total_fee = 0.0
    total_delta = 0.0
    for sig in sigs:
        row = analyze_transaction(sig, wallet=wallet, rpc_url=rpc_url)
        txs.append(row.to_dict())
        total_fee += row.fee_sol
        if row.wallet_delta_sol is not None:
            total_delta += row.wallet_delta_sol

    sunk_est = None
    sunk_pct = None
    if rent_escrow_estimate:
        sunk_est = float(rent_escrow_estimate.get("sunk_sol_est") or 0)
        sunk_pct = float(rent_escrow_estimate.get("sunk_pct_of_deposit") or 0)

    # Non-recoverable ≈ wallet outflow minus deposit + network fees (heuristic)
    deposit_sol = None
    if deposit_usd and rent_escrow_estimate:
        px = float(rent_escrow_estimate.get("sol_price_usd") or 180)
        deposit_sol = deposit_usd / px if px > 0 else None

    implied_sunk = None
    if deposit_sol is not None and total_delta < 0:
        implied_sunk = max(0.0, -(total_delta + deposit_sol) - total_fee)

    recommendations: list[str] = []
    if sunk_pct and sunk_pct > 10:
        recommendations.append(
            f"Rent guard would block this shape at 10% cap (est sunk {sunk_pct:.1f}% of deposit). "
            "Raise deposit, narrow band, or use centered_tight below ~$16."
        )
    if total_fee > 0.001:
        recommendations.append(
            f"Network fees ~{total_fee:.4f} SOL across {len(txs)} tx(s) — keep priority micro at 2000 unless congested."
        )
    if implied_sunk and implied_sunk > 0.02:
        recommendations.append(
            f"Observed sunk ~{implied_sunk:.4f} SOL — avoid literal full range; prefer ≤80% wide or tight centered."
        )
    if len(txs) > 1:
        recommendations.append(
            "Funding swap added a second tx — pre-fund pay token in wallet to save swap fee + CU."
        )
    if not recommendations:
        recommendations.append("Costs look proportionate; keep wide band only when deposit ≫ sunk rent (~$75+ at 10% cap).")

    return {
        "wallet": wallet,
        "signatures": sigs,
        "transactions": txs,
        "total_network_fee_sol": round(total_fee, 9),
        "total_wallet_delta_sol": round(total_delta, 9),
        "deposit_usd": deposit_usd,
        "rent_escrow_estimate": rent_escrow_estimate,
        "implied_sunk_sol": round(implied_sunk, 6) if implied_sunk is not None else None,
        "recommendations": recommendations,
    }
