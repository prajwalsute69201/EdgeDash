from datetime import datetime, timezone
from typing import Any

from edgedash import storage
from edgedash.agents.base import AgentResult
from edgedash.config import Config
from edgedash.sources import SOURCES


class Fetcher:
    name: str = "Fetcher"

    def run(
        self,
        config: Config,
        goal: str | None = None,
        stop_conditions: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> AgentResult:
        enabled_sources = config.sources if config.sources else ["arbeitnow"]
        all_rows: list[dict[str, Any]] = []
        total_inserted = 0
        source_notes: list[str] = []
        any_success = False

        for src_name in enabled_sources:
            start_time = datetime.now(timezone.utc).isoformat()
            try:
                if src_name not in SOURCES:
                    raise ValueError(f"Unknown source '{src_name}' in SOURCES registry")

                source_cls = SOURCES[src_name]
                source_inst = source_cls()
                rows = source_inst.fetch(config)

                now_str = datetime.now(timezone.utc).isoformat()
                for row in rows:
                    source_str = str(row.get("source") or src_name)
                    url_str = str(row.get("url") or "")
                    row["id"] = storage.generate_listing_id(source_str, url_str)
                    if not row.get("fetched_at"):
                        row["fetched_at"] = now_str

                new_inserted = storage.upsert_listings(config.db_path, rows)
                total_inserted += new_inserted
                all_rows.extend(rows)

                end_time = datetime.now(timezone.utc).isoformat()
                storage.log_cycle(
                    db_path=config.db_path,
                    agent=src_name,
                    started_at=start_time,
                    finished_at=end_time,
                    records_touched=len(rows),
                    status="ok",
                    notes=f"Fetched {len(rows)} rows",
                )

                source_notes.append(f"{src_name}: {len(rows)} rows ({new_inserted} new)")
                any_success = True

            except Exception as err:
                end_time = datetime.now(timezone.utc).isoformat()
                storage.log_cycle(
                    db_path=config.db_path,
                    agent=src_name,
                    started_at=start_time,
                    finished_at=end_time,
                    records_touched=0,
                    status="failed",
                    notes=str(err),
                )
                print(f"[Fetcher] WARNING: Source '{src_name}' failed: {err}")
                source_notes.append(f"{src_name}: FAILED ({err})")
                continue

        notes_str = " | ".join(source_notes) if source_notes else "No sources configured"
        status_str = "ok" if (any_success or not enabled_sources) else "failed"

        return AgentResult(
            agent=self.name,
            status=status_str,
            records_touched=total_inserted,
            notes=notes_str,
        )
