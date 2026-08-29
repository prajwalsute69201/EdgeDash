import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from edgedash import storage
from edgedash.rescore import main as rescore_main


class TestRescore(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.temp_db.close()
        self.db_path = self.temp_db.name
        storage.init_db(self.db_path)

        # Seed listings
        rows = [
            {
                "id": "item1",
                "title": "Data Analyst",
                "company": "Company A",
                "location": "Dubai",
                "url": "https://example.com/1",
                "description": "Python, SQL required",
                "source": "arbeitnow",
                "posted_at": "2026-08-24T10:00:00Z",
                "fetched_at": "2026-08-24T10:00:00Z",
                "fit_score": 85,
                "fit_reason": "2/2 skills",
            },
            {
                "id": "item2",
                "title": "Senior Data Analyst",
                "company": "Company B",
                "location": "Dubai",
                "url": "https://example.com/2",
                "description": "Python, Tableau required",
                "source": "arbeitnow",
                "posted_at": "2026-08-24T10:00:00Z",
                "fetched_at": "2026-08-24T10:00:00Z",
                "fit_score": 90,
                "fit_reason": "2/2 skills",
            },
        ]
        storage.upsert_listings(self.db_path, rows)

        # Seed extraction cache
        storage.save_extraction(
            self.db_path,
            "hash1",
            {"required_skills": ["python", "sql"], "nice_to_have": [], "seniority": "mid", "years_required": 2, "remote_ok": True},
        )

    def tearDown(self) -> None:
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except OSError:
                pass

    def test_clear_all_scores_storage(self) -> None:
        cleared = storage.clear_all_scores(self.db_path)
        self.assertEqual(cleared, 2)
        self.assertEqual(storage.count_unscored(self.db_path), 2)

        # Extraction cache MUST remain untouched
        cached = storage.get_extraction(self.db_path, "hash1")
        self.assertIsNotNone(cached)
        self.assertEqual(cached["required_skills"], ["python", "sql"])

    def test_clear_listing_score_storage(self) -> None:
        cleared = storage.clear_listing_score(self.db_path, "item1")
        self.assertEqual(cleared, 1)

        # Only item1 is unscored, item2 remains scored
        self.assertEqual(storage.count_unscored(self.db_path), 1)

        # Extraction cache MUST remain untouched
        cached = storage.get_extraction(self.db_path, "hash1")
        self.assertIsNotNone(cached)

    @patch("sys.argv", ["rescore", "--all", "-y"])
    @patch("edgedash.rescore.load_config")
    def test_rescore_cli_all_yes(self, mock_load_config: MagicMock) -> None:
        mock_cfg = unittest.mock.MagicMock()
        mock_cfg.db_path = self.db_path
        mock_load_config.return_value = mock_cfg

        rescore_main()
        self.assertEqual(storage.count_unscored(self.db_path), 2)

    @patch("sys.argv", ["rescore", "--id", "item1"])
    @patch("edgedash.rescore.load_config")
    def test_rescore_cli_id(self, mock_load_config: MagicMock) -> None:
        mock_cfg = unittest.mock.MagicMock()
        mock_cfg.db_path = self.db_path
        mock_load_config.return_value = mock_cfg

        rescore_main()
        self.assertEqual(storage.count_unscored(self.db_path), 1)

    @patch("sys.argv", ["rescore", "--all"])
    @patch("builtins.input", return_value="n")
    @patch("edgedash.rescore.load_config")
    def test_rescore_cli_all_refused(self, mock_load_config: MagicMock, mock_input: MagicMock) -> None:

        mock_cfg = unittest.mock.MagicMock()
        mock_cfg.db_path = self.db_path
        mock_load_config.return_value = mock_cfg

        with self.assertRaises(SystemExit) as cm:
            rescore_main()

        self.assertEqual(cm.exception.code, 0)
        # Scores must NOT be cleared when refused
        self.assertEqual(storage.count_unscored(self.db_path), 0)



if __name__ == "__main__":
    unittest.main()
