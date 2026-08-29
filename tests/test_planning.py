from datetime import datetime, timezone
import unittest

from edgedash.config import Config
from edgedash.planning import build_plan
from edgedash.state import SystemState


class TestPlanning(unittest.TestCase):
    def setUp(self) -> None:
        self.config = Config(
            fetch_interval_hours=6.0,
            max_fetch_pages=5,
            max_fetch_listings=100,
            score_batch_size=50,
            max_score_seconds=60,
            max_analyse_seconds=30,
        )
        self.now = datetime(2026, 8, 24, 12, 0, 0, tzinfo=timezone.utc)

    def test_everything_stale(self) -> None:
        state = SystemState(
            last_fetch_at=datetime(2026, 8, 24, 0, 0, 0, tzinfo=timezone.utc),  # 12 hours ago
            hours_since_fetch=12.0,
            unscored_count=15,
            gaps_computed_at=datetime(2026, 8, 24, 1, 0, 0, tzinfo=timezone.utc),
            gaps_stale=True,
            last_cycle_verdict="ok",
            last_cycle_at=datetime(2026, 8, 24, 10, 0, 0, tzinfo=timezone.utc),
        )

        plan = build_plan(state, self.config)

        self.assertEqual(len(plan.tasks), 3)
        self.assertEqual(plan.tasks[0].agent_name, "Fetcher")
        self.assertEqual(plan.tasks[0].action, "run")
        self.assertIn("hours_since_fetch=12.0 >= 6.0h", plan.tasks[0].reason)

        self.assertEqual(plan.tasks[1].agent_name, "Scorer")
        self.assertEqual(plan.tasks[1].action, "run")
        self.assertEqual(plan.tasks[1].reason, "unscored_count=15")

        self.assertEqual(plan.tasks[2].agent_name, "GapAnalyzer")
        self.assertEqual(plan.tasks[2].action, "run")
        self.assertEqual(plan.tasks[2].reason, "gaps_stale=True (new scores detected)")

    def test_nothing_to_do(self) -> None:
        state = SystemState(
            last_fetch_at=datetime(2026, 8, 24, 10, 0, 0, tzinfo=timezone.utc),  # 2 hours ago
            hours_since_fetch=2.0,
            unscored_count=0,
            gaps_computed_at=datetime(2026, 8, 24, 11, 0, 0, tzinfo=timezone.utc),
            gaps_stale=False,
            last_cycle_verdict="ok",
            last_cycle_at=datetime(2026, 8, 24, 11, 0, 0, tzinfo=timezone.utc),
        )

        plan = build_plan(state, self.config)

        self.assertEqual(len(plan.tasks), 3)
        self.assertEqual(plan.tasks[0].action, "skip")
        self.assertIn("skipped: hours_since_fetch=2.0 < 6.0h", plan.tasks[0].reason)

        self.assertEqual(plan.tasks[1].action, "skip")
        self.assertEqual(plan.tasks[1].reason, "skipped: unscored_count=0")

        self.assertEqual(plan.tasks[2].action, "skip")
        self.assertEqual(plan.tasks[2].reason, "skipped: gaps_stale=False")

        # Test rendering
        rendered = plan.render()
        self.assertIn("[SKIP]", rendered)
        self.assertIn("Fetcher", rendered)
        self.assertIn("Scorer", rendered)
        self.assertIn("GapAnalyzer", rendered)

    def test_only_unscored_listings(self) -> None:
        state = SystemState(
            last_fetch_at=datetime(2026, 8, 24, 10, 0, 0, tzinfo=timezone.utc),  # 2 hours ago
            hours_since_fetch=2.0,
            unscored_count=8,
            gaps_computed_at=datetime(2026, 8, 24, 11, 0, 0, tzinfo=timezone.utc),
            gaps_stale=False,
            last_cycle_verdict="ok",
            last_cycle_at=datetime(2026, 8, 24, 11, 0, 0, tzinfo=timezone.utc),
        )

        plan = build_plan(state, self.config)

        self.assertEqual(plan.tasks[0].action, "skip")
        self.assertEqual(plan.tasks[1].action, "run")
        self.assertEqual(plan.tasks[1].reason, "unscored_count=8")
        self.assertEqual(plan.tasks[2].action, "skip")

    def test_gaps_stale_nothing_unscored(self) -> None:
        state = SystemState(
            last_fetch_at=datetime(2026, 8, 24, 10, 0, 0, tzinfo=timezone.utc),  # 2 hours ago
            hours_since_fetch=2.0,
            unscored_count=0,
            gaps_computed_at=datetime(2026, 8, 24, 9, 0, 0, tzinfo=timezone.utc),
            gaps_stale=True,
            last_cycle_verdict="ok",
            last_cycle_at=datetime(2026, 8, 24, 11, 0, 0, tzinfo=timezone.utc),
        )

        plan = build_plan(state, self.config)

        self.assertEqual(plan.tasks[0].action, "skip")
        self.assertEqual(plan.tasks[1].action, "skip")
        self.assertEqual(plan.tasks[2].action, "run")
        self.assertEqual(plan.tasks[2].reason, "gaps_stale=True (new scores detected)")


if __name__ == "__main__":
    unittest.main()
