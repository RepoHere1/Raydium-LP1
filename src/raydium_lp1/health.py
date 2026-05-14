"""Liquidity health monitor for Raydium-LP1.

Tracks per-pool TVL and 24h-volume snapshots over time and assigns each pool
one of three health scores:

* ``healthy``  - within normal bounds.
* ``warning``  - mid-range degradation (15-30% TVL drop, low volume).
* ``critical`` - >=30% TVL drop from entry, or volume has cratered.

Snapshots are persisted to ``reports/liquidity_history.json`` so health can be
evaluated across scan cycles and across process restarts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

DEFAULT_HISTORY_PATH = Path("reports/liquidity_history.json")
MAX_SNAPSHOTS_PER_POOL = 288  # ~ one day at 5-minute scans

HEALTH_HEALTHY = "healthy"
HEALTH_WARNING = "warning"
HEALTH_CRITICAL = "critical"

CRITICAL_TVL_DROP = 0.30
WARNING_TVL_DROP = 0.15
NEAR_ZERO_VOLUME_USD = 50.0
WARNING_VOLUME_USD = 500.0


@dataclass(frozen=True)
class HealthAssessment:
    pool_id: str
    score: str
    reasons: list[str]
    tvl_now: float
    tvl_entry: float
    tvl_drop_pct: float
    volume_now: float
    volume_entry: float
    snapshot_count: int

    def to_dict(self) -> dict:
        return {
            "pool_id": self.pool_id,
            "score": self.score,
            "reasons": list(self.reasons),
            "tvl_now": self.tvl_now,
            "tvl_entry": self.tvl_entry,
            "tvl_drop_pct": self.tvl_drop_pct,
            "volume_now": self.volume_now,
            "volume_entry": self.volume_entry,
            "snapshot_count": self.snapshot_count,
        }


def load_history(path: Path = DEFAULT_HISTORY_PATH) -> dict:
    """Read the on-disk history. Returns {} when missing or corrupt."""

    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def save_history(history: dict, path: Path = DEFAULT_HISTORY_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(history, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def record_snapshot(
    history: dict,
    pool: dict,
    *,
    now_iso: str | None = None,
    max_snapshots: int = MAX_SNAPSHOTS_PER_POOL,
) -> dict:
    """Append a snapshot for ``pool`` into ``history`` (in place) and return it.

    A pool entry looks like::

        {
            "pair": "SOL/TEST",
            "entry": {"tvl": ..., "volume_24h": ..., "ts": "..."},
            "snapshots": [{"ts": "...", "tvl": ..., "volume_24h": ...}, ...]
        }
    """

    pool_id = str(pool.get("id") or "")
    if not pool_id:
        return history
    pair = f"{pool.get('mint_a_symbol', '')}/{pool.get('mint_b_symbol', '')}"
    snapshot = {
        "ts": now_iso or _now_iso(),
        "tvl": float(pool.get("liquidity_usd", 0.0) or 0.0),
        "volume_24h": float(pool.get("volume_24h_usd", 0.0) or 0.0),
        "apr": float(pool.get("apr", 0.0) or 0.0),
    }
    entry = history.get(pool_id) or {}
    if not entry.get("entry"):
        entry["entry"] = dict(snapshot)
    entry["pair"] = pair
    snapshots = list(entry.get("snapshots") or [])
    snapshots.append(snapshot)
    if max_snapshots > 0 and len(snapshots) > max_snapshots:
        snapshots = snapshots[-max_snapshots:]
    entry["snapshots"] = snapshots
    entry["last_seen"] = snapshot["ts"]
    history[pool_id] = entry
    return history


def assess_health(history: dict, pool: dict) -> HealthAssessment:
    """Return a :class:`HealthAssessment` for the given pool against history.

    If ``history`` has no entry yet, the pool is reported as ``healthy`` with
    snapshot_count=0 (first sighting baseline).
    """

    pool_id = str(pool.get("id") or "")
    entry = history.get(pool_id) or {}
    snapshots = list(entry.get("snapshots") or [])
    tvl_now = float(pool.get("liquidity_usd", 0.0) or 0.0)
    volume_now = float(pool.get("volume_24h_usd", 0.0) or 0.0)
    entry_snapshot = entry.get("entry") or {}
    tvl_entry = float(entry_snapshot.get("tvl") or tvl_now)
    volume_entry = float(entry_snapshot.get("volume_24h") or volume_now)

    reasons: list[str] = []
    score = HEALTH_HEALTHY
    drop_pct = 0.0
    if tvl_entry > 0:
        drop_pct = (tvl_entry - tvl_now) / tvl_entry
        if drop_pct >= CRITICAL_TVL_DROP:
            score = HEALTH_CRITICAL
            reasons.append(f"TVL down {drop_pct * 100:.1f}% from entry (${tvl_entry:,.0f} -> ${tvl_now:,.0f})")
        elif drop_pct >= WARNING_TVL_DROP:
            score = HEALTH_WARNING
            reasons.append(f"TVL down {drop_pct * 100:.1f}% from entry (${tvl_entry:,.0f} -> ${tvl_now:,.0f})")

    if volume_now <= NEAR_ZERO_VOLUME_USD:
        if score != HEALTH_CRITICAL:
            score = HEALTH_CRITICAL
        reasons.append(f"24h volume near zero (${volume_now:,.2f})")
    elif volume_now < WARNING_VOLUME_USD and volume_entry > 0 and volume_now < volume_entry * 0.25:
        if score == HEALTH_HEALTHY:
            score = HEALTH_WARNING
        reasons.append(
            f"24h volume collapsed (${volume_entry:,.0f} -> ${volume_now:,.0f})"
        )

    return HealthAssessment(
        pool_id=pool_id,
        score=score,
        reasons=reasons,
        tvl_now=tvl_now,
        tvl_entry=tvl_entry,
        tvl_drop_pct=drop_pct,
        volume_now=volume_now,
        volume_entry=volume_entry,
        snapshot_count=len(snapshots),
    )


def assess_pools(
    pools: Iterable[dict],
    *,
    history_path: Path = DEFAULT_HISTORY_PATH,
    persist: bool = True,
    now_iso: str | None = None,
) -> tuple[list[HealthAssessment], dict]:
    """Convenience: load history, record fresh snapshots, assess, save."""

    history = load_history(history_path)
    assessments: list[HealthAssessment] = []
    for pool in pools:
        record_snapshot(history, pool, now_iso=now_iso)
        assessments.append(assess_health(history, pool))
    if persist:
        save_history(history, history_path)
    return assessments, history
