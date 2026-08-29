import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch


from edgedash import storage
from edgedash.config import Config
from edgedash.skills import suggest_aliases


class TestSuggestAliases(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.temp_db.close()
        self.db_path = self.temp_db.name
        storage.init_db(self.db_path)

        # Seed extractions
        storage.save_extraction(
            self.db_path,
            "hash1",
            {"required_skills": ["deutsch", "german", "k8s", "kubernetes", "nodejs"], "nice_to_have": []},
        )

        self.config = Config(
            db_path=self.db_path,
            skill_aliases={"k8s": "kubernetes"},
        )

    def tearDown(self) -> None:
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except OSError:
                pass

    @patch("edgedash.llm.complete_json")
    def test_suggest_aliases_read_only_and_conflict_detection(self, mock_complete_json: MagicMock) -> None:

        # Mock LLM returning 2 proposals: 1 clean, 1 conflicting with existing alias
        mock_complete_json.return_value = {
            "proposals": [
                {
                    "canonical": "german",
                    "variants": ["deutsch", "german"],
                    "confidence": "high",
                },
                {
                    "canonical": "kubernetes",
                    "variants": ["k8s", "kubernetes"],
                    "confidence": "high",
                },
            ]
        }

        with patch("sys.stdout.write") as mock_stdout:
            suggest_aliases(self.config)
            out = "".join(call.args[0] for call in mock_stdout.call_args_list)

            # 1. Exactly 1 LLM call made
            self.assertEqual(mock_complete_json.call_count, 1)

            # 2. Warning banner printed with Rule 23 reference
            self.assertIn("WARNING: ALIAS SUGGESTIONS REQUIRE HUMAN REVIEW", out)
            self.assertIn("Rule 23: Merging distinct skills is worse than leaving them separate", out)

            # 3. Ready-to-paste YAML printed for clean proposal
            self.assertIn("skill_aliases:", out)
            self.assertIn('deutsch: "german"', out)

            # 4. Conflict detection flagged k8s re-aliasing / existing choice
            self.assertIn("CONFLICT DETECTED with existing config.yaml choice", out)
            self.assertIn("Variant 'k8s' already has an explicit alias entry in config.yaml", out)


if __name__ == "__main__":
    unittest.main()
