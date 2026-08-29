from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from edgedash import storage
from edgedash.config import Config


def _parse_iso(ts: Any) -> datetime | None:
    if not ts or not isinstance(ts, str):
        return None
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


@dataclass
class SystemState:
    last_fetch_at: datetime | None
    hours_since_fetch: float | None
    unscored_count: int
    gaps_computed_at: datetime | None
    gaps_stale: bool
    last_cycle_verdict: str | None
    last_cycle_at: datetime | None


def read_state(config: Config, now: datetime) -> SystemState:
    metrics = storage.get_state_metrics(config.db_path)

    last_fetch_at = _parse_iso(metrics.get("last_fetch_at"))
    max_scored_at = _parse_iso(metrics.get("max_scored_at"))
    gaps_computed_at = _parse_iso(metrics.get("gaps_computed_at"))
    last_cycle_at = _parse_iso(metrics.get("last_cycle_at"))

    unscored_count = int(metrics.get("unscored_count") or 0)
    last_cycle_verdict = metrics.get("last_cycle_verdict")

    # Compute hours_since_fetch
    if last_fetch_at is not None:
        now_tz = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
        fetch_tz = (
            last_fetch_at
            if last_fetch_at.tzinfo is not None
            else last_fetch_at.replace(tzinfo=timezone.utc)
        )
        hours_since_fetch = max(0.0, (now_tz - fetch_tz).total_seconds() / 3600.0)
    else:
        hours_since_fetch = None

    # Compute gaps_stale (true if no snapshot exists or if any score is newer than snapshot)
    if gaps_computed_at is None:
        gaps_stale = True
    elif max_scored_at is not None:
        gaps_stale = max_scored_at > gaps_computed_at
    else:
        gaps_stale = False

    return SystemState(
        last_fetch_at=last_fetch_at,
        hours_since_fetch=hours_since_fetch,
        unscored_count=unscored_count,
        gaps_computed_at=gaps_computed_at,
        gaps_stale=gaps_stale,
        last_cycle_verdict=last_cycle_verdict,
        last_cycle_at=last_cycle_at,
    )
