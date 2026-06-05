"""On-chain SPL / Token-2022 mint safety checks (anti scam-token / hidden-tax).

Pool_verify proves a *pool* is a real Raydium pool account. This module proves a
*token mint* isn't a trap. For each mint we read the on-chain account and surface:

  - freeze_authority_set : issuer can FREEZE your tokens mid-position (rug lever).
  - mint_authority_set   : issuer can MINT more supply (dilution / soft rug).
  - is_token2022         : owned by the Token-2022 program (extensions possible).
  - transfer_fee_bps     : Token-2022 TransferFeeConfig = a HIDDEN TAX on every move.
  - has_transfer_hook    : Token-2022 TransferHook = arbitrary code that can BLOCK
                           your sell (classic honeypot vector).

Design:
  * Pure stdlib (urllib) — mirrors pool_verify's RPC style. No new deps.
  * Module-level cache keyed by mint so a scan only pays one RPC per unique mint.
  * filter_token_safety() plugs into filter_suite. It is **default OFF**; when
    enabled via config it is live and will block unsafe mints.

Config keys (all read from the filter cfg dict; safe defaults baked in):
  token_safety_enabled              (bool, default False)  -> master switch
  token_safety_rpc_urls             (list[str])            -> Solana RPC endpoints
  token_safety_block_freeze         (bool, default True)
  token_safety_block_mint_authority (bool, default False)  -> many legit tokens keep it
  token_safety_block_transfer_hook  (bool, default True)
  token_safety_max_transfer_fee_bps (int,  default 100)    -> block tax > 1%
  token_safety_allow_mints          (list[str])            -> skip these (USDC etc.)
  token_safety_fail_open            (bool, default True)    -> on RPC error, PASS
                                       (set False to be paranoid and block on doubt)
"""

from __future__ import annotations

import base64
import json
import struct
from typing import Any
from urllib.request import Request, urlopen

from raydium_lp1.pool_verify import DEFAULT_PUBLIC_RPC, filter_rpc_urls

# Token program owners
SPL_TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"

# Token-2022 extension type ids we care about (TLV `type` u16, little-endian)
EXT_TRANSFER_FEE_CONFIG = 1
EXT_TRANSFER_HOOK = 14
EXT_PERMANENT_DELEGATE = 12   # permanent delegate can move your tokens — also a rug lever
EXT_DEFAULT_ACCOUNT_STATE = 6  # can default-freeze new holders

# Well-known safe mints — never block these (skip the RPC entirely).
KNOWN_SAFE_MINTS = {
    "So11111111111111111111111111111111111111112",   # Wrapped SOL
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",   # USDC
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",   # USDT
}

# mint -> result dict (process-lifetime cache)
_CACHE: dict[str, dict[str, Any]] = {}


def _rpc_get_account(mint: str, rpc_urls: list[str], *, timeout: int = 10) -> dict | None:
    """getAccountInfo (base64) for a mint; returns the `value` dict or None."""
    body = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "getAccountInfo",
        "params": [mint, {"encoding": "base64"}],
    }).encode("utf-8")
    urls = filter_rpc_urls(rpc_urls, warn=False) or [DEFAULT_PUBLIC_RPC]
    for url in urls:
        try:
            req = Request(url, data=body, method="POST", headers={
                "content-type": "application/json",
                "accept": "application/json",
                "accept-encoding": "identity",
                "user-agent": "Raydium-LP1/token-safety",
            })
            with urlopen(req, timeout=timeout) as resp:  # noqa: S310
                payload = json.loads(resp.read())
            return (payload.get("result") or {}).get("value")
        except (OSError, json.JSONDecodeError, ValueError, KeyError):
            continue
    return None


def _parse_mint_base(data: bytes) -> dict[str, Any]:
    """Parse the 82-byte SPL Mint base (same prefix for Token-2022)."""
    out: dict[str, Any] = {"mint_authority_set": False, "freeze_authority_set": False}
    if len(data) < 82:
        out["parse_error"] = f"mint data too short ({len(data)} bytes)"
        return out
    # mintAuthority COption<Pubkey>: 4-byte option tag + 32-byte key
    mint_auth_opt = struct.unpack_from("<I", data, 0)[0]
    out["mint_authority_set"] = mint_auth_opt == 1
    # decimals at 44, isInitialized at 45
    out["decimals"] = data[44]
    # freezeAuthority COption at offset 46
    freeze_opt = struct.unpack_from("<I", data, 46)[0]
    out["freeze_authority_set"] = freeze_opt == 1
    return out


def _parse_token2022_extensions(data: bytes) -> dict[str, Any]:
    """Walk Token-2022 TLV extensions (begin at byte 166: 165 base+pad, 1 acct type)."""
    out: dict[str, Any] = {
        "transfer_fee_bps": 0,
        "has_transfer_hook": False,
        "has_permanent_delegate": False,
        "default_account_state_frozen": False,
        "extensions": [],
    }
    # Base mint is padded to 165, account_type byte at 165, TLV from 166.
    if len(data) <= 166:
        return out
    i = 166
    while i + 4 <= len(data):
        ext_type, ext_len = struct.unpack_from("<HH", data, i)
        i += 4
        if ext_type == 0:  # Uninitialized — end of meaningful TLV
            break
        body = data[i:i + ext_len]
        i += ext_len
        out["extensions"].append(ext_type)
        if ext_type == EXT_TRANSFER_FEE_CONFIG and len(body) >= 36:
            # TransferFeeConfig layout:
            #   transfer_fee_config_authority : 32 (OptionalNonZeroPubkey)
            #   withdraw_withheld_authority   : 32
            #   withheld_amount               : u64 (8)
            #   older_transfer_fee : { epoch u64, maximum_fee u64, bps u16 } = 18
            #   newer_transfer_fee : { epoch u64, maximum_fee u64, bps u16 } = 18
            # transfer_fee_basis_points is the LAST u16 of each 18-byte TransferFee.
            # Take the max of older/newer to be conservative (which is active
            # depends on current epoch; blocking on the larger fails safe).
            try:
                newer_bps = struct.unpack_from("<H", body, len(body) - 2)[0]
                older_bps = struct.unpack_from("<H", body, len(body) - 20)[0]
                bps = max(newer_bps, older_bps)
                out["transfer_fee_bps"] = bps if 0 <= bps <= 10000 else 0
            except struct.error:
                out["transfer_fee_bps"] = 0
        elif ext_type == EXT_TRANSFER_HOOK:
            out["has_transfer_hook"] = True
        elif ext_type == EXT_PERMANENT_DELEGATE:
            out["has_permanent_delegate"] = True
        elif ext_type == EXT_DEFAULT_ACCOUNT_STATE and body and body[0] == 2:
            out["default_account_state_frozen"] = True  # 2 == Frozen
    return out


def check_mint(mint: str, rpc_urls: list[str] | None = None) -> dict[str, Any]:
    """Inspect one mint. Returns a dict of safety flags (cached per mint)."""
    mint = (mint or "").strip()
    if not mint:
        return {"mint": mint, "ok": True, "reason": "empty mint", "checked": False}
    if mint in KNOWN_SAFE_MINTS:
        return {"mint": mint, "ok": True, "reason": "known-safe mint", "checked": False}
    if mint in _CACHE:
        return _CACHE[mint]

    value = _rpc_get_account(mint, rpc_urls or [DEFAULT_PUBLIC_RPC])
    if not value:
        res = {"mint": mint, "ok": None, "reason": "no RPC account info", "checked": False}
        _CACHE[mint] = res
        return res

    owner = str(value.get("owner") or "")
    is_t22 = owner == TOKEN_2022_PROGRAM
    try:
        raw_b64 = (value.get("data") or [None])[0]
        raw = base64.b64decode(raw_b64) if raw_b64 else b""
    except (ValueError, TypeError):
        raw = b""

    res: dict[str, Any] = {
        "mint": mint, "owner": owner, "is_token2022": is_t22,
        "checked": True, "ok": True,
        "transfer_fee_bps": 0, "has_transfer_hook": False,
        "has_permanent_delegate": False, "default_account_state_frozen": False,
    }
    res.update(_parse_mint_base(raw))
    if is_t22:
        res.update(_parse_token2022_extensions(raw))
    _CACHE[mint] = res
    return res


def evaluate_mint(mint: str, cfg: dict, rpc_urls: list[str] | None = None) -> dict[str, Any]:
    """Apply config policy to one mint. Returns {pass, reason, info}."""
    info = check_mint(mint, rpc_urls)
    allow = set(cfg.get("token_safety_allow_mints", []) or [])
    if mint in allow:
        return {"pass": True, "reason": "mint allowlisted", "info": info}

    if info.get("checked") is False:
        # known-safe / empty -> pass; RPC failure -> fail_open policy
        if info.get("ok") is None:
            fail_open = bool(cfg.get("token_safety_fail_open", True))
            return {"pass": fail_open,
                    "reason": f"mint {mint[:6]}…: {info.get('reason')} "
                              f"({'fail-open pass' if fail_open else 'fail-closed block'})",
                    "info": info}
        return {"pass": True, "reason": info.get("reason", "skipped"), "info": info}

    reasons: list[str] = []
    if bool(cfg.get("token_safety_block_freeze", True)) and info.get("freeze_authority_set"):
        reasons.append(f"freeze authority still set on {mint[:6]}… (can freeze your tokens)")
    if bool(cfg.get("token_safety_block_mint_authority", False)) and info.get("mint_authority_set"):
        reasons.append(f"mint authority still set on {mint[:6]}… (dilution risk)")
    if bool(cfg.get("token_safety_block_transfer_hook", True)) and info.get("has_transfer_hook"):
        reasons.append(f"Token-2022 transfer hook on {mint[:6]}… (can block your sell)")
    if info.get("has_permanent_delegate"):
        reasons.append(f"Token-2022 permanent delegate on {mint[:6]}… (issuer can move your tokens)")
    if info.get("default_account_state_frozen"):
        reasons.append(f"Token-2022 default-frozen state on {mint[:6]}… (new holders frozen)")
    max_fee = int(cfg.get("token_safety_max_transfer_fee_bps", 100))
    fee = int(info.get("transfer_fee_bps", 0))
    if fee > max_fee:
        reasons.append(f"Token-2022 transfer tax {fee} bps > max {max_fee} bps (hidden tax)")

    if reasons:
        return {"pass": False, "reason": "; ".join(reasons), "info": info}
    return {"pass": True, "reason": "mint safe", "info": info}


def filter_token_safety(cand: dict, cfg: dict) -> dict:
    """filter_suite-compatible filter. DEFAULT OFF — enable via token_safety_enabled.

    Put this LAST in the chain: it makes an RPC call per surviving candidate, so
    cheap filters should reject the junk first.
    """
    if not bool(cfg.get("token_safety_enabled", False)):
        return {"pass": True, "reason": "token safety off"}
    rpc_urls = cfg.get("token_safety_rpc_urls") or cfg.get("rpc_urls") or [DEFAULT_PUBLIC_RPC]
    for key in ("mint_a", "mint_b"):
        mint = str(cand.get(key) or "")
        if not mint:
            continue
        r = evaluate_mint(mint, cfg, rpc_urls)
        if not r["pass"]:
            return {"pass": False, "reason": f"{key} unsafe: {r['reason']}"}
    return {"pass": True, "reason": "mints safe"}


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("usage: python -m raydium_lp1.token_safety <mint> [rpc_url]")
        sys.exit(2)
    rpc = [sys.argv[2]] if len(sys.argv) > 2 else [DEFAULT_PUBLIC_RPC]
    print(json.dumps(check_mint(sys.argv[1], rpc), indent=2))
