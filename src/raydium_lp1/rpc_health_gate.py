"""RpcHealthGate: refuse to even start a scan unless enough RPCs are healthy.

The name to remember is **rpc_health_gate**.

Why this matters, in plain English:
- Half of this project's safety filters (`honeypot_guard`, `mint_authority_guard`,
  `lp_lock_guard`) call a Solana JSON-RPC. If every configured RPC is down,
  those guards either fail open (silently letting risky pools through) or
  fail closed (rejecting *every* candidate). Both states are bad without the
  operator knowing.
- This gate samples the configured RPCs with `getHealth` *before* scanning
  Raydium and stops the run unless `min_healthy_rpcs` answered OK. The text
  report still gets a one-line summary so you know which providers came back
  alive.

For dry-run scanning we want this enabled by default. When you have no RPCs
configured at all and don't want to add any, set `enabled=false`.

Settings live under `rpc_health_gate` in `config/settings.json`.
See SETTINGS.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RpcHealthGateConfig:
    enabled: bool = True
    min_healthy_rpcs: int = 1
    require_when_no_rpc_configured: bool = False

    @classmethod
    def from_raw(cls, raw: Any) -> "RpcHealthGateConfig":
        if not isinstance(raw, dict):
            return cls()
        return cls(
            enabled=bool(raw.get("enabled", cls.enabled)),
            min_healthy_rpcs=max(0, int(raw.get("min_healthy_rpcs", cls.min_healthy_rpcs))),
            require_when_no_rpc_configured=bool(
                raw.get("require_when_no_rpc_configured", cls.require_when_no_rpc_configured)
            ),
        )


@dataclass(frozen=True)
class RpcHealthSummary:
    enabled: bool
    required: int
    healthy: int
    total: int
    passed: bool
    results: list[dict[str, Any]]

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "required_healthy": self.required,
            "healthy_count": self.healthy,
            "configured_count": self.total,
            "passed": self.passed,
            "results": self.results,
        }


def evaluate_rpc_health_gate(
    config: RpcHealthGateConfig,
    rpc_check_results: list[dict[str, Any]] | None,
    *,
    rpc_count: int,
) -> RpcHealthSummary:
    """Run the gate against the result list produced by `check_rpc_urls`."""

    if not config.enabled:
        return RpcHealthSummary(
            enabled=False,
            required=config.min_healthy_rpcs,
            healthy=0,
            total=rpc_count,
            passed=True,
            results=rpc_check_results or [],
        )

    if rpc_count == 0 and not config.require_when_no_rpc_configured:
        return RpcHealthSummary(
            enabled=True,
            required=config.min_healthy_rpcs,
            healthy=0,
            total=0,
            passed=True,
            results=[],
        )

    results = rpc_check_results or []
    healthy = sum(1 for entry in results if entry.get("ok"))
    passed = healthy >= config.min_healthy_rpcs
    return RpcHealthSummary(
        enabled=True,
        required=config.min_healthy_rpcs,
        healthy=healthy,
        total=rpc_count,
        passed=passed,
        results=results,
    )


__all__ = [
    "RpcHealthGateConfig",
    "RpcHealthSummary",
    "evaluate_rpc_health_gate",
]
