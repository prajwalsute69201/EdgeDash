from dataclasses import dataclass
from typing import Any

from edgedash.config import Config
from edgedash.state import SystemState


@dataclass
class Task:
    agent_name: str
    action: str  # "run" | "skip"
    goal: str
    stop_conditions: dict[str, Any]
    reason: str


@dataclass
class Plan:
    tasks: list[Task]

    def render(self) -> str:
        lines = []
        lines.append("=" * 80)
        lines.append(" EDGEDASH ORCHESTRATION PLAN".center(80))
        lines.append("=" * 80)
        for task in self.tasks:
            flag = "[RUN] " if task.action == "run" else "[SKIP]"
            stop_str = ", ".join(f"{k}={v}" for k, v in task.stop_conditions.items())
            lines.append(f"  {flag:<7} {task.agent_name:<11} │ Goal  : {task.goal}")
            lines.append(f"          {' ':<11} │ Stop  : {stop_str}")
            lines.append(f"          {' ':<11} │ Reason: {task.reason}")
            lines.append("  " + "-" * 76)
        lines.append("=" * 80)
        return "\n".join(lines)


def build_plan(state: SystemState, config: Config) -> Plan:
    fetch_interval_hours = float(getattr(config, "fetch_interval_hours", 6.0))
    max_fetch_pages = int(getattr(config, "max_fetch_pages", 5))
    max_fetch_listings = int(getattr(config, "max_fetch_listings", 100))
    score_batch_size = int(getattr(config, "score_batch_size", 50))
    max_score_seconds = int(getattr(config, "max_score_seconds", 60))
    max_analyse_seconds = int(getattr(config, "max_analyse_seconds", 30))

    tasks: list[Task] = []

    # 1. Fetcher Task
    fetch_needed = (
        state.hours_since_fetch is None or state.hours_since_fetch >= fetch_interval_hours
    )
    if fetch_needed:
        if state.hours_since_fetch is None:
            fetch_reason = "never_fetched"
        else:
            fetch_reason = f"hours_since_fetch={state.hours_since_fetch:.1f} >= {fetch_interval_hours:.1f}h"
        fetch_action = "run"
    else:
        fetch_reason = f"skipped: hours_since_fetch={state.hours_since_fetch:.1f} < {fetch_interval_hours:.1f}h"
        fetch_action = "skip"

    tasks.append(
        Task(
            agent_name="Fetcher",
            action=fetch_action,
            goal="Fetch new job listings from remote job boards",
            stop_conditions={"max_pages": max_fetch_pages, "max_listings": max_fetch_listings},
            reason=fetch_reason,
        )
    )

    # 2. Scorer Task
    score_needed = state.unscored_count > 0
    if score_needed:
        score_action = "run"
        score_reason = f"unscored_count={state.unscored_count}"
    else:
        score_action = "skip"
        score_reason = "skipped: unscored_count=0"

    tasks.append(
        Task(
            agent_name="Scorer",
            action=score_action,
            goal="Extract facts & compute fit scores for unscored listings",
            stop_conditions={"max_items": score_batch_size, "max_seconds": max_score_seconds},
            reason=score_reason,
        )
    )

    # 3. GapAnalyzer Task
    analyse_needed = state.gaps_stale or state.gaps_computed_at is None
    if analyse_needed:
        analyse_action = "run"
        if state.gaps_computed_at is None:
            analyse_reason = "gaps_computed_at=Never"
        else:
            analyse_reason = "gaps_stale=True (new scores detected)"
    else:
        analyse_action = "skip"
        analyse_reason = "skipped: gaps_stale=False"

    tasks.append(
        Task(
            agent_name="GapAnalyzer",
            action=analyse_action,
            goal="Compute fit-weighted skill gap snapshot",
            stop_conditions={"max_seconds": max_analyse_seconds},
            reason=analyse_reason,
        )
    )

    return Plan(tasks=tasks)



