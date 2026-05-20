"""On-chain SPL mint checks for exit safety (dry-run, read-only RPC).

Rejects pools whose non-base mints are not standard Token / Token-2022 mint
accounts, or whose Token-2022 **transfer fee** (on-chain tax) exceeds your cap.

This is not a full smart-contract audit of arbitrary programs; it enforces
that liquidity tokens are normal SPL mints and that documented transfer fees
cannot exceed the configured basis-point ceiling before route/slippage checks.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from raydium_lp1.pool_verify import DEFAULT_PUBLIC_RPC, filter_rpc_urls

RpcPost = Callable[[str, dict[str, Any]], dict[str, Any]]

SPL_TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"


def _post_json(url: str, body: dict[str, Any], rpc_post: RpcPost | None) -> dict[str, Any]:
    if rpc_post is not None:
        return rpc_post(url, body)
    from urllib.request import Request, urlopen

    request = Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "accept": "application/json",
            "accept-encoding": "identity",
            "user-agent": "Raydium-LP1/mint-safety",
        },
        method="POST",
    )
    with urlopen(request, timeout=12) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def _max_transfer_fee_bps_from_extensions(extensions: object) -> int:
    """Return the highest configured transfer fee in basis points (0 if none)."""

    if not isinstance(extensions, list):
        return 0
    max_bps = 0
    for ext in extensions:
        if not isinstance(ext, dict):
            continue
        if ext.get("extension") != "transferFeeConfig":
            continue
        state = ext.get("state")
        if not isinstance(state, dict):
            continue
        for key in ("newerTransferFee", "olderTransferFee"):
            fee = state.get(key)
            if isinstance(fee, dict):
                try:
                    bps = int(fee.get("transferFeeBasisPoints") or 0)
                except (TypeError, ValueError):
                    bps = 0
                max_bps = max(max_bps, bps)
    return max_bps


def fetch_mint_accounts_parsed(
    mints: list[str],
    rpc_urls: list[str],
    *,
    rpc_post: RpcPost | None = None,
) -> dict[str, dict[str, Any]]:
    """Return per-mint dict with keys ``owner``, ``info``, ``missing``.

    Uses ``getMultipleAccounts`` with ``jsonParsed`` encoding (one RPC round-trip).
    """

    out: dict[str, dict[str, Any]] = {}
    need = [m for m in mints if m and m not in out]
    if not need:
        return out
    urls = filter_rpc_urls(rpc_urls, warn=False) or [DEFAULT_PUBLIC_RPC]
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getMultipleAccounts",
        "params": [need, {"encoding": "jsonParsed"}],
    }
    for url in urls:
        try:
            response = _post_json(url, body, rpc_post)
        except (OSError, json.JSONDecodeError, RuntimeError, KeyError, TypeError, ValueError):
            continue
        values = (response.get("result") or {}).get("value")
        if not isinstance(values, list):
            continue
        for mint, entry in zip(need, values):
            if entry is None:
                out[mint] = {"missing": True, "owner": None, "info": None}
                continue
            owner = str(entry.get("owner") or "")
            data = entry.get("data")
            info: dict[str, Any] | None = None
            if isinstance(data, dict):
                parsed = data.get("parsed")
                if isinstance(parsed, dict) and parsed.get("type") == "mint":
                    raw_info = parsed.get("info")
                    info = raw_info if isinstance(raw_info, dict) else None
            out[mint] = {"missing": False, "owner": owner or None, "info": info}
        break
    for m in need:
        if m not in out:
            out[m] = {"missing": True, "owner": None, "info": None}
    return out


def validate_pool_mints_exit_safety(
    pool: dict[str, Any],
    *,
    rpc_urls: list[str],
    max_transfer_fee_bps: int,
    require_standard_token_program: bool,
    rpc_post: RpcPost | None = None,
) -> tuple[bool, list[str]]:
    """Return (ok, reasons) for both pool mints."""

    reasons: list[str] = []
    mint_a = str(pool.get("mint_a") or "")
    mint_b = str(pool.get("mint_b") or "")
    sym_a = str(pool.get("mint_a_symbol") or "?")
    sym_b = str(pool.get("mint_b_symbol") or "?")
    targets = [(mint_a, "A", sym_a), (mint_b, "B", sym_b)]
    mints = [m for m, _, _ in targets if m]
    if not mints:
        return False, ["missing mint address(es) on pool payload"]

    accounts = fetch_mint_accounts_parsed(mints, rpc_urls, rpc_post=rpc_post)
    for mint, label, sym in targets:
        if not mint:
            reasons.append(f"mint {label} ({sym}) is empty")
            continue
        row = accounts.get(mint) or {"missing": True, "owner": None, "info": None}
        if row.get("missing"):
            reasons.append(
                f"mint {label} ({sym}): no on-chain mint account at {mint[:8]}… — cannot verify exit tax / program"
            )
            continue
        owner = row.get("owner")
        if require_standard_token_program and owner not in (SPL_TOKEN_PROGRAM, TOKEN_2022_PROGRAM):
            reasons.append(
                f"mint {label} ({sym}): owner program {owner} is not SPL Token / Token-2022 "
                f"(refusing non-standard mint contracts)"
            )
            continue
        info = row.get("info") if isinstance(row.get("info"), dict) else {}
        bps = _max_transfer_fee_bps_from_extensions(info.get("extensions"))
        if max_transfer_fee_bps > 0 and bps > max_transfer_fee_bps:
            reasons.append(
                f"mint {label} ({sym}): Token-2022 transfer fee {bps} bps ({bps/100:.2f}%) "
                f"exceeds max {max_transfer_fee_bps} bps ({max_transfer_fee_bps/100:.2f}%)"
            )
    return not reasons, reasons
