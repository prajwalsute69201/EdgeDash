import os
import tempfile
import unittest
from typing import Any
from unittest.mock import MagicMock, patch

from edgedash import storage
from edgedash.agents.extractor import (
    EXTRACTION_SCHEMA,
    compute_description_hash,
    extract,
)
from edgedash.config import Config


class TestExtractor(unittest.TestCase):
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

    def test_compute_description_hash(self) -> None:
        desc1 = "Looking for a Python Developer with Postgres experience."
        desc2 = "  Looking for a Python Developer with Postgres experience. \n "
        h1 = compute_description_hash(desc1)
        h2 = compute_description_hash(desc2)
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 64)

    @patch("edgedash.llm.complete_json")
    def test_extract_uncached_normalizes_skills_and_caches(self, mock_complete_json: MagicMock) -> None:
        mock_complete_json.return_value = {
            "required_skills": ["Python", "Postgres", "AWS", "postgres"],
            "nice_to_have": ["Docker", "Kubernetes"],
            "seniority": "senior",
            "years_required": 5,
            "remote_ok": True,
        }

        listing = {"description": "We need a Senior Python Developer with Postgres experience."}
        result = extract(listing, config=self.config)

        # Verify LLM was called once
        mock_complete_json.assert_called_once()

        # Verify skill lowercasing and deduplication
        self.assertEqual(result["required_skills"], ["python", "postgres", "aws"])
        self.assertEqual(result["nice_to_have"], ["docker", "kubernetes"])
        self.assertEqual(result["seniority"], "senior")
        self.assertEqual(result["years_required"], 5)
        self.assertTrue(result["remote_ok"])

        # Verify Rule 16 constraint: fit_score / score must NOT be present
        self.assertNotIn("fit_score", result)
        self.assertNotIn("score", result)

        # Verify cache hit on second call
        mock_complete_json.reset_mock()
        result_cached = extract(listing, config=self.config)
        mock_complete_json.assert_not_called()
        self.assertEqual(result, result_cached)

    @patch("edgedash.llm.complete_json")
    def test_extract_handles_nulls(self, mock_complete_json: MagicMock) -> None:
        mock_complete_json.return_value = {
            "required_skills": [],
            "nice_to_have": [],
            "seniority": "unknown",
            "years_required": None,
            "remote_ok": None,
        }

        listing = {"description": "Generic software developer opening."}
        result = extract(listing, config=self.config)

        self.assertEqual(result["required_skills"], [])
        self.assertEqual(result["nice_to_have"], [])
        self.assertEqual(result["seniority"], "unknown")
        self.assertIsNone(result["years_required"])
        self.assertIsNone(result["remote_ok"])

    def test_schema_field_constraints(self) -> None:
        # Verify schema properties match exact fields
        props = set(EXTRACTION_SCHEMA["properties"].keys())
        expected_props = {
            "required_skills",
            "nice_to_have",
            "seniority",
            "years_required",
            "remote_ok",
        }
        self.assertEqual(props, expected_props)
        self.assertNotIn("score", props)
        self.assertNotIn("fit_score", props)


if __name__ == "__main__":
    unittest.main()
