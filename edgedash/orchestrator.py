import sys
import time
from datetime import datetime, timezone

from edgedash import planning, state, storage
from edgedash.agents.base import Agent, AgentResult
from edgedash.agents.fetcher import Fetcher
from edgedash.agents.gap_analyzer import GapAnalyzer
from edgedash.agents.mock_fetcher import MockFetcher
from edgedash.agents.scorer import Scorer
from edgedash.agents.verifier import Verifier
from edgedash.config import Config


# Agent Registry - Default real Fetcher, configurable via config.use_mock_fetcher
DEFAULT_REGISTRY: list[Agent] = [
    Fetcher(),
    Scorer(),
    GapAnalyzer(),
    Verifier(),
]


def explain_system_state(sys_state: state.SystemState, plan: planning.Plan) -> str:
    lines = []
    lines.append("=" * 80)
    lines.append(" SYSTEM STATE & DECISION EXPLANATION".center(80))
    lines.append("=" * 80)

    task_map = {t.agent_name.lower(): t for t in plan.tasks}

    fetcher_task = task_map.get("fetcher")
    if fetcher_task:
        ts_str = (
            sys_state.last_fetch_at.isoformat()
            if sys_state.last_fetch_at
            else "Never"
        )
        hsf_str = (
            f"{sys_state.hours_since_fetch:.1f}h"
            if sys_state.hours_since_fetch is not None
            else "N/A"
        )
        lines.append(f"  [Fetcher Task] -> Decision: [{fetcher_task.action.upper()}]")
        lines.append(f"    • last_fetch_at     : {ts_str}")
        lines.append(f"    • hours_since_fetch : {hsf_str}")
        lines.append(f"    • Decision Reason   : {fetcher_task.reason}")
        lines.append("")

    scorer_task = task_map.get("scorer")
    if scorer_task:
        lines.append(f"  [Scorer Task] -> Decision: [{scorer_task.action.upper()}]")
        lines.append(f"    • unscored_count    : {sys_state.unscored_count}")
        lines.append(f"    • Decision Reason   : {scorer_task.reason}")
        lines.append("")

    gap_task = task_map.get("gapanalyzer")
    if gap_task:
        ts_str = (
            sys_state.gaps_computed_at.isoformat()
            if sys_state.gaps_computed_at
            else "Never"
        )
        lines.append(f"  [GapAnalyzer Task] -> Decision: [{gap_task.action.upper()}]")
        lines.append(f"    • gaps_computed_at  : {ts_str}")
        lines.append(f"    • gaps_stale        : {sys_state.gaps_stale}")
        lines.append(f"    • Decision Reason   : {gap_task.reason}")
        lines.append("")

    verifier_task = task_map.get("verifier")
    if verifier_task:
        lines.append(f"  [Verifier Task] -> Decision: [{verifier_task.action.upper()}]")
        lines.append(f"    • Decision Reason   : {verifier_task.reason}")
        lines.append("")

    cycle_ts_str = (
        sys_state.last_cycle_at.isoformat()
        if sys_state.last_cycle_at
        else "Never"
    )
    lines.append("  [System Context]")
    lines.append(f"    • last_cycle_at     : {cycle_ts_str}")
    lines.append(f"    • last_cycle_verdict: {sys_state.last_cycle_verdict or 'None'}")
    lines.append("=" * 80)

    return "\n".join(lines)


def run_cycle(
    config: Config,
    registry: list[Agent] | None = None,
    now: datetime | None = None,
    dry_run: bool = False,
    force_agents: list[str] | None = None,
    explain: bool = False,
) -> list[AgentResult]:
    # Ensure stdout handles UTF-8 on Windows terminals
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    # 1. Init database & resolve agents
    storage.init_db(config.db_path)

    if registry is None:
        fetcher: Agent = MockFetcher() if config.use_mock_fetcher else Fetcher()
        agents = [
            fetcher,
            Scorer(),
            GapAnalyzer(),
            Verifier(),
        ]
    else:
        agents = registry

    agent_map: dict[str, Agent] = {a.name: a for a in agents}

    current_now = now or datetime.now(timezone.utc)
    cycle_start = datetime.now(timezone.utc)

    # 2. Read state & build plan (Rules 28 & 31)
    sys_state = state.read_state(config, current_now)
    plan = planning.build_plan(sys_state, config)

    # Handle --force overrides
    forced_applied: list[str] = []
    if force_agents:
        for forced_name in force_agents:
            for task in plan.tasks:
                if task.agent_name.lower() == forced_name.strip().lower():
                    if task.action == "skip":
                        task.action = "run"
                        task.reason = "forced by operator"
                        if task.agent_name not in forced_applied:
                            forced_applied.append(task.agent_name)
                    elif task.agent_name not in forced_applied:
                        forced_applied.append(task.agent_name)
                    break

    # Handle --explain
    if explain:
        print("\n" + explain_system_state(sys_state, plan))

    # Print warning if plan was manually overridden by --force
    if forced_applied:
        print(
            f"\n[WARNING] Plan manually overridden by operator: forced execution for agent(s): {', '.join(forced_applied)}"
        )

    # 3. Print rendered plan BEFORE executing anything (Rule 31)
    print("\n" + plan.render() + "\n")

    if dry_run:
        print("[DRY RUN] Plan generated successfully. Exiting without executing tasks.")
        return []

    results: list[AgentResult] = []
    agent_durations: dict[str, float] = {}
    ran_agents: list[str] = []
    skipped_info: list[str] = []
    has_failure = False

    all_skipped = all(t.action == "skip" for t in plan.tasks)

    if all_skipped:
        # Rule 33 / Rule 28: skipping when no work is a SUCCESSFUL outcome ("nothing_to_do")
        cycle_outcome = "nothing_to_do"
        for task in plan.tasks:
            skipped_info.append(f"{task.agent_name} ({task.reason})")
            results.append(
                AgentResult(
                    agent=task.agent_name,
                    status="skipped",
                    records_touched=0,
                    notes=task.reason,
                )
            )
        print("Cycle Outcome: nothing_to_do (System state up to date).\n")
        retry_count = 0
        verdict_status = "pass"
        failed_checks_notes = "none"
    else:
        print("[Executing Orchestration Plan]")
        verifier_agent: Verifier = agent_map.get("Verifier") if isinstance(agent_map.get("Verifier"), Verifier) else Verifier()

        for task in plan.tasks:
            if task.action == "skip":
                skipped_info.append(f"{task.agent_name} ({task.reason})")
                res = AgentResult(
                    agent=task.agent_name,
                    status="skipped",
                    records_touched=0,
                    notes=task.reason,
                )
                results.append(res)
                print(f"  > [{task.agent_name:<11}] SKIPPED -> {task.reason}")
                continue

            target_agent = agent_map.get(task.agent_name)
            if not target_agent:
                has_failure = True
                skipped_info.append(f"{task.agent_name} (Not found in registry)")
                res = AgentResult(
                    agent=task.agent_name,
                    status="failed",
                    records_touched=0,
                    notes="Agent not found in registry",
                )
                results.append(res)
                print(f"  > [{task.agent_name:<11}] FAILED -> Agent not found in registry")
                continue

            task_start = datetime.now(timezone.utc)
            print(f"  > [{task.agent_name:<11}] Running... ", end="", flush=True)

            # Rule 32: Try/except per task. Failure logs and continues cycle with outcome "partial"
            try:
                res = target_agent.run(
                    config,
                    goal=task.goal,
                    stop_conditions=task.stop_conditions,
                )

                task_end = datetime.now(timezone.utc)
                duration = round((task_end - task_start).total_seconds(), 2)
                agent_durations[task.agent_name] = duration
                ran_agents.append(task.agent_name)

                status_flag = "OK" if res.status == "ok" else res.status.upper()
                if res.status != "ok":
                    has_failure = True

                print(
                    f"\r  > [{task.agent_name:<11}] Finished ({status_flag}) [{duration}s] -> {res.notes}"
                )
                results.append(res)

            except Exception as err:
                task_end = datetime.now(timezone.utc)
                duration = round((task_end - task_start).total_seconds(), 2)
                agent_durations[task.agent_name] = duration
                ran_agents.append(task.agent_name)
                has_failure = True

                print(f"\r  > [{task.agent_name:<11}] FAILED [{duration}s] -> {err}")
                res = AgentResult(
                    agent=task.agent_name,
                    status="failed",
                    records_touched=0,
                    notes=str(err),
                )
                results.append(res)

            time.sleep(0.05)

        # Run Verifier after Scorer and GapAnalyzer (Rule 36)
        print("  > [Verifier   ] Running... ", end="", flush=True)
        v_start = datetime.now(timezone.utc)
        ver_res = verifier_agent.run(config, now=current_now)
        v_dur = round((datetime.now(timezone.utc) - v_start).total_seconds(), 2)
        agent_durations["Verifier"] = v_dur
        ran_agents.append("Verifier")
        results.append(ver_res)
        print(f"\r  > [Verifier   ] Finished ({ver_res.status.upper()}) [{v_dur}s] -> {ver_res.notes}")

        # Rule 36: Bounded Verification Retry Logic (Max 1 retry per cycle)
        retry_count = 0
        last_verdict = verifier_agent.last_verdict

        if last_verdict and not last_verdict.passed:
            retry_count = 1
            failed_names = [c.name for c in last_verdict.failed_checks]

            # Determine failing agent to retry with adjusted context
            if "score_spread" in failed_names or "extraction_sanity" in failed_names:
                failing_agent_name = "Scorer"
            elif "gap_sample_size" in failed_names:
                failing_agent_name = "GapAnalyzer"
            elif "freshness" in failed_names:
                failing_agent_name = "Fetcher"
            else:
                failing_agent_name = "Scorer"

            print(
                f"\n[Verification Failure] Checks failed: {', '.join(failed_names)}. "
                f"Retrying failing agent '{failing_agent_name}' with adjusted context (Retry 1/1)..."
            )

            # Re-run ONLY the failing agent with adjusted context
            if failing_agent_name == "Scorer":
                storage.clear_all_scores(config.db_path)
                scorer_agent = agent_map.get("Scorer") or Scorer()
                t0 = datetime.now(timezone.utc)
                retry_res = scorer_agent.run(config, widen_distribution=True)
                agent_durations["Scorer_retry"] = round((datetime.now(timezone.utc) - t0).total_seconds(), 2)
                print(f"  > [Scorer (Retry)] Finished ({retry_res.status.upper()}) -> {retry_res.notes}")

                # Update GapAnalyzer after rescoring so gaps match new score distribution
                gap_agent = agent_map.get("GapAnalyzer") or GapAnalyzer()
                gap_agent.run(config)

            elif failing_agent_name in agent_map:
                agent_map[failing_agent_name].run(config)

            # Re-verify cycle after single retry
            print("  > [Verifier (Re-check)] Running verification again...")
            ver_res = verifier_agent.run(config, now=current_now)
            # Replace earlier Verifier result in results
            results = [r for r in results if r.agent != "Verifier"]
            results.append(ver_res)
            last_verdict = verifier_agent.last_verdict

        # Final verdict resolution per Rule 36
        if last_verdict:
            verdict_status = "pass" if last_verdict.passed else "fail"
            if last_verdict.passed:
                failed_checks_notes = "none"
                cycle_outcome = "partial" if has_failure else "complete"
            else:
                # Rule 36: If verification fails after 1 retry, mark cycle "degraded" and STOP
                cycle_outcome = "degraded"
                failed_details = []
                for check in last_verdict.failed_checks:
                    failed_details.append(
                        f"{check.name}: observed {check.observed} (threshold {check.threshold})"
                    )
                failed_checks_notes = "; ".join(failed_details)
                print(f"\n[Verification Final Verdict] DEGRADED — {failed_checks_notes}")
        else:
            verdict_status = "pass" if not has_failure else "fail"
            failed_checks_notes = "none"
            cycle_outcome = "partial" if has_failure else "complete"


    # Rule 33 & 37: Write exactly one summary row for the cycle with verdict details
    cycle_finish = datetime.now(timezone.utc)
    total_records = sum(r.records_touched for r in results)

    durations_str = ", ".join(f"{k}:{v}s" for k, v in agent_durations.items()) or "none"
    ran_str = ", ".join(ran_agents) or "none"
    skipped_str = "; ".join(skipped_info) or "none"
    forced_str = ", ".join(forced_applied) if forced_applied else "none"

    cycle_summary_notes = (
        f"outcome={cycle_outcome} | verdict={verdict_status} | failed_checks=[{failed_checks_notes}] | "
        f"retries={retry_count} | ran=[{ran_str}] | skipped=[{skipped_str}] | "
        f"durations=[{durations_str}] | forced=[{forced_str}]"
    )

    storage.log_cycle(
        db_path=config.db_path,
        agent="Orchestrator",
        started_at=cycle_start.isoformat(),
        finished_at=cycle_finish.isoformat(),
        records_touched=total_records,
        status=cycle_outcome,
        notes=cycle_summary_notes,
    )

    # Print Cycle Summary Table
    print("\n" + "=" * 80)
    print(f" CYCLE SUMMARY ({cycle_outcome.upper()})".center(80))
    print("=" * 80)
    print(f" {'TASK':<15} | {'STATUS':<9} | {'TOUCHED':<8} | {'NOTES'}")
    print("-" * 80)
    for r in results:
        status_disp = r.status.upper()
        print(f" {r.agent:<15} | {status_disp:<9} | {r.records_touched:<8} | {r.notes}")
    print("=" * 80 + "\n")

    return results

