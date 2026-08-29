from datetime import datetime, timezone
import unittest

from edgedash.config import Config
from edgedash.scoring import score_listing, build_reason, compute_seniority_fit


class TestScoring(unittest.TestCase):
    def setUp(self) -> None:
        self.config = Config(
            my_skills=["python", "sql", "pandas", "tableau"],
            target_city="Dubai",
            experience_years=3,  # target_seniority = mid
            weight_skill_match=0.45,
            weight_seniority_fit=0.25,
            weight_location_fit=0.15,
            weight_recency=0.15,
        )

    def test_perfect_match(self) -> None:
        listing = {
            "location": "Dubai, UAE",
            "posted_at": datetime.now(timezone.utc).isoformat(),
        }
        facts = {
            "required_skills": ["python", "sql"],
            "nice_to_have": ["pandas", "tableau"],
            "seniority": "mid",
            "remote_ok": True,
        }

        result = score_listing(listing, facts, self.config)

        self.assertEqual(result["score"], 100)
        self.assertEqual(result["components"]["skill_match"], 1.0)
        self.assertEqual(result["components"]["seniority_fit"], 1.0)
        self.assertEqual(result["components"]["location_fit"], 1.0)
        self.assertEqual(result["components"]["recency"], 1.0)
        self.assertIn("2/2 required skills", result["reason"])
        self.assertIn("seniority fits", result["reason"])
        self.assertIn("remote", result["reason"])
        self.assertNotIn("gap:", result["reason"])

    def test_zero_match(self) -> None:
        listing = {
            "location": "London, UK",
            "posted_at": "2020-01-01T00:00:00Z",  # > 30 days old => recency 0.0
        }
        facts = {
            "required_skills": ["rust", "cpp", "assembly"],
            "nice_to_have": ["go"],
            "seniority": "lead",  # target is mid => 2 bands off => 0.25
            "remote_ok": False,
        }

        result = score_listing(listing, facts, self.config)

        self.assertEqual(result["components"]["skill_match"], 0.0)
        self.assertEqual(result["components"]["seniority_fit"], 0.25)
        self.assertEqual(result["components"]["location_fit"], 0.1)
        self.assertEqual(result["components"]["recency"], 0.0)
        # Weighted sum: 0.45*0 + 0.25*0.25 + 0.15*0.1 + 0.15*0 = 0.0625 + 0.015 = 0.0775 => 8
        self.assertEqual(result["score"], 8)
        self.assertIn("0/3 required skills", result["reason"])
        self.assertIn("gap: rust, cpp, assembly", result["reason"])

    def test_empty_required_skills(self) -> None:
        listing = {
            "location": "Dubai",
            "posted_at": datetime.now(timezone.utc).isoformat(),
        }
        facts = {
            "required_skills": [],
            "nice_to_have": [],
            "seniority": "mid",
            "remote_ok": True,
        }

        result = score_listing(listing, facts, self.config)

        # Empty required_skills should result in skill_match = 1.0 without zero division
        self.assertEqual(result["components"]["skill_match"], 1.0)
        self.assertEqual(result["score"], 100)
        self.assertIn("no required skills listed", result["reason"])

    def test_null_posted_at(self) -> None:
        listing = {
            "location": "Dubai",
            "posted_at": None,
        }
        facts = {
            "required_skills": ["python"],
            "nice_to_have": [],
            "seniority": "mid",
            "remote_ok": True,
        }

        result = score_listing(listing, facts, self.config)

        # null posted_at defaults to recency = 0.5 without crashing
        self.assertEqual(result["components"]["recency"], 0.5)
        self.assertIn("posted date unknown", result["reason"])

    def test_null_remote_ok(self) -> None:
        listing = {
            "location": "Unknown Location",
            "posted_at": datetime.now(timezone.utc).isoformat(),
        }
        facts = {
            "required_skills": ["python"],
            "nice_to_have": [],
            "seniority": "mid",
            "remote_ok": None,
        }

        result = score_listing(listing, facts, self.config)

        # null remote_ok with unstated location defaults to location_fit = 0.5
        self.assertEqual(result["components"]["location_fit"], 0.5)
        self.assertIn("location unstated", result["reason"])

    def test_seniority_three_bands_off(self) -> None:
        # target_seniority = junior (index 0), listing seniority = lead (index 3) => distance 3 => 0.0
        config_junior = Config(
            my_skills=["python"],
            experience_years=1,  # target_seniority = junior
        )
        facts = {
            "required_skills": ["python"],
            "nice_to_have": [],
            "seniority": "lead",
            "remote_ok": True,
        }
        listing = {
            "location": "Dubai",
            "posted_at": datetime.now(timezone.utc).isoformat(),
        }

        result = score_listing(listing, facts, config_junior)

        self.assertEqual(result["components"]["seniority_fit"], 0.0)
        self.assertIn("lead (target: junior)", result["reason"])

    def test_reason_string_formatting(self) -> None:
        components = {
            "skill_match": 0.67,
            "seniority_fit": 1.0,
            "location_fit": 1.0,
            "recency": 1.0,
        }
        facts = {
            "required_skills": ["python", "sql", "kubernetes"],
            "nice_to_have": [],
            "seniority": "mid",
            "remote_ok": True,
        }
        reason = build_reason(
            components=components,
            facts=facts,
            config=self.config,
            missing_skills=["kubernetes"],
            matched_req_count=2,
            total_req_count=3,
            days_old=2.0,
        )
        expected = "2/3 required skills · seniority fits · remote · posted 2d ago · gap: kubernetes"
        self.assertEqual(reason, expected)


if __name__ == "__main__":
    unittest.main()
