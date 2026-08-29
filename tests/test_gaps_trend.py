import os
import tempfile
import unittest
from typing import Any
from unittest.mock import MagicMock, patch

from edgedash import storage
from edgedash.gaps import print_trend_report


class TestGapsTrend(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.temp_db.close()
        self.db_path = self.temp_db.name
        storage.init_db(self.db_path)

    def tearDown(self) -> None:
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except OSError:
                pass

    @patch("edgedash.gaps.load_config")
    def test_trend_single_snapshot_refuses_extrapolation(self, mock_load_config: MagicMock) -> None:
        mock_cfg = unittest.mock.MagicMock()
        mock_cfg.db_path = self.db_path
        mock_load_config.return_value = mock_cfg

        # Insert 1 snapshot
        gaps_run1 = [
            {"skill": "kubernetes", "listings_blocked": 5, "opportunity_cost": 4.5, "mean_score": 90.0, "top_score": 95, "example_ids": ["id1"], "also_nice_to_have": 0, "confidence": "normal"},
        ]
        storage.save_gap_snapshot(self.db_path, "run1", "2026-08-20T10:00:00Z", gaps_run1)

        with patch("sys.stdout.write") as mock_stdout:
            print_trend_report()
            # Ensure it mentions single snapshot and at least 2 runs required
            out = "".join(call.args[0] for call in mock_stdout.call_args_list)
            self.assertIn("ONLY 1 SNAPSHOT RECORDED", out)
            self.assertIn("At least 2 snapshot runs across multiple days are required", out)

    @patch("edgedash.gaps.load_config")
    def test_trend_multiple_snapshots(self, mock_load_config: MagicMock) -> None:
        mock_cfg = unittest.mock.MagicMock()
        mock_cfg.db_path = self.db_path
        mock_load_config.return_value = mock_cfg

        # Earliest snapshot run1 (Aug 20)
        gaps_run1 = [
            {"skill": "kubernetes", "listings_blocked": 5, "opportunity_cost": 4.0, "mean_score": 80.0, "top_score": 90, "example_ids": ["id1"], "also_nice_to_have": 0, "confidence": "normal"},
            {"skill": "python", "listings_blocked": 3, "opportunity_cost": 2.5, "mean_score": 83.3, "top_score": 90, "example_ids": ["id2"], "also_nice_to_have": 0, "confidence": "normal"},
        ]
        storage.save_gap_snapshot(self.db_path, "run1", "2026-08-20T10:00:00Z", gaps_run1)

        # Latest snapshot run2 (Aug 24)
        gaps_run2 = [
            {"skill": "kubernetes", "listings_blocked": 8, "opportunity_cost": 6.8, "mean_score": 85.0, "top_score": 95, "example_ids": ["id1"], "also_nice_to_have": 0, "confidence": "normal"},
            {"skill": "docker", "listings_blocked": 4, "opportunity_cost": 3.2, "mean_score": 80.0, "top_score": 85, "example_ids": ["id3"], "also_nice_to_have": 0, "confidence": "normal"},
        ]
        storage.save_gap_snapshot(self.db_path, "run2", "2026-08-24T10:00:00Z", gaps_run2)

        with patch("sys.stdout.write") as mock_stdout:
            print_trend_report()
            out = "".join(call.args[0] for call in mock_stdout.call_args_list)

            # Check snapshot dates printed
            self.assertIn("2026-08-20T10:00:00", out)
            self.assertIn("2026-08-24T10:00:00", out)

            # Check kubernetes change (+2.80, +70.0%)
            self.assertIn("kubernetes", out)
            self.assertIn("+2.80", out)

            # Check docker marked as NEW SKILL
            self.assertIn("docker", out)
            self.assertIn("NEW SKILL", out)

            # Check python marked as DROPPED OUT
            self.assertIn("python", out)
            self.assertIn("DROPPED OUT", out)


if __name__ == "__main__":
    unittest.main()
