"""edgedash/agents/verifier.py

Verifier agent implementing the Agent protocol.
Validates current cycle output plausibility using pure verification functions.
Writes NO data to storage other than returning the verdict in AgentResult.
"""

from datetime import datetime, timezone
from typing import Any

from edgedash import storage
from edgedash.agents.base import AgentResult
from edgedash.config import Config
from edgedash.verification import Verdict, run_all_checks


class Verifier:
    name: str = "Verifier"

    def __init__(self) -> None:
        self.last_verdict: Verdict | None = None

    def run(
        self,
        config: Config,
        goal: str | None = None,
        stop_conditions: dict[str, Any] | None = None,
        now: datetime | None = None,
        **kwargs: Any,
    ) -> AgentResult:
        db_path = config.db_path
        current_now = now or datetime.now(timezone.utc)

        # 1. Read required data from storage
        listings = storage.get_scored_listings(db_path)
        scores: list[float] = [
            float(r["fit_score"]) for r in listings if r.get("fit_score") is not None
        ]

        facts_list = storage.get_all_extractions(db_path)
        gaps = storage.get_latest_gap_snapshot(db_path)

        state_metrics = storage.get_state_metrics(db_path)
        latest_fetch_at = state_metrics.get("last_fetch_at")

        # 2. Run all verification checks
        verdict = run_all_checks(
            config=config,
            scores=scores,
            facts_list=facts_list,
            gaps=gaps,
            latest_fetch_at=latest_fetch_at,
            now=current_now,
        )
        self.last_verdict = verdict

        status_str = "ok" if verdict.passed else "fail"

        if verdict.passed:
            notes_str = "VERDICT: pass — All verification checks passed"
        else:
            failed_details = []
            for check in verdict.failed_checks:
                failed_details.append(
                    f"{check.name} observed {check.observed} ({check.threshold})"
                )
            notes_str = f"VERDICT: fail — {'; '.join(failed_details)}"

        return AgentResult(
            agent=self.name,
            status=status_str,
            records_touched=len(verdict.all_results),
            notes=notes_str,
        )
