import argparse
import sys
from edgedash import storage
from edgedash.config import load_config


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Manual re-scoring escape hatch. Clears listing fit_score and fit_reason to trigger re-scoring."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--all",
        action="store_true",
        help="Clear every fit_score so the next cycle re-scores all listings.",
    )
    group.add_argument(
        "--id",
        type=str,
        dest="listing_id",
        help="Clear fit_score for a specific listing ID.",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip confirmation prompt when using --all.",
    )

    args = parser.parse_args()
    config = load_config()

    if args.all:
        if not args.yes:
            try:
                response = input("Are you sure you want to clear ALL listing scores? [y/N]: ").strip().lower()
            except (KeyboardInterrupt, EOFError):
                print("\nOperation cancelled.")
                sys.exit(1)

            if response not in ("y", "yes"):
                print("Operation cancelled. No scores were cleared.")
                sys.exit(0)

        cleared = storage.clear_all_scores(config.db_path)
        print(f"\nCleared {cleared} listing score(s).")
        print("Note: Extraction cache remains untouched (0 API calls needed for re-scoring).")
        print("Run 'python run_cycle.py' to re-score listings.\n")

    elif args.listing_id:
        cleared = storage.clear_listing_score(config.db_path, args.listing_id)
        if cleared > 0:
            print(f"\nCleared score for listing '{args.listing_id}'.")
            print("Run 'python run_cycle.py' to re-score listings.\n")
        else:
            print(f"\nNo listing with ID '{args.listing_id}' was cleared (it may not exist or was already unscored).\n")


if __name__ == "__main__":
    main()
