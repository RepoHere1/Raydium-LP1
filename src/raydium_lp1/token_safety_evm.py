"""EVM token safety (Base / BNB) via the GoPlus Security API — Kyber LP equivalent
of token_safety.py for Solana.

Mirrors token_safety.py's interface so the SAME filter contract protects every
venue: check_token() -> flags, evaluate_token() -> {pass, reason}, and
filter_token_safety_evm() plugs into filter_suite. DEFAULT OFF.

GoPlus is keyless for basic calls:
  GET https://api.gopluslabs.io/api/v1/token_security/{chain_id}?contract_addresses={addr}
  chain_id: Base=8453, BNB=56, Ethereum=1, Arbitrum=42161, ...

The honeypot / hidden-tax vectors we read (all "1"/"0" strings from GoPlus):
  is_honeypot           -> you literally cannot sell (hard block)
  cannot_sell_all       -> can't fully exit (honeypot-lite)
  cannot_buy            -> can't even enter
  buy_tax / sell_tax / transfer_tax -> hidden taxes (fractions, e.g. "0.05" = 5%)
  is_blacklisted        -> contract can blacklist your address
  transfer_pausable     -> issuer can freeze all transfers
  trading_cooldown      -> forced hold timer (can't exit when you want)
  slippage_modifiable / personal_slippage_modifiable -> tax can be cranked later
  hidden_owner / can_take_back_ownership -> stealth control / re-rug
  selfdestruct          -> contract can be destroyed
  is_open_source        -> "0" means unverified bytecode (treat as risky)

Config keys (read from the filter cfg dict; safe defaults baked in):
  evm_token_safety_enabled            (bool, default False) -> master switch
  evm_token_safety_max_buy_tax_bps    (int,  default 300)   -> block buy tax > 3%
  evm_token_safety_max_sell_tax_bps   (int,  default 300)   -> block sell tax > 3%
  evm_token_safety_require_open_source(bool, default True)
  evm_token_safety_block_pausable     (bool, default True)
  evm_token_safety_block_blacklist    (bool, default True)
  evm_token_safety_allow_tokens       (list[str], lowercased addresses to skip)
  evm_token_safety_fail_open          (bool, default True)  -> on API error, PASS
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

GOPLUS = "https://api.gopluslabs.io/api/v1/token_security"

# chain name -> GoPlus chain id (strings the Kyber scan already uses)
CHAIN_IDS = {"base": "8453", "8453": "8453", "bnb": "56", "bsc": "56", "56": "56",
             "ethereum": "1", "1": "1", "arbitrum": "42161", "42161": "42161"}

# (address.lower(), chain_id) -> result dict (process-lifetime cache)
_CACHE: dict[tuple[str, str], dict[str, Any]] = {}


def _to_bool(v: Any) -> bool:
    return str(v).strip() in ("1", "true", "True")


def _tax_bps(v: Any) -> int:
    """GoPlus taxes are decimal fractions as strings ('0.05'=5%). -> basis points."""
    try:
        return int(round(float(v) * 10000))
    except (TypeError, ValueError):
        return 0


def _fetch(chain_id: str, address: str, *, timeout: int = 15) -> dict | None:
    url = f"{GOPLUS}/{chain_id}?" + urlencode({"contract_addresses": address})
    try:
        req = Request(url, headers={"accept": "application/json",
                                    "user-agent": "Raydium-LP1/evm-token-safety"})
        with urlopen(req, timeout=timeout) as resp:  # noqa: S310
            payload = json.loads(resp.read())
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    if payload.get("code") != 1:
        return None
    result = payload.get("result") or {}
    # GoPlus keys the result by the lowercased address
    for k, v in result.items():
        if k.lower() == address.lower():
            return v
    return next(iter(result.values()), None)


def check_token(address: str, chain: str) -> dict[str, Any]:
    """Inspect one EVM token. Returns safety flags (cached per address+chain)."""
    address = (address or "").strip().lower()
    chain_id = CHAIN_IDS.get(str(chain).strip().lower())
    if not address or not chain_id:
        return {"address": address, "ok": True, "reason": "no address/unknown chain",
                "checked": False}
    key = (address, chain_id)
    if key in _CACHE:
        return _CACHE[key]

    raw = _fetch(chain_id, address)
    if raw is None:
        res = {"address": address, "ok": None, "reason": "GoPlus no data", "checked": False}
        _CACHE[key] = res
        return res

    res: dict[str, Any] = {
        "address": address, "chain_id": chain_id, "checked": True, "ok": True,
        "is_honeypot": _to_bool(raw.get("is_honeypot")),
        "cannot_sell_all": _to_bool(raw.get("cannot_sell_all")),
        "cannot_buy": _to_bool(raw.get("cannot_buy")),
        "buy_tax_bps": _tax_bps(raw.get("buy_tax")),
        "sell_tax_bps": _tax_bps(raw.get("sell_tax")),
        "transfer_tax_bps": _tax_bps(raw.get("transfer_tax")),
        "is_blacklisted": _to_bool(raw.get("is_blacklisted")),
        "transfer_pausable": _to_bool(raw.get("transfer_pausable")),
        "trading_cooldown": _to_bool(raw.get("trading_cooldown")),
        "slippage_modifiable": _to_bool(raw.get("slippage_modifiable")),
        "personal_slippage_modifiable": _to_bool(raw.get("personal_slippage_modifiable")),
        "hidden_owner": _to_bool(raw.get("hidden_owner")),
        "can_take_back_ownership": _to_bool(raw.get("can_take_back_ownership")),
        "selfdestruct": _to_bool(raw.get("selfdestruct")),
        "is_open_source": _to_bool(raw.get("is_open_source")),
        "is_proxy": _to_bool(raw.get("is_proxy")),
        "is_mintable": _to_bool(raw.get("is_mintable")),
    }
    _CACHE[key] = res
    return res


def evaluate_token(address: str, chain: str, cfg: dict) -> dict[str, Any]:
    """Apply config policy to one EVM token. Returns {pass, reason, info}."""
    info = check_token(address, chain)
    allow = {a.lower() for a in (cfg.get("evm_token_safety_allow_tokens") or [])}
    if (address or "").lower() in allow:
        return {"pass": True, "reason": "token allowlisted", "info": info}

    if info.get("checked") is False:
        if info.get("ok") is None:
            fail_open = bool(cfg.get("evm_token_safety_fail_open", True))
            return {"pass": fail_open,
                    "reason": f"{address[:8]}…: {info.get('reason')} "
                              f"({'fail-open pass' if fail_open else 'fail-closed block'})",
                    "info": info}
        return {"pass": True, "reason": info.get("reason", "skipped"), "info": info}

    reasons: list[str] = []
    # Hard honeypot vectors — always block.
    if info["is_honeypot"]:
        reasons.append("HONEYPOT (cannot sell)")
    if info["cannot_sell_all"]:
        reasons.append("cannot sell all (honeypot-lite)")
    if info["cannot_buy"]:
        reasons.append("cannot buy")
    if info["selfdestruct"]:
        reasons.append("selfdestruct present")
    if info["hidden_owner"]:
        reasons.append("hidden owner")
    if info["can_take_back_ownership"]:
        reasons.append("can take back ownership (re-rug)")
    # Policy-gated vectors.
    if bool(cfg.get("evm_token_safety_block_blacklist", True)) and info["is_blacklisted"]:
        reasons.append("blacklist function (can freeze your address)")
    if bool(cfg.get("evm_token_safety_block_pausable", True)) and info["transfer_pausable"]:
        reasons.append("transfers pausable")
    if bool(cfg.get("evm_token_safety_require_open_source", True)) and not info["is_open_source"]:
        reasons.append("unverified / closed-source bytecode")
    if info["slippage_modifiable"] or info["personal_slippage_modifiable"]:
        reasons.append("tax/slippage modifiable (can be cranked after entry)")
    max_buy = int(cfg.get("evm_token_safety_max_buy_tax_bps", 300))
    max_sell = int(cfg.get("evm_token_safety_max_sell_tax_bps", 300))
    if info["buy_tax_bps"] > max_buy:
        reasons.append(f"buy tax {info['buy_tax_bps']}bps > max {max_buy}")
    if info["sell_tax_bps"] > max_sell:
        reasons.append(f"sell tax {info['sell_tax_bps']}bps > max {max_sell}")

    if reasons:
        return {"pass": False, "reason": "; ".join(reasons), "info": info}
    return {"pass": True, "reason": "token safe", "info": info}


def filter_token_safety_evm(cand: dict, cfg: dict) -> dict:
    """filter_suite-compatible EVM filter. DEFAULT OFF.

    Expects candidate fields (from the Kyber scan):
      token0_address / token1_address  (or token0/token1)
      chain  (e.g. 'base' or 'bnb', or chain_id '8453'/'56')
    Put LAST in the chain — one API call per surviving candidate.
    """
    if not bool(cfg.get("evm_token_safety_enabled", False)):
        return {"pass": True, "reason": "evm token safety off"}
    chain = cand.get("chain") or cand.get("chain_id") or cfg.get("evm_chain") or ""
    for key in ("token0_address", "token1_address", "token0", "token1",
                "mint_a", "mint_b"):
        addr = str(cand.get(key) or "")
        if not addr.startswith("0x"):
            continue
        r = evaluate_token(addr, chain, cfg)
        if not r["pass"]:
            return {"pass": False, "reason": f"{key} unsafe: {r['reason']}"}
    return {"pass": True, "reason": "tokens safe"}


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("usage: python -m raydium_lp1.token_safety_evm <address> <chain: base|bnb>")
        sys.exit(2)
    print(json.dumps(check_token(sys.argv[1], sys.argv[2]), indent=2))
