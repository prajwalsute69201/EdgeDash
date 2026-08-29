import argparse
from edgedash import storage
from edgedash.agents.extractor import extract
from edgedash.config import load_config
from edgedash.scoring import score_listing


def main() -> None:
    parser = argparse.ArgumentParser(description="Debug listing scoring and facts extraction.")
    parser.add_argument("--limit", type=int, default=5, help="Number of listings to inspect.")
    parser.add_argument("--all", action="store_true", help="Inspect all listings instead of unscored only.")
    args = parser.parse_args()

    config = load_config("config.yaml")
    storage.init_db(config.db_path)

    if args.all:
        listings = storage.get_listings(config.db_path, limit=args.limit)
    else:
        listings = storage.get_unscored_listings(config.db_path, limit=args.limit)
        if not listings:
            print("No unscored listings found. Inspecting recent listings instead...")
            listings = storage.get_listings(config.db_path, limit=args.limit)

    if not listings:
        print("No listings found in database.")
        return

    print("=" * 80)
    print(f" DEBUG SCORING REPORT ({len(listings)} listings)".center(80))
    print("=" * 80)

    for idx, listing in enumerate(listings, 1):
        title = listing.get("title", "Untitled")
        company = listing.get("company", "Unknown")
        location = listing.get("location", "Unstated")
        posted = listing.get("posted_at", "Unknown")

        print(f"\n[{idx}] {title} @ {company} ({location})")
        print(f"    URL: {listing.get('url')}")
        print(f"    Posted At: {posted}")

        try:
            facts = extract(listing, config=config)
            print("    Extracted Facts:")
            print(f"      - Required Skills : {facts.get('required_skills')}")
            print(f"      - Nice To Have    : {facts.get('nice_to_have')}")
            print(f"      - Seniority       : {facts.get('seniority')}")
            print(f"      - Years Required  : {facts.get('years_required')}")
            print(f"      - Remote OK       : {facts.get('remote_ok')}")

            res = score_listing(listing, facts, config)
            print(f"    Score  : {res['score']} / 100")
            print(f"    Reason : {res['reason']}")
            print("    Components:")
            for k, v in res["components"].items():
                print(f"      - {k:<15}: {v}")

        except Exception as err:
            print(f"    ERROR: {err}")

    print("\n" + "=" * 80)


if __name__ == "__main__":
    main()
