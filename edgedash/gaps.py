import argparse
import sys
from edgedash import storage
from edgedash.config import load_config


def print_gaps_report() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    config = load_config()
    storage.init_db(config.db_path)

    gaps = storage.get_latest_gap_snapshot(config.db_path)
    if not gaps:
        print("\nNo skill gap snapshots found in database. Run 'python run_cycle.py' to generate a report.\n")
        return

    computed_at = gaps[0].get("computed_at", "Unknown")
    run_id = gaps[0].get("run_id", "Unknown")

    print("\n" + "=" * 95)
    print(f" EDGEDASH SKILL GAP ANALYSIS REPORT (Snapshot {run_id} @ {computed_at[:19]})".center(95))
    print("=" * 95)
    print(
        f" {'#':<3} | {'SKILL':<22} | {'BLOCKED':<7} | {'COST':<7} | {'MEAN':<5} | {'TOP':<4} | {'CONFIDENCE':<14} | {'OPPORTUNITY BAR'}"
    )
    print("-" * 95)

    max_cost = max((g.get("opportunity_cost", 0.0) for g in gaps), default=1.0)
    if max_cost <= 0:
        max_cost = 1.0

    # Test if stdout supports Unicode blocks
    use_unicode = True
    try:
        "█".encode(sys.stdout.encoding or "ascii")
    except (UnicodeEncodeError, TypeError):
        use_unicode = False

    fill_char = "█" if use_unicode else "#"
    empty_char = "░" if use_unicode else "-"

    for rank, g in enumerate(gaps, 1):
        skill = str(g.get("skill", ""))[:22]
        blocked = int(g.get("listings_blocked", 0))
        cost = float(g.get("opportunity_cost", 0.0))
        mean_s = float(g.get("mean_score", 0.0))
        top_s = int(g.get("top_score", 0))
        conf = str(g.get("confidence", "normal"))

        # Bar calculation (length 12)
        filled = int(round((cost / max_cost) * 12))
        bar = fill_char * filled + empty_char * (12 - filled)

        conf_display = "LOW CONF" if "low" in conf.lower() else "OK"

        print(
            f" {rank:<3} | {skill:<22} | {blocked:<7} | {cost:<7.2f} | {mean_s:<5.1f} | {top_s:<4} | {conf_display:<14} | {bar}"
        )

        ex_ids = g.get("example_ids", [])
        if ex_ids:
            ids_str = ", ".join(ex_ids[:3])
            nice_str = f" (+{g.get('also_nice_to_have', 0)} nice-to-have)" if g.get("also_nice_to_have", 0) > 0 else ""
            print(f"     └─ Traceable IDs: {ids_str}{nice_str}")

    print("=" * 95 + "\n")


def print_trend_report() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    config = load_config()
    storage.init_db(config.db_path)

    history = storage.get_gap_snapshot_history(config.db_path)
    if not history:
        print("\nNo skill gap snapshots found in database. Run 'python run_cycle.py' first.\n")
        return

    if len(history) == 1:
        single = history[0]
        comp_at = single.get("computed_at", "Unknown")[:19]
        run_id = single.get("run_id", "Unknown")
        print("\n" + "=" * 90)
        print(" SKILL GAP TREND ANALYSIS".center(90))
        print("=" * 90)
        print(f"  * Status           : ONLY 1 SNAPSHOT RECORDED ({comp_at}, Run {run_id})")
        print("  * Trend Capability : At least 2 snapshot runs across multiple days are required to show a trend.")
        print("  * Recommendation   : Run 'python run_cycle.py' over upcoming days to build trend history.")
        print("                       Trend reporting will not fabricate or extrapolate from a single point.")
        print("=" * 90 + "\n")
        return

    earliest_info = history[0]
    latest_info = history[-1]

    earliest_run_id = earliest_info["run_id"]
    latest_run_id = latest_info["run_id"]

    earliest_date_str = earliest_info.get("computed_at", "Unknown")[:19]
    latest_date_str = latest_info.get("computed_at", "Unknown")[:19]

    earliest_list = storage.get_gap_snapshot_by_run_id(config.db_path, earliest_run_id)
    latest_list = storage.get_gap_snapshot_by_run_id(config.db_path, latest_run_id)

    earliest_map = {g["skill"]: g for g in earliest_list}
    latest_map = {g["skill"]: g for g in latest_list}

    top_latest = latest_list[:10]
    top_earliest_skills = [g["skill"] for g in earliest_list[:10]]
    top_latest_skills = {g["skill"] for g in top_latest}

    print("\n" + "=" * 95)
    print(" SKILL GAP TREND REPORT".center(95))
    print("=" * 95)
    print(f"  * Earliest Snapshot : {earliest_date_str} (Run {earliest_run_id})")
    print(f"  * Latest Snapshot   : {latest_date_str} (Run {latest_run_id})")
    print(f"  * Snapshots In DB   : {len(history)} total runs across snapshot timeline")
    print("-" * 95)
    print(
        f" {'#':<3} | {'SKILL':<22} | {'EARLIEST':<8} | {'LATEST':<8} | {'ABS CHANGE':<10} | {'% CHANGE':<10} | {'STATUS'}"
    )
    print("-" * 95)

    # 1. Top 10 skills in current (latest) snapshot
    for rank, g in enumerate(top_latest, 1):
        skill = str(g.get("skill", ""))[:22]
        cost_latest = float(g.get("opportunity_cost", 0.0))

        if skill in earliest_map:
            cost_earliest = float(earliest_map[skill].get("opportunity_cost", 0.0))
            abs_change = cost_latest - cost_earliest
            if cost_earliest > 0:
                pct = (abs_change / cost_earliest) * 100.0
                pct_str = f"{pct:+.1f}%"
            else:
                pct_str = "N/A"

            if skill not in top_earliest_skills:
                status_str = "NEW IN TOP 10"
            elif abs_change > 0:
                status_str = f"RISING (+{abs_change:.2f})"
            elif abs_change < 0:
                status_str = f"FALLING ({abs_change:.2f})"
            else:
                status_str = "STABLE"
        else:
            cost_earliest = 0.0
            abs_change = cost_latest
            pct_str = "N/A"
            status_str = "NEW SKILL"

        print(
            f" {rank:<3} | {skill:<22} | {cost_earliest:<8.2f} | {cost_latest:<8.2f} | {abs_change:<+10.2f} | {pct_str:<10} | {status_str}"
        )

    # 2. Skills that were in earliest top 10 but dropped out of current top 10
    dropped_out = [s for s in top_earliest_skills if s not in top_latest_skills]
    if dropped_out:
        print("-" * 95)
        print(" SKILLS THAT DROPPED OUT OF TOP 10:")
        for s in dropped_out:
            c_earliest = float(earliest_map[s].get("opportunity_cost", 0.0))
            c_latest = float(latest_map.get(s, {}).get("opportunity_cost", 0.0))
            abs_ch = c_latest - c_earliest
            pct_s = f"{((abs_ch / c_earliest) * 100.0):+.1f}%" if c_earliest > 0 else "N/A"
            print(
                f" --  | {s[:22]:<22} | {c_earliest:<8.2f} | {c_latest:<8.2f} | {abs_ch:<+10.2f} | {pct_s:<10} | DROPPED OUT"
            )

    print("=" * 95 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="View skill gap analysis report or trend analysis.")
    parser.add_argument(
        "--trend",
        action="store_true",
        help="Compare opportunity cost trends between earliest and latest snapshots.",
    )
    args = parser.parse_args()

    if args.trend:
        print_trend_report()
    else:
        print_gaps_report()


if __name__ == "__main__":
    main()
