"""Prove Raydium pool identifiers are real on-chain pool accounts.

Explorers often label any Solana pubkey as a "wallet". Raydium's api-v3 ``id``
field is the pool **state account** pubkey. We verify:

1. ``programId`` from the list payload is a known Raydium pool program.
2. Optional RPC ``getAccountInfo``: on-chain ``owner`` equals that program
   (not System / Token programs).
3. Optional Raydium ``/pools/info/ids`` round-trip for the same ``id``.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from raydium_lp1.http_json import load_json_from_urlopen_response


# Raydium pool program IDs (mainnet) -> short label shown in verdict stream.
RAYDIUM_POOL_PROGRAMS: dict[str, str] = {
    "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C": "CPMM",
    "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK": "CLMM",
    "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8": "AMMv4",
    "RVKd61ztZW9GUwhRbbLoYVRE5Xf1B2tVscKLYXCfqLg": "AMM",
}

# Accounts owned by these are NOT Raydium pool state (common false "wallet" hits).
NON_POOL_OWNERS = {
    "11111111111111111111111111111111",  # System
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",  # SPL Token
    "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",  # Token-2022
}

DEFAULT_PUBLIC_RPC = "https://api.mainnet-beta.solana.com"
RAYDIUM_POOL_INFO_IDS = "/pools/info/ids"
RAYDIUM_UI_POOL_URL = "https://raydium.io/liquidity/increase/?mode=add&pool_id={pool_id}"

RpcPost = Callable[[str, dict[str, Any]], dict[str, Any]]


def is_valid_solana_rpc_url(url: str) -> bool:
    """Reject junk list entries (e.g. comma-split typos like ``y`` from ``...,y``)."""

    u = (url or "").strip()
    if len(u) < 8:
        return False
    parsed = urlparse(u)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def filter_rpc_urls(urls: Iterable[str], *, warn: bool = True) -> list[str]:
    """Return only usable HTTP(S) RPC endpoints, deduped in order."""

    seen: set[str] = set()
    out: list[str] = []
    for raw in urls:
        u = str(raw).strip()
        if is_valid_solana_rpc_url(u):
            if u not in seen:
                seen.add(u)
                out.append(u)
        elif u and warn:
            print(
                f"[config] skipping invalid Solana RPC URL (use full https://…): {u!r}",
                file=sys.stderr,
            )
    return out


@dataclass(frozen=True)
class PoolVerification:
    ok: bool
    pool_id: str
    program_id: str
    program_label: str
    on_chain_owner: str | None = None
    on_chain_ok: bool | None = None
    raydium_api_ok: bool | None = None
    proof_tag: str = ""
    raydium_verify_url: str = ""
    raydium_ui_url: str = ""
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "pool_id": self.pool_id,
            "program_id": self.program_id,
            "program_label": self.program_label,
            "on_chain_owner": self.on_chain_owner,
            "on_chain_ok": self.on_chain_ok,
            "raydium_api_ok": self.raydium_api_ok,
            "proof_tag": self.proof_tag,
            "raydium_verify_url": self.raydium_verify_url,
            "raydium_ui_url": self.raydium_ui_url,
            "reasons": list(self.reasons),
        }


def program_label(program_id: str) -> str:
    return RAYDIUM_POOL_PROGRAMS.get(program_id, "")


def raydium_verify_url(api_base: str, pool_id: str) -> str:
    base = api_base.rstrip("/")
    return f"{base}{RAYDIUM_POOL_INFO_IDS}?ids={quote(pool_id, safe='')}"


def raydium_ui_url(pool_id: str) -> str:
    return RAYDIUM_UI_POOL_URL.format(pool_id=quote(pool_id, safe=""))


def _build_proof_tag(
    *,
    program_label: str,
    on_chain_ok: bool | None,
    raydium_api_ok: bool | None,
) -> str:
    parts: list[str] = []
    if program_label:
        parts.append(program_label)
    if on_chain_ok is True:
        parts.append("chain")
    elif on_chain_ok is False:
        parts.append("!chain")
    if raydium_api_ok is True:
        parts.append("api")
    elif raydium_api_ok is False:
        parts.append("!api")
    return "+".join(parts) if parts else "?"


def verify_api_program(pool: dict[str, Any]) -> tuple[bool, list[str], str]:
    """Fast check: Raydium list payload declares a known pool program."""

    pool_id = str(pool.get("id") or "")
    program_id = str(pool.get("program_id") or "")
    reasons: list[str] = []
    if not pool_id:
        reasons.append("missing pool id")
        return False, reasons, ""
    if not program_id:
        reasons.append("missing Raydium programId on pool payload")
        return False, reasons, ""
    label = program_label(program_id)
    if not label:
        reasons.append(
            f"programId {program_id} is not a known Raydium pool program "
            f"(known: {', '.join(sorted(set(RAYDIUM_POOL_PROGRAMS.values())))})"
        )
        return False, reasons, ""
    return True, reasons, label


def fetch_raydium_pool_by_id(
    pool_id: str,
    *,
    api_base: str,
    timeout: int = 12,
    fetch_json: Callable[[str, int], dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Return Raydium pool record for ``pool_id`` or None if API has no match."""

    url = raydium_verify_url(api_base, pool_id)

    def _default_fetch(u: str, t: int) -> dict[str, Any]:
        request = Request(u, headers={"accept": "application/json", "user-agent": "Raydium-LP1/verify"})
        with urlopen(request, timeout=t) as response:  # noqa: S310
            return load_json_from_urlopen_response(response)

    loader = fetch_json or _default_fetch
    try:
        payload = loader(url, timeout)
    except (OSError, json.JSONDecodeError, RuntimeError):
        return None
    data = payload.get("data")
    if not payload.get("success") or not isinstance(data, list) or not data:
        return None
    first = data[0]
    return first if isinstance(first, dict) else None


def prefetch_account_owners(
    pubkeys: list[str],
    rpc_urls: list[str],
    *,
    owner_cache: dict[str, str | None],
    rpc_post: RpcPost | None = None,
    chunk_size: int = 100,
) -> None:
    """Batch-fill ``owner_cache`` via ``getMultipleAccounts`` (one RPC per chunk)."""

    pending = [pk for pk in pubkeys if pk and pk not in owner_cache]
    if not pending:
        return
    urls = filter_rpc_urls(rpc_urls, warn=False) or [DEFAULT_PUBLIC_RPC]

    def _post(url: str, keys: list[str]) -> dict[str, Any]:
        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getMultipleAccounts",
            "params": [keys, {"encoding": "base64"}],
        }
        if rpc_post is not None:
            return rpc_post(url, body)
        request = Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "accept": "application/json",
                "accept-encoding": "identity",
                "user-agent": "Raydium-LP1/pool-verify",
            },
            method="POST",
        )
        with urlopen(request, timeout=12) as resp:  # noqa: S310
            return load_json_from_urlopen_response(resp)

    for start in range(0, len(pending), chunk_size):
        chunk = pending[start : start + chunk_size]
        for url in urls:
            try:
                response = _post(url, chunk)
            except (OSError, json.JSONDecodeError, RuntimeError, KeyError):
                continue
            values = (response.get("result") or {}).get("value")
            if not isinstance(values, list):
                continue
            for pk, entry in zip(chunk, values):
                if entry is None:
                    owner_cache[pk] = None
                else:
                    owner_cache[pk] = str(entry.get("owner") or "")
            break


def get_account_owner(
    pubkey: str,
    rpc_url: str,
    *,
    rpc_post: RpcPost | None = None,
    timeout: int = 8,
) -> str | None:
    """Return the on-chain owner program id for ``pubkey``, or None if missing."""

    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getAccountInfo",
        "params": [pubkey, {"encoding": "base64"}],
    }
    if rpc_post is not None:
        response = rpc_post(rpc_url, body)
    else:
        request = Request(
            rpc_url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "accept": "application/json",
                "accept-encoding": "identity",
                "user-agent": "Raydium-LP1/pool-verify",
            },
            method="POST",
        )
        with urlopen(request, timeout=timeout) as resp:  # noqa: S310
            response = load_json_from_urlopen_response(resp)
    value = (response.get("result") or {}).get("value")
    if not value:
        return None
    return str(value.get("owner") or "")


def verify_on_chain_owner(
    pool_id: str,
    expected_program_id: str,
    rpc_urls: list[str],
    *,
    rpc_post: RpcPost | None = None,
    owner_cache: dict[str, str | None] | None = None,
) -> tuple[bool, str | None, list[str]]:
    """Confirm ``pool_id`` account is owned by ``expected_program_id`` (Raydium pool)."""

    cache = owner_cache if owner_cache is not None else {}
    owner: str | None = None
    if pool_id in cache:
        owner = cache[pool_id]
    else:
        urls = filter_rpc_urls(rpc_urls, warn=False) or [DEFAULT_PUBLIC_RPC]
        for url in urls:
            try:
                owner = get_account_owner(pool_id, url, rpc_post=rpc_post)
            except (OSError, json.JSONDecodeError, RuntimeError, KeyError):
                continue
            if owner is not None:
                break
        cache[pool_id] = owner

    reasons: list[str] = []
    if owner is None:
        if len(pool_id) <= 12:
            short = pool_id
        else:
            short = f"{pool_id[:6]}…{pool_id[-4:]}"
        reasons.append(f"on-chain: no RPC account ({short}); id is wrong or not LP state")
        return False, None, reasons
    if owner in NON_POOL_OWNERS:
        reasons.append(
            f"on-chain: {pool_id} is owned by {owner} (wallet/token/system), "
            "not a Raydium pool program — explorers often mislabel this as 'wallet'"
        )
        return False, owner, reasons
    if owner != expected_program_id:
        reasons.append(
            f"on-chain: owner {owner} != Raydium programId {expected_program_id} from API"
        )
        return False, owner, reasons
    if owner not in RAYDIUM_POOL_PROGRAMS:
        reasons.append(f"on-chain: owner {owner} is not a known Raydium pool program")
        return False, owner, reasons
    return True, owner, reasons


def validate_pool(
    pool: dict[str, Any],
    *,
    api_base: str,
    rpc_urls: list[str],
    verify_on_chain: bool = True,
    verify_raydium_api: bool = False,
    rpc_post: RpcPost | None = None,
    owner_cache: dict[str, str | None] | None = None,
    fetch_json: Callable[[str, int], dict[str, Any]] | None = None,
) -> PoolVerification:
    """Full verification for one normalized pool dict."""

    pool_id = str(pool.get("id") or "")
    program_id = str(pool.get("program_id") or "")
    api_ok, api_reasons, label = verify_api_program(pool)
    all_reasons = list(api_reasons)
    on_chain_ok: bool | None = None
    on_chain_owner: str | None = None
    raydium_api_ok: bool | None = None

    if api_ok and verify_on_chain:
        on_chain_ok, on_chain_owner, chain_reasons = verify_on_chain_owner(
            pool_id,
            program_id,
            rpc_urls,
            rpc_post=rpc_post,
            owner_cache=owner_cache,
        )
        if not on_chain_ok:
            all_reasons.extend(chain_reasons)

    if api_ok and verify_raydium_api:
        record = fetch_raydium_pool_by_id(
            pool_id,
            api_base=api_base,
            fetch_json=fetch_json,
        )
        raydium_api_ok = record is not None and str(record.get("id") or "") == pool_id
        if not raydium_api_ok:
            all_reasons.append(
                f"Raydium API has no pool record for id {pool_id} "
                f"(see {raydium_verify_url(api_base, pool_id)})"
            )

    ok = api_ok and (on_chain_ok is not False) and (raydium_api_ok is not False)
    proof = _build_proof_tag(
        program_label=label,
        on_chain_ok=on_chain_ok,
        raydium_api_ok=raydium_api_ok,
    )
    return PoolVerification(
        ok=ok,
        pool_id=pool_id,
        program_id=program_id,
        program_label=label,
        on_chain_owner=on_chain_owner,
        on_chain_ok=on_chain_ok,
        raydium_api_ok=raydium_api_ok,
        proof_tag=proof,
        raydium_verify_url=raydium_verify_url(api_base, pool_id) if pool_id else "",
        raydium_ui_url=raydium_ui_url(pool_id) if pool_id else "",
        reasons=all_reasons,
    )
