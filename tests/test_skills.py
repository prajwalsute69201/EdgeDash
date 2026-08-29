import unittest
from edgedash.skills import canonical


class TestSkills(unittest.TestCase):
    def setUp(self) -> None:
        self.aliases = {
            "k8s": "kubernetes",
            "js": "javascript",
            "node": "node.js",
            "nodejs": "node.js",
            "postgres": "postgres",
            "postgresql": "postgres",
            "psql": "postgres",
            "gcp": "gcp",
            "google cloud": "gcp",
            "google cloud platform": "gcp",
            "ml": "machine learning",
            "ci/cd": "ci/cd",
            "ci cd": "ci/cd",
            "cicd": "ci/cd",
        }

    def test_canonical_case(self) -> None:
        self.assertEqual(canonical("PYTHON", self.aliases), "python")
        self.assertEqual(canonical("PostgreSQL", self.aliases), "postgres")

    def test_canonical_whitespace(self) -> None:
        self.assertEqual(canonical("   sql   ", self.aliases), "sql")
        self.assertEqual(canonical("machine   learning", self.aliases), "machine learning")
        self.assertEqual(canonical("google   cloud", self.aliases), "gcp")

    def test_canonical_parentheses(self) -> None:
        self.assertEqual(canonical("kubernetes (eks)", self.aliases), "kubernetes")
        self.assertEqual(canonical("postgresql (v14.2)", self.aliases), "postgres")
        self.assertEqual(canonical("python (pandas/numpy)", self.aliases), "python")

    def test_canonical_aliased_term(self) -> None:
        self.assertEqual(canonical("k8s", self.aliases), "kubernetes")
        self.assertEqual(canonical("js", self.aliases), "javascript")
        self.assertEqual(canonical("psql", self.aliases), "postgres")
        self.assertEqual(canonical("ci cd", self.aliases), "ci/cd")

    def test_canonical_no_alias(self) -> None:
        self.assertEqual(canonical("c++", self.aliases), "c++")
        self.assertEqual(canonical("docker", self.aliases), "docker")
        self.assertEqual(canonical("tableau", self.aliases), "tableau")

    def test_canonical_empty_string(self) -> None:
        self.assertEqual(canonical("", self.aliases), "")
        self.assertEqual(canonical("   ", self.aliases), "")
        self.assertEqual(canonical(None, self.aliases), "")

    def test_node_javascript_separation(self) -> None:
        # Node and Javascript MUST be separate
        self.assertEqual(canonical("node", self.aliases), "node.js")
        self.assertEqual(canonical("nodejs", self.aliases), "node.js")
        self.assertEqual(canonical("js", self.aliases), "javascript")
        self.assertNotEqual(canonical("node", self.aliases), "javascript")


if __name__ == "__main__":
    unittest.main()
