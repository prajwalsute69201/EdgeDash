import os
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock

from edgedash import storage
from edgedash.agents.base import AgentResult
from edgedash.config import Config
from edgedash.orchestrator import run_cycle


from typing import Any

class FailingAgent:
    name: str = "FailingAgent"

    def run(
        self,
        config: Config,
        goal: str | None = None,
        stop_conditions: dict[str, Any] | None = None,
    ) -> AgentResult:
        raise RuntimeError("Simulated agent error")


class SuccessfulAgent:
    name: str = "MockAgent"

    def run(
        self,
        config: Config,
        goal: str | None = None,
        stop_conditions: dict[str, Any] | None = None,
    ) -> AgentResult:
        return AgentResult(
            agent=self.name,
            status="ok",
            records_touched=5,
            notes="Completed successfully",
        )



class TestOrchestrator(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.temp_db.close()
        self.db_path = self.temp_db.name
        storage.init_db(self.db_path)
        self.config = Config(db_path=self.db_path)

    def tearDown(self) -> None:
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except OSError:
                pass

    def test_run_cycle_nothing_to_do(self) -> None:
        # Empty DB where recent fetch and gap analysis are up to date
        now = datetime(2026, 8, 24, 12, 0, 0, tzinfo=timezone.utc)

        # Seed recent fetch (1 hour ago), 0 unscored, recent gap analysis (30 mins ago)
        storage.upsert_listings(
            self.db_path,
            [
                {
                    "id": "j1",
                    "title": "A",
                    "company": "B",
                    "location": "C",
                    "url": "http://1",
                    "description": "d",
                    "source": "s",
                    "posted_at": "2026-08-24T10:00:00Z",
                    "fetched_at": "2026-08-24T11:00:00Z",
                    "fit_score": 80,
                    "fit_reason": "ok",
                    "scored_at": "2026-08-24T11:10:00Z",
                }
            ],
        )
        storage.save_gap_snapshot(
            self.db_path,
            run_id="r1",
            computed_at="2026-08-24T11:30:00Z",
            gaps=[
                {
                    "skill": "dummy",
                    "listings_blocked": 1,
                    "opportunity_cost": 0.8,
                    "mean_score": 80.0,
                    "top_score": 80,
                    "example_ids": ["j1"],
                    "also_nice_to_have": 0,
                    "confidence": "low confidence",
                }
            ],
        )

        results = run_cycle(self.config, now=now)
        self.assertEqual(len(results), 3)
        self.assertTrue(all(r.status == "skipped" for r in results))

        # Check Orchestrator summary row in cycle_log
        with storage.sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT status, notes FROM cycle_log WHERE agent = 'Orchestrator' ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], "nothing_to_do")
            self.assertIn("outcome=nothing_to_do", row[1])

    def test_run_cycle_partial_on_subagent_failure(self) -> None:
        # Force a cycle where Fetcher runs and fails
        registry = [FailingAgent(), SuccessfulAgent()]
        now = datetime(2026, 8, 24, 12, 0, 0, tzinfo=timezone.utc)

        results = run_cycle(self.config, registry=registry, now=now)

        # Check Orchestrator outcome is partial
        with storage.sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT status FROM cycle_log WHERE agent = 'Orchestrator' ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
            self.assertEqual(row[0], "partial")

    def test_dry_run_flag(self) -> None:
        now = datetime(2026, 8, 24, 12, 0, 0, tzinfo=timezone.utc)
        results = run_cycle(self.config, now=now, dry_run=True)
        self.assertEqual(results, [])

        # Ensure no cycle_log row was written during dry run
        with storage.sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM cycle_log")
            count = cursor.fetchone()[0]
            self.assertEqual(count, 0)

    def test_force_flag_overrides_skipped_agent(self) -> None:
        now = datetime(2026, 8, 24, 12, 0, 0, tzinfo=timezone.utc)

        # Seed recent fetch (1 hour ago) so Fetcher would normally be skipped
        storage.upsert_listings(
            self.db_path,
            [
                {
                    "id": "j1",
                    "title": "A",
                    "company": "B",
                    "location": "C",
                    "url": "http://1",
                    "description": "d",
                    "source": "s",
                    "posted_at": "2026-08-24T10:00:00Z",
                    "fetched_at": "2026-08-24T11:00:00Z",
                    "fit_score": 80,
                    "fit_reason": "ok",
                    "scored_at": "2026-08-24T11:10:00Z",
                }
            ],
        )

        mock_fetcher = MagicMock()
        mock_fetcher.name = "Fetcher"
        mock_fetcher.run.return_value = AgentResult(
            agent="Fetcher",
            status="ok",
            records_touched=3,
            notes="Fetched 3 items via force",
        )
        mock_scorer = MagicMock()
        mock_scorer.name = "Scorer"

        registry = [mock_fetcher, mock_scorer]

        results = run_cycle(
            self.config, registry=registry, now=now, force_agents=["Fetcher"]
        )

        # Fetcher should have executed due to force
        mock_fetcher.run.assert_called_once()

        # Check cycle_log notes record the forced override
        with storage.sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT notes FROM cycle_log WHERE agent = 'Orchestrator' ORDER BY id DESC LIMIT 1"
            )
            row = cursor.fetchone()
            self.assertIsNotNone(row)
            self.assertIn("forced=[Fetcher]", row[0])

    def test_explain_flag(self) -> None:
        import io
        import sys

        now = datetime(2026, 8, 24, 12, 0, 0, tzinfo=timezone.utc)
        captured_output = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = captured_output
            run_cycle(self.config, now=now, explain=True, dry_run=True)
        finally:
            sys.stdout = old_stdout

        output = captured_output.getvalue()
        self.assertIn("SYSTEM STATE & DECISION EXPLANATION", output)
        self.assertIn("Fetcher Task", output)
        self.assertIn("Scorer Task", output)
        self.assertIn("GapAnalyzer Task", output)


if __name__ == "__main__":
    unittest.main()
