from edgedash import storage
from edgedash.config import load_config


def main() -> None:
    config = load_config()
    storage.init_db(config.db_path)
    diag = storage.get_diagnostics(config.db_path)

    total = diag["total_listings"]
    counts_per_source = diag["counts_per_source"]
    dup_groups = diag["cross_source_dup_groups"]
    dup_listings = diag["cross_source_dup_listings"]
    recent = diag["recent_listings"]
    invalid = diag["invalid_listings"]

    print("\n" + "=" * 70)
    print(" EDGEDASH DATABASE DIAGNOSTICS".center(70))
    print("=" * 70)

    # 1. Total listings and count per source
    print("\n[Listings Overview]")
    print(f"  * Total Listings : {total}")
    if counts_per_source:
        print("  * Count per Source:")
        for src, cnt in counts_per_source.items():
            print(f"    - {src:<15}: {cnt}")
    else:
        print("  * Count per Source : None")

    # 2. Cross-source duplicates
    pct = (dup_listings / total * 100) if total > 0 else 0.0
    print("\n[Cross-Source Duplicates]")
    print(f"  * Duplicate (Title, Company) Pairs Across Sources : {dup_groups}")
    print(f"  * Listings Involved in Cross-Source Duplicates   : {dup_listings} ({pct:.1f}% of total)")

    # 3. 5 Most Recent Listings
    print("\n[5 Most Recent Listings]")
    if recent:
        for idx, item in enumerate(recent, start=1):
            print(f"  {idx}. [{item['source']}] {item['title']} @ {item['company']}")
    else:
        print("  * No listings in database.")

    # 4. Data Quality Check
    print("\n[Data Quality Check]")
    if invalid:
        print(f"  * WARNING: {len(invalid)} listings have NULL or empty url, title, or company:")
        for item in invalid:
            print(f"    - ID: {item['id']} | Source: {item['source']} | Title: '{item['title']}' | Company: '{item['company']}' | URL: '{item['url']}'")
    else:
        print("  * Clean Data Quality: 0 listings with NULL or empty url, title, or company.")

    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
