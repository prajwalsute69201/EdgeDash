import hashlib
import json
import logging
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

logger = logging.getLogger("edgedash.storage")

try:
    import psycopg2
    import psycopg2.extras

    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False

try:
    import psycopg
    import psycopg.rows

    HAS_PSYCOPG3 = True
except ImportError:
    HAS_PSYCOPG3 = False


def get_backend(db_path: str = "edgedash.db") -> str:
    """Return active database backend ('postgres' or 'sqlite')."""
    if os.environ.get("DATABASE_URL") and (db_path == "edgedash.db" or not db_path.endswith(".db")):
        return "postgres"
    return "sqlite"


def log_active_backend() -> None:
    """Log active database backend at startup."""
    backend = get_backend()
    if backend == "postgres":
        msg = "EdgeDash storage: Active backend is POSTGRES (DATABASE_URL configured)"
        logger.info(msg)
        print(msg, file=sys.stderr)
    else:
        msg = "EdgeDash storage: Active backend is SQLITE (local file fallback)"
        logger.info(msg)
        print(msg, file=sys.stderr)


# Log active backend on module import
log_active_backend()


def _val(row: Any, index: int = 0) -> Any:
    """Helper to retrieve a column value by index from sqlite3.Row, tuple, or dict."""
    if row is None:
        return None
    if isinstance(row, dict):
        values = list(row.values())
        return values[index] if index < len(values) else None
    return row[index]


class DB:
    """Database context manager providing a unified interface for SQLite and Postgres."""

    def __init__(self, db_path: str = "edgedash.db"):
        self.db_path = db_path
        self.backend = get_backend(db_path)
        self.conn = None
        self.cursor = None

    def __enter__(self):
        if self.backend == "postgres":
            db_url = os.environ.get("DATABASE_URL")
            if not db_url:
                raise ValueError("DATABASE_URL environment variable is missing")
            if HAS_PSYCOPG2:
                self.conn = psycopg2.connect(db_url)
                self.cursor = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            elif HAS_PSYCOPG3:
                self.conn = psycopg.connect(db_url, row_factory=psycopg.rows.dict_row)
                self.cursor = self.conn.cursor()
            else:
                raise ImportError(
                    "PostgreSQL driver (psycopg2 or psycopg) is required when DATABASE_URL is set."
                )
        else:
            self.conn = sqlite3.connect(self.db_path)
            self.conn.row_factory = sqlite3.Row
            self.cursor = self.conn.cursor()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            if self.conn:
                self.conn.rollback()
        else:
            if self.conn:
                self.conn.commit()
        if self.cursor:
            self.cursor.close()
        if self.conn:
            self.conn.close()

    def execute(self, sql: str, params: tuple | list = ()) -> Any:
        prepared_sql = self._prepare_sql(sql)
        self.cursor.execute(prepared_sql, params)
        return self.cursor

    def _prepare_sql(self, sql: str) -> str:
        if self.backend != "postgres":
            return sql
        pg_sql = sql.replace("?", "%s")
        pg_sql = pg_sql.replace(", rowid DESC", "")
        pg_sql = pg_sql.replace(", ROWID DESC", "")
        return pg_sql


def init_db(db_path: str = "edgedash.db") -> None:
    backend = get_backend()
    with DB(db_path) as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS listings (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                company TEXT NOT NULL,
                location TEXT NOT NULL,
                url TEXT NOT NULL,
                description TEXT NOT NULL,
                source TEXT NOT NULL,
                posted_at TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                fit_score INTEGER NULL,
                fit_reason TEXT NULL
            );
            """
        )

        if backend == "postgres":
            try:
                db.execute(
                    """
                    SELECT column_name FROM information_schema.columns
                    WHERE table_name = 'skill_gaps'
                    """
                )
                cols = [r["column_name"] for r in db.cursor.fetchall()]
                if cols and "run_id" not in cols:
                    db.execute("DROP TABLE skill_gaps CASCADE")
            except Exception:
                pass
        else:
            try:
                db.execute("SELECT * FROM skill_gaps LIMIT 0")
                cols = [col[0] for col in db.cursor.description] if db.cursor.description else []
                if cols and "run_id" not in cols:
                    db.execute("DROP TABLE skill_gaps")
            except Exception:
                pass

        if backend == "postgres":
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS skill_gaps (
                    id SERIAL PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    computed_at TEXT NOT NULL,
                    skill TEXT NOT NULL,
                    listings_blocked INTEGER NOT NULL,
                    opportunity_cost DOUBLE PRECISION NOT NULL,
                    mean_score DOUBLE PRECISION NOT NULL,
                    top_score INTEGER NOT NULL,
                    example_ids TEXT NOT NULL,
                    also_nice_to_have INTEGER NOT NULL,
                    confidence TEXT NOT NULL
                );
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS cycle_log (
                    id SERIAL PRIMARY KEY,
                    agent TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL,
                    records_touched INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    notes TEXT NULL
                );
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS extractions (
                    hash TEXT PRIMARY KEY,
                    required_skills TEXT NOT NULL,
                    nice_to_have TEXT NOT NULL,
                    seniority TEXT NOT NULL,
                    years_required INTEGER NULL,
                    remote_ok INTEGER NULL,
                    extracted_at TEXT NOT NULL
                );
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS query_log (
                    id SERIAL PRIMARY KEY,
                    question TEXT NOT NULL,
                    tool_chosen TEXT NULL,
                    params TEXT NULL,
                    answerable INTEGER NOT NULL,
                    duration_ms DOUBLE PRECISION NOT NULL,
                    asked_at TEXT NOT NULL
                );
                """
            )
        else:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS skill_gaps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    computed_at TEXT NOT NULL,
                    skill TEXT NOT NULL,
                    listings_blocked INTEGER NOT NULL,
                    opportunity_cost REAL NOT NULL,
                    mean_score REAL NOT NULL,
                    top_score INTEGER NOT NULL,
                    example_ids TEXT NOT NULL,
                    also_nice_to_have INTEGER NOT NULL,
                    confidence TEXT NOT NULL
                );
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS cycle_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL,
                    records_touched INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    notes TEXT NULL
                );
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS extractions (
                    hash TEXT PRIMARY KEY,
                    required_skills TEXT NOT NULL,
                    nice_to_have TEXT NOT NULL,
                    seniority TEXT NOT NULL,
                    years_required INTEGER NULL,
                    remote_ok INTEGER NULL,
                    extracted_at TEXT NOT NULL
                );
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS query_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    question TEXT NOT NULL,
                    tool_chosen TEXT NULL,
                    params TEXT NULL,
                    answerable INTEGER NOT NULL,
                    duration_ms REAL NOT NULL,
                    asked_at TEXT NOT NULL
                );
                """
            )


def generate_listing_id(source: str, url: str) -> str:
    raw = f"{source.strip().lower()}:{url.strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def upsert_listings(db_path: str, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0

    backend = get_backend()
    inserted_count = 0
    with DB(db_path) as db:
        for row in rows:
            source = str(row.get("source", ""))
            url = str(row.get("url", ""))
            listing_id = str(row.get("id") or generate_listing_id(source, url))

            if backend == "postgres":
                db.execute(
                    """
                    INSERT INTO listings (
                        id, title, company, location, url, description,
                        source, posted_at, fetched_at, fit_score, fit_reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        listing_id,
                        str(row.get("title", "")),
                        str(row.get("company", "")),
                        str(row.get("location", "")),
                        url,
                        str(row.get("description", "")),
                        source,
                        str(row.get("posted_at", "")),
                        str(row.get("fetched_at", "")),
                        row.get("fit_score"),
                        row.get("fit_reason"),
                    ),
                )
            else:
                db.execute(
                    """
                    INSERT OR IGNORE INTO listings (
                        id, title, company, location, url, description,
                        source, posted_at, fetched_at, fit_score, fit_reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        listing_id,
                        str(row.get("title", "")),
                        str(row.get("company", "")),
                        str(row.get("location", "")),
                        url,
                        str(row.get("description", "")),
                        source,
                        str(row.get("posted_at", "")),
                        str(row.get("fetched_at", "")),
                        row.get("fit_score"),
                        row.get("fit_reason"),
                    ),
                )
            if db.cursor.rowcount > 0:
                inserted_count += 1
    return inserted_count


def count_unscored(db_path: str) -> int:
    with DB(db_path) as db:
        db.execute("SELECT COUNT(*) FROM listings WHERE fit_score IS NULL")
        row = db.cursor.fetchone()
        return int(_val(row) or 0)


def get_unscored_listings(db_path: str, limit: int = 50) -> list[dict[str, Any]]:
    with DB(db_path) as db:
        db.execute(
            """
            SELECT * FROM listings
            WHERE fit_score IS NULL
            ORDER BY fetched_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(r) for r in db.cursor.fetchall()]


def update_listing_score(
    db_path: str, listing_id: str, fit_score: int, fit_reason: str
) -> None:
    with DB(db_path) as db:
        db.execute(
            """
            UPDATE listings
            SET fit_score = ?, fit_reason = ?
            WHERE id = ?
            """,
            (fit_score, fit_reason, listing_id),
        )


def last_fetch_time(db_path: str) -> str | None:
    with DB(db_path) as db:
        db.execute("SELECT MAX(fetched_at) FROM listings")
        row = db.cursor.fetchone()
        val = _val(row)
        return str(val) if val is not None else None


def log_cycle(
    db_path: str,
    agent: str,
    started_at: str,
    finished_at: str,
    records_touched: int,
    status: str,
    notes: str = "",
) -> int:
    backend = get_backend()
    with DB(db_path) as db:
        if backend == "postgres":
            db.execute(
                """
                INSERT INTO cycle_log (agent, started_at, finished_at, records_touched, status, notes)
                VALUES (?, ?, ?, ?, ?, ?)
                RETURNING id
                """,
                (agent, started_at, finished_at, records_touched, status, notes),
            )
            row = db.cursor.fetchone()
            return int(_val(row) or 0)
        else:
            db.execute(
                """
                INSERT INTO cycle_log (agent, started_at, finished_at, records_touched, status, notes)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (agent, started_at, finished_at, records_touched, status, notes),
            )
            return int(db.cursor.lastrowid or 0)


def get_listings(db_path: str, limit: int = 50, min_score: int = 0) -> list[dict[str, Any]]:
    with DB(db_path) as db:
        if min_score > 0:
            db.execute(
                """
                SELECT * FROM listings
                WHERE fit_score >= ?
                ORDER BY fetched_at DESC
                LIMIT ?
                """,
                (min_score, limit),
            )
        else:
            db.execute(
                """
                SELECT * FROM listings
                ORDER BY fetched_at DESC
                LIMIT ?
                """,
                (limit,),
            )
        return [dict(r) for r in db.cursor.fetchall()]


def get_diagnostics(db_path: str = "edgedash.db") -> dict[str, Any]:
    with DB(db_path) as db:
        db.execute("SELECT COUNT(*) FROM listings")
        row = db.cursor.fetchone()
        total_listings = int(_val(row) or 0)

        db.execute(
            """
            SELECT source, COUNT(*) as count
            FROM listings
            GROUP BY source
            ORDER BY count DESC
            """
        )
        counts_per_source = {str(r["source"]): int(r["count"]) for r in db.cursor.fetchall()}

        db.execute(
            """
            SELECT LOWER(TRIM(title)) as norm_title,
                   LOWER(TRIM(company)) as norm_company,
                   COUNT(DISTINCT source) as num_sources,
                   COUNT(*) as total_count
            FROM listings
            WHERE title IS NOT NULL AND TRIM(title) != ''
              AND company IS NOT NULL AND TRIM(company) != ''
            GROUP BY LOWER(TRIM(title)), LOWER(TRIM(company))
            HAVING COUNT(DISTINCT source) > 1
            """
        )
        dup_rows = [dict(r) for r in db.cursor.fetchall()]
        cross_source_dup_groups = len(dup_rows)
        cross_source_dup_listings = sum(int(r["total_count"]) for r in dup_rows)

        db.execute(
            """
            SELECT source, title, company, fetched_at
            FROM listings
            ORDER BY fetched_at DESC, rowid DESC
            LIMIT 5
            """
        )
        recent_listings = [dict(r) for r in db.cursor.fetchall()]

        db.execute(
            """
            SELECT id, source, title, company, url
            FROM listings
            WHERE title IS NULL OR TRIM(title) = ''
               OR company IS NULL OR TRIM(company) = ''
               OR url IS NULL OR TRIM(url) = ''
            """
        )
        invalid_listings = [dict(r) for r in db.cursor.fetchall()]

        return {
            "total_listings": total_listings,
            "counts_per_source": counts_per_source,
            "cross_source_dup_groups": cross_source_dup_groups,
            "cross_source_dup_listings": cross_source_dup_listings,
            "recent_listings": recent_listings,
            "invalid_listings": invalid_listings,
        }


def get_extraction(db_path: str, description_hash: str) -> dict[str, Any] | None:
    init_db(db_path)
    with DB(db_path) as db:
        db.execute(
            """
            SELECT required_skills, nice_to_have, seniority, years_required, remote_ok
            FROM extractions
            WHERE hash = ?
            """,
            (description_hash,),
        )
        row = db.cursor.fetchone()
        if not row:
            return None

        required_skills = json.loads(row["required_skills"])
        nice_to_have = json.loads(row["nice_to_have"])
        seniority = str(row["seniority"])
        years_required = row["years_required"]
        if years_required is not None:
            years_required = int(years_required)
        raw_remote = row["remote_ok"]
        remote_ok = True if raw_remote == 1 else (False if raw_remote == 0 else None)

        return {
            "required_skills": required_skills,
            "nice_to_have": nice_to_have,
            "seniority": seniority,
            "years_required": years_required,
            "remote_ok": remote_ok,
        }


def save_extraction(db_path: str, description_hash: str, extraction: dict[str, Any]) -> None:
    init_db(db_path)
    backend = get_backend()
    required_skills_json = json.dumps(extraction.get("required_skills", []))
    nice_to_have_json = json.dumps(extraction.get("nice_to_have", []))
    seniority = str(extraction.get("seniority", "unknown"))
    years_required = extraction.get("years_required")
    if years_required is not None:
        years_required = int(years_required)

    raw_remote = extraction.get("remote_ok")
    remote_ok = 1 if raw_remote is True else (0 if raw_remote is False else None)
    extracted_at = datetime.now(timezone.utc).isoformat()

    with DB(db_path) as db:
        if backend == "postgres":
            db.execute(
                """
                INSERT INTO extractions (
                    hash, required_skills, nice_to_have, seniority, years_required, remote_ok, extracted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (hash) DO UPDATE SET
                    required_skills = EXCLUDED.required_skills,
                    nice_to_have = EXCLUDED.nice_to_have,
                    seniority = EXCLUDED.seniority,
                    years_required = EXCLUDED.years_required,
                    remote_ok = EXCLUDED.remote_ok,
                    extracted_at = EXCLUDED.extracted_at
                """,
                (
                    description_hash,
                    required_skills_json,
                    nice_to_have_json,
                    seniority,
                    years_required,
                    remote_ok,
                    extracted_at,
                ),
            )
        else:
            db.execute(
                """
                INSERT OR REPLACE INTO extractions (
                    hash, required_skills, nice_to_have, seniority, years_required, remote_ok, extracted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    description_hash,
                    required_skills_json,
                    nice_to_have_json,
                    seniority,
                    years_required,
                    remote_ok,
                    extracted_at,
                ),
            )


def clear_all_scores(db_path: str) -> int:
    init_db(db_path)
    with DB(db_path) as db:
        db.execute("UPDATE listings SET fit_score = NULL, fit_reason = NULL WHERE fit_score IS NOT NULL")
        return int(db.cursor.rowcount)


def clear_listing_score(db_path: str, listing_id: str) -> int:
    init_db(db_path)
    with DB(db_path) as db:
        db.execute("UPDATE listings SET fit_score = NULL, fit_reason = NULL WHERE id = ?", (listing_id,))
        return int(db.cursor.rowcount)


def get_all_extractions(db_path: str) -> list[dict[str, Any]]:
    init_db(db_path)
    with DB(db_path) as db:
        db.execute(
            """
            SELECT hash, required_skills, nice_to_have, seniority, years_required, remote_ok, extracted_at
            FROM extractions
            """
        )
        results = []
        for row in db.cursor.fetchall():
            results.append(
                {
                    "hash": row["hash"],
                    "required_skills": json.loads(row["required_skills"]),
                    "nice_to_have": json.loads(row["nice_to_have"]),
                    "seniority": row["seniority"],
                    "years_required": row["years_required"],
                    "remote_ok": True if row["remote_ok"] == 1 else (False if row["remote_ok"] == 0 else None),
                    "extracted_at": row["extracted_at"],
                }
            )
        return results


def get_scored_listings(db_path: str) -> list[dict[str, Any]]:
    init_db(db_path)
    with DB(db_path) as db:
        db.execute(
            """
            SELECT * FROM listings
            WHERE fit_score IS NOT NULL
            ORDER BY fit_score DESC
            """
        )
        return [dict(r) for r in db.cursor.fetchall()]


def save_gap_snapshot(
    db_path: str, run_id: str, computed_at: str, gaps: list[dict[str, Any]]
) -> None:
    init_db(db_path)
    with DB(db_path) as db:
        for g in gaps:
            example_ids_json = json.dumps(g.get("example_ids", []))
            db.execute(
                """
                INSERT INTO skill_gaps (
                    run_id, computed_at, skill, listings_blocked, opportunity_cost,
                    mean_score, top_score, example_ids, also_nice_to_have, confidence
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    computed_at,
                    str(g.get("skill", "")),
                    int(g.get("listings_blocked", 0)),
                    float(g.get("opportunity_cost", 0.0)),
                    float(g.get("mean_score", 0.0)),
                    int(g.get("top_score", 0)),
                    example_ids_json,
                    int(g.get("also_nice_to_have", 0)),
                    str(g.get("confidence", "normal")),
                ),
            )


def get_latest_gap_snapshot(db_path: str) -> list[dict[str, Any]]:
    init_db(db_path)
    with DB(db_path) as db:
        db.execute("SELECT run_id, computed_at FROM skill_gaps ORDER BY id DESC LIMIT 1")
        latest = db.cursor.fetchone()
        if not latest:
            return []

        latest_run_id = latest["run_id"]
        db.execute(
            """
            SELECT * FROM skill_gaps
            WHERE run_id = ?
            ORDER BY opportunity_cost DESC
            """,
            (latest_run_id,),
        )
        results = []
        for row in db.cursor.fetchall():
            item = dict(row)
            item["example_ids"] = json.loads(item["example_ids"])
            results.append(item)
        return results


def get_gap_snapshot_history(db_path: str) -> list[dict[str, Any]]:
    init_db(db_path)
    with DB(db_path) as db:
        db.execute(
            """
            SELECT run_id, MIN(computed_at) as computed_at, COUNT(*) as gap_count
            FROM skill_gaps
            GROUP BY run_id
            ORDER BY MIN(id) ASC
            """
        )
        return [dict(r) for r in db.cursor.fetchall()]


def get_gap_snapshot_by_run_id(db_path: str, run_id: str) -> list[dict[str, Any]]:
    init_db(db_path)
    with DB(db_path) as db:
        db.execute(
            """
            SELECT * FROM skill_gaps
            WHERE run_id = ?
            ORDER BY opportunity_cost DESC
            """,
            (run_id,),
        )
        results = []
        for row in db.cursor.fetchall():
            item = dict(row)
            item["example_ids"] = json.loads(item["example_ids"])
            results.append(item)
        return results


def get_state_metrics(db_path: str) -> dict[str, Any]:
    init_db(db_path)
    with DB(db_path) as db:
        db.execute("SELECT MAX(fetched_at) FROM listings")
        row_fetch = db.cursor.fetchone()
        last_fetch_at = _val(row_fetch)

        db.execute("SELECT COUNT(*) FROM listings WHERE fit_score IS NULL")
        row_unscored = db.cursor.fetchone()
        unscored_count = int(_val(row_unscored) or 0)

        db.execute("SELECT MAX(finished_at) FROM cycle_log WHERE agent = 'Scorer' AND status = 'ok'")
        row_scored = db.cursor.fetchone()
        max_scored_at = _val(row_scored)

        db.execute("SELECT MAX(computed_at) FROM skill_gaps")
        row_gaps = db.cursor.fetchone()
        gaps_computed_at = _val(row_gaps)

        db.execute("SELECT status, finished_at FROM cycle_log ORDER BY id DESC LIMIT 1")
        row_cycle = db.cursor.fetchone()
        last_cycle_status = row_cycle["status"] if row_cycle else None
        last_cycle_at = row_cycle["finished_at"] if row_cycle else None

        db.execute("SELECT COUNT(*) FROM listings")
        total_listings = int(_val(db.cursor.fetchone()) or 0)

        db.execute("SELECT COUNT(*) FROM listings WHERE fit_score IS NOT NULL")
        total_scored = int(_val(db.cursor.fetchone()) or 0)

        return {
            "last_fetch_at": last_fetch_at,
            "unscored_count": unscored_count,
            "max_scored_at": max_scored_at,
            "gaps_computed_at": gaps_computed_at,
            "last_cycle_verdict": last_cycle_status,
            "last_cycle_at": last_cycle_at,
            "total_listings": total_listings,
            "total_scored": total_scored,
        }


def get_latest_passing_cycle(db_path: str = "edgedash.db") -> dict[str, Any] | None:
    init_db(db_path)
    with DB(db_path) as db:
        db.execute(
            """
            SELECT * FROM cycle_log
            WHERE agent = 'Orchestrator' AND (status = 'complete' OR status = 'pass' OR notes LIKE '%verdict=pass%')
            ORDER BY id DESC LIMIT 1
            """
        )
        row = db.cursor.fetchone()
        return dict(row) if row else None


def get_recent_cycles(db_path: str = "edgedash.db", limit: int = 30) -> list[dict[str, Any]]:
    init_db(db_path)
    with DB(db_path) as db:
        db.execute(
            """
            SELECT * FROM cycle_log
            WHERE agent = 'Orchestrator'
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(r) for r in db.cursor.fetchall()]


def query_companies_hiring(db_path: str = "edgedash.db", days: int = 7) -> list[dict[str, Any]]:
    init_db(db_path)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    with DB(db_path) as db:
        db.execute(
            """
            SELECT company, COUNT(*) as listing_count, MAX(posted_at) as latest_posted_at
            FROM listings
            WHERE posted_at >= ? OR fetched_at >= ?
            GROUP BY company
            ORDER BY listing_count DESC, company ASC
            """,
            (cutoff, cutoff),
        )
        return [dict(r) for r in db.cursor.fetchall()]


def query_best_matches(db_path: str = "edgedash.db", limit: int = 10) -> list[dict[str, Any]]:
    init_db(db_path)
    with DB(db_path) as db:
        db.execute(
            """
            SELECT fit_score, title, company, fit_reason, url, location, posted_at
            FROM listings
            WHERE fit_score IS NOT NULL
            ORDER BY fit_score DESC, fetched_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(r) for r in db.cursor.fetchall()]


def query_top_gaps(db_path: str = "edgedash.db", limit: int = 5) -> list[dict[str, Any]]:
    init_db(db_path)
    snapshot = get_latest_gap_snapshot(db_path)
    rows = []
    for g in snapshot[:limit]:
        rows.append(
            {
                "skill": g.get("skill", ""),
                "opportunity_cost": g.get("opportunity_cost", 0.0),
                "listings_blocked": g.get("listings_blocked", 0),
                "mean_score": g.get("mean_score", 0.0),
                "top_score": g.get("top_score", 0),
                "confidence": g.get("confidence", "normal"),
            }
        )
    return rows


def query_gap_detail(db_path: str = "edgedash.db", canonical_skill: str = "") -> list[dict[str, Any]]:
    init_db(db_path)
    snapshot = get_latest_gap_snapshot(db_path)
    matching_gap = None
    for g in snapshot:
        if str(g.get("skill", "")).strip().lower() == canonical_skill.strip().lower():
            matching_gap = g
            break

    if not matching_gap:
        return []

    example_ids = matching_gap.get("example_ids", [])
    if not example_ids:
        return []

    with DB(db_path) as db:
        placeholders = ",".join("?" * len(example_ids))
        db.execute(
            f"""
            SELECT id, title, company, fit_score, fit_reason, url
            FROM listings
            WHERE id IN ({placeholders})
            ORDER BY fit_score DESC
            """,
            example_ids,
        )
        return [dict(r) for r in db.cursor.fetchall()]


def query_gap_trend(db_path: str = "edgedash.db", weeks: int = 3) -> list[dict[str, Any]]:
    init_db(db_path)
    cutoff = (datetime.now(timezone.utc) - timedelta(weeks=weeks)).isoformat()
    with DB(db_path) as db:
        db.execute(
            """
            SELECT run_id, MIN(computed_at) as computed_at
            FROM skill_gaps
            WHERE computed_at >= ?
            GROUP BY run_id
            ORDER BY MIN(id) ASC
            """,
            (cutoff,),
        )
        runs = [dict(r) for r in db.cursor.fetchall()]
        if not runs:
            db.execute(
                """
                SELECT run_id, MIN(computed_at) as computed_at
                FROM skill_gaps
                GROUP BY run_id
                ORDER BY MIN(id) ASC
                """
            )
            runs = [dict(r) for r in db.cursor.fetchall()]

        if not runs:
            return []

        earliest_run_id = runs[0]["run_id"]
        latest_run_id = runs[-1]["run_id"]

        earliest_gaps = {
            g["skill"].lower(): g["opportunity_cost"]
            for g in get_gap_snapshot_by_run_id(db_path, earliest_run_id)
        }
        latest_gaps = get_gap_snapshot_by_run_id(db_path, latest_run_id)

        results = []
        for g in latest_gaps:
            skill = g["skill"]
            curr_cost = g["opportunity_cost"]
            prev_cost = earliest_gaps.get(skill.lower(), 0.0)
            change = round(curr_cost - prev_cost, 2)
            results.append(
                {
                    "skill": skill,
                    "current_opportunity_cost": curr_cost,
                    "previous_opportunity_cost": prev_cost,
                    "change": change,
                    "direction": "up" if change > 0 else ("down" if change < 0 else "unchanged"),
                    "snapshots_compared": len(runs),
                }
            )
        return results


def query_listing_count(db_path: str = "edgedash.db") -> list[dict[str, Any]]:
    init_db(db_path)
    with DB(db_path) as db:
        db.execute("SELECT COUNT(*) FROM listings")
        total = int(_val(db.cursor.fetchone()) or 0)

        db.execute("SELECT COUNT(*) FROM listings WHERE fit_score IS NOT NULL")
        scored = int(_val(db.cursor.fetchone()) or 0)

        db.execute("SELECT COUNT(*) FROM listings WHERE fit_score IS NULL")
        unscored = int(_val(db.cursor.fetchone()) or 0)

        db.execute("SELECT MAX(posted_at), MAX(fetched_at) FROM listings")
        row = db.cursor.fetchone()
        newest_posted = _val(row, 0)
        newest_fetched = _val(row, 1)
        newest_date = newest_posted or newest_fetched or "N/A"

        return [
            {
                "total_listings": total,
                "scored_listings": scored,
                "unscored_listings": unscored,
                "newest_listing_date": newest_date,
            }
        ]


def query_skill_demand(db_path: str = "edgedash.db", canonical_skill: str = "") -> list[dict[str, Any]]:
    init_db(db_path)
    extractions = get_all_extractions(db_path)
    required_count = 0
    nice_to_have_count = 0
    target_skill = canonical_skill.strip().lower()

    for ext in extractions:
        reqs = [s.strip().lower() for s in ext.get("required_skills", []) if isinstance(s, str)]
        nices = [s.strip().lower() for s in ext.get("nice_to_have", []) if isinstance(s, str)]

        if target_skill in reqs:
            required_count += 1
        if target_skill in nices:
            nice_to_have_count += 1

    total_mentions = required_count + nice_to_have_count
    if total_mentions == 0:
        return []

    return [
        {
            "skill": canonical_skill,
            "required_count": required_count,
            "nice_to_have_count": nice_to_have_count,
            "total_mentions": total_mentions,
        }
    ]


def get_present_skills(db_path: str = "edgedash.db") -> set[str]:
    init_db(db_path)
    skills_set: set[str] = set()
    extractions = get_all_extractions(db_path)
    for ext in extractions:
        for s in ext.get("required_skills", []) + ext.get("nice_to_have", []):
            if isinstance(s, str) and s.strip():
                skills_set.add(s.strip().lower())

    latest_gaps = get_latest_gap_snapshot(db_path)
    for g in latest_gaps:
        s = g.get("skill", "")
        if isinstance(s, str) and s.strip():
            skills_set.add(s.strip().lower())
    return skills_set


def log_query(
    db_path: str,
    question: str,
    tool_chosen: str | None,
    params: dict[str, Any] | None,
    answerable: bool,
    duration_ms: float,
) -> int:
    init_db(db_path)
    backend = get_backend()
    params_json = json.dumps(params or {})
    asked_at = datetime.now(timezone.utc).isoformat()
    with DB(db_path) as db:
        if backend == "postgres":
            db.execute(
                """
                INSERT INTO query_log (question, tool_chosen, params, answerable, duration_ms, asked_at)
                VALUES (?, ?, ?, ?, ?, ?)
                RETURNING id
                """,
                (
                    question,
                    tool_chosen,
                    params_json,
                    1 if answerable else 0,
                    duration_ms,
                    asked_at,
                ),
            )
            row = db.cursor.fetchone()
            return int(_val(row) or 0)
        else:
            db.execute(
                """
                INSERT INTO query_log (question, tool_chosen, params, answerable, duration_ms, asked_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    question,
                    tool_chosen,
                    params_json,
                    1 if answerable else 0,
                    duration_ms,
                    asked_at,
                ),
            )
            return int(db.cursor.lastrowid or 0)


def get_recent_queries(db_path: str = "edgedash.db", limit: int = 20) -> list[dict[str, Any]]:
    init_db(db_path)
    with DB(db_path) as db:
        db.execute(
            """
            SELECT * FROM query_log
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(r) for r in db.cursor.fetchall()]


def count_queries_today(db_path: str = "edgedash.db") -> int:
    init_db(db_path)
    start_of_day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with DB(db_path) as db:
        db.execute(
            """
            SELECT COUNT(*) FROM query_log
            WHERE asked_at >= ?
            """,
            (start_of_day,),
        )
        row = db.cursor.fetchone()
        return int(_val(row) or 0)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="EdgeDash Storage Management CLI")
    parser.add_argument("--migrate", action="store_true", help="Run database migrations / table creation.")
    parser.add_argument("--check", action="store_true", help="Check database connection and table row counts.")
    args = parser.parse_args()

    backend = get_backend()

    if args.migrate:
        print(f"Running migration on active backend ({backend.upper()})...")
        init_db()
        print("Migration complete. All tables created successfully.")

    elif args.check:
        print(f"Active backend: {backend.upper()}")
        try:
            init_db()
            print(f"Connection check: SUCCESS (Connected to {backend.upper()})")

            tables = ["listings", "skill_gaps", "cycle_log", "extractions", "query_log"]
            print("\nTable Row Counts:")
            with DB() as db:
                for table in tables:
                    db.execute(f"SELECT COUNT(*) FROM {table}")
                    row = db.cursor.fetchone()
                    count = int(_val(row) or 0)
                    print(f"  - {table}: {count}")
        except Exception as e:
            print(f"Connection check: FAILED - {e}")
            sys.exit(1)
