import os
import tempfile
import unittest

from edgedash import storage
from edgedash.agents.extractor import compute_description_hash
from edgedash.agents.gap_analyzer import GapAnalyzer
from edgedash.config import Config


class TestGapAnalyzer(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.temp_db.close()
        self.db_path = self.temp_db.name
        storage.init_db(self.db_path)

        self.config = Config(
            db_path=self.db_path,
            my_skills=["python", "sql"],
            skill_aliases={"k8s": "kubernetes"},
        )

        # Seed listings with fit scores
        listings = [
            {
                "id": "job1",
                "title": "Senior Engineer",
                "company": "Company A",
                "location": "Dubai",
                "url": "https://example.com/1",
                "description": "Needs kubernetes and docker",
                "source": "arbeitnow",
                "posted_at": "2026-08-24T10:00:00Z",
                "fetched_at": "2026-08-24T10:00:00Z",
                "fit_score": 80,
                "fit_reason": "high fit",
            },
            {
                "id": "job2",
                "title": "Cloud Specialist",
                "company": "Company B",
                "location": "Dubai",
                "url": "https://example.com/2",
                "description": "Needs k8s and aws",
                "source": "arbeitnow",
                "posted_at": "2026-08-24T10:00:00Z",
                "fetched_at": "2026-08-24T10:00:00Z",
                "fit_score": 90,
                "fit_reason": "high fit",
            },
            {
                "id": "job3",
                "title": "DevOps Engineer",
                "company": "Company C",
                "location": "Dubai",
                "url": "https://example.com/3",
                "description": "Needs kubernetes",
                "source": "arbeitnow",
                "posted_at": "2026-08-24T10:00:00Z",
                "fetched_at": "2026-08-24T10:00:00Z",
                "fit_score": 70,
                "fit_reason": "med fit",
            },
        ]
        storage.upsert_listings(self.db_path, listings)

        # Seed extractions
        storage.save_extraction(
            self.db_path,
            compute_description_hash(listings[0]["description"]),
            {"required_skills": ["kubernetes", "docker"], "nice_to_have": ["aws"], "seniority": "senior", "years_required": 5, "remote_ok": True},
        )
        storage.save_extraction(
            self.db_path,
            compute_description_hash(listings[1]["description"]),
            {"required_skills": ["k8s", "aws"], "nice_to_have": ["docker"], "seniority": "senior", "years_required": 5, "remote_ok": True},
        )
        storage.save_extraction(
            self.db_path,
            compute_description_hash(listings[2]["description"]),
            {"required_skills": ["kubernetes"], "nice_to_have": [], "seniority": "mid", "years_required": 3, "remote_ok": True},
        )

    def tearDown(self) -> None:
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except OSError:
                pass

    def test_opportunity_cost_and_ranking(self) -> None:
        analyzer = GapAnalyzer()
        res = analyzer.run(self.config)

        self.assertEqual(res.status, "ok")
        self.assertIn("kubernetes", res.notes)

        # Read latest snapshot from storage
        snapshot = storage.get_latest_gap_snapshot(self.db_path)
        self.assertTrue(len(snapshot) > 0)

        # Top gap must be kubernetes (appears in all 3 listings: scores 80, 90, 70)
        top_gap = snapshot[0]
        self.assertEqual(top_gap["skill"], "kubernetes")
        self.assertEqual(top_gap["listings_blocked"], 3)

        # Opportunity cost arithmetic: (80 + 90 + 70) / 100.0 = 2.40
        self.assertAlmostEqual(top_gap["opportunity_cost"], 2.40, places=2)
        self.assertAlmostEqual(top_gap["mean_score"], 80.0, places=1)
        self.assertEqual(top_gap["top_score"], 90)

        # Confidence: 3 listings => "normal"
        self.assertEqual(top_gap["confidence"], "normal")

        # Example IDs ordered by score descending: job2 (90), job1 (80), job3 (70)
        self.assertEqual(top_gap["example_ids"], ["job2", "job1", "job3"])

    def test_low_confidence_flag(self) -> None:
        analyzer = GapAnalyzer()
        analyzer.run(self.config)

        snapshot = storage.get_latest_gap_snapshot(self.db_path)
        # docker appears in 1 listing as required => listings_blocked = 1 < 3 => low confidence
        docker_gap = next((g for g in snapshot if g["skill"] == "docker"), None)
        self.assertIsNotNone(docker_gap)
        self.assertEqual(docker_gap["confidence"], "low confidence")

    def test_nice_to_have_separation(self) -> None:
        analyzer = GapAnalyzer()
        analyzer.run(self.config)

        snapshot = storage.get_latest_gap_snapshot(self.db_path)
        # docker was required in job1, nice_to_have in job2
        docker_gap = next((g for g in snapshot if g["skill"] == "docker"), None)
        self.assertIsNotNone(docker_gap)
        self.assertEqual(docker_gap["listings_blocked"], 1)  # only required count
        self.assertEqual(docker_gap["also_nice_to_have"], 1)  # separate nice_to_have count

    def test_snapshot_non_overwriting(self) -> None:
        analyzer = GapAnalyzer()
        analyzer.run(self.config)
        snapshot1 = storage.get_latest_gap_snapshot(self.db_path)

        analyzer.run(self.config)
        snapshot2 = storage.get_latest_gap_snapshot(self.db_path)

        # Two snapshot runs should exist in skill_gaps with distinct run_ids
        with storage.sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(DISTINCT run_id) FROM skill_gaps")
            run_count = cursor.fetchone()[0]
            self.assertEqual(run_count, 2)


if __name__ == "__main__":
    unittest.main()
