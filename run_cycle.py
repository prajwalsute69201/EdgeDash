import argparse

from edgedash.config import load_config
from edgedash.orchestrator import run_cycle


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an Edgedash orchestration cycle.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Read state, build plan, print it, and exit without executing.",
    )
    parser.add_argument(
        "--force",
        action="append",
        dest="force_agents",
        help="Force the named agent to run even if state says to skip (repeatable).",
    )
    parser.add_argument(
        "--explain",
        action="store_true",
        help="Print full SystemState and timestamps next to decisions.",
    )

    args = parser.parse_args()

    config = load_config("config.yaml")
    run_cycle(
        config,
        dry_run=args.dry_run,
        force_agents=args.force_agents,
        explain=args.explain,
    )


if __name__ == "__main__":
    main()
