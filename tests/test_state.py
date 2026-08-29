import os
import tempfile
import unittest
from datetime import datetime, timezone

from edgedash import storage
from edgedash.config import Config
from edgedash.state import read_state


class TestState(unittest.TestCase):
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

    def test_read_state_empty_db(self) -> None:
        now = datetime(2026, 8, 24, 12, 0, 0, tzinfo=timezone.utc)
        state = read_state(self.config, now)

        self.assertIsNone(state.last_fetch_at)
        self.assertIsNone(state.hours_since_fetch)
        self.assertEqual(state.unscored_count, 0)
        self.assertIsNone(state.gaps_computed_at)
        self.assertTrue(state.gaps_stale)
        self.assertIsNone(state.last_cycle_verdict)

    def test_read_state_with_data(self) -> None:
        now = datetime(2026, 8, 24, 14, 0, 0, tzinfo=timezone.utc)

        # Seed 1 fetched listing 2 hours ago
        listings = [
            {
                "id": "job1",
                "title": "Analyst",
                "company": "Co",
                "location": "Dubai",
                "url": "https://example.com/1",
                "description": "desc",
                "source": "arbeitnow",
                "posted_at": "2026-08-24T10:00:00Z",
                "fetched_at": "2026-08-24T12:00:00Z",
            }
        ]
        storage.upsert_listings(self.db_path, listings)

        state = read_state(self.config, now)

        self.assertEqual(state.unscored_count, 1)
        self.assertIsNotNone(state.last_fetch_at)
        self.assertAlmostEqual(state.hours_since_fetch, 2.0, places=1)
        self.assertTrue(state.gaps_stale)


if __name__ == "__main__":
    unittest.main()
