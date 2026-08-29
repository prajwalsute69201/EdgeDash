# EdgeDash

EdgeDash is an autonomous career intelligence agent that tracks live job listings, deduplicates them, and scores skill fit against target roles.

## Diagnostics

Run the read-only database diagnostic tool at any time:

```bash
python -m edgedash.diagnose
```

### Diagnostics Output Example
- **Total Listings & Per-Source Counts**: Breakdown of stored job listings across enabled and legacy sources.
- **Cross-Source Duplicates**: Identifies identical `(title, company)` pairs appearing across different sources.
- **5 Most Recent Listings**: Displays the latest job entries fetched.
- **Data Quality Check**: Reports any records missing `url`, `title`, or `company`.

## Known Limitations

- **Cross-Source Deduplication**: Deduplication is performed deterministically per source using `sha256(source + url)`. Cross-source duplicate listings (identical title and company posted across different platforms) currently represent under 10% of total listings (0.0% in current test dataset) and are tracked via `python -m edgedash.diagnose` without fuzzy matching.
