import importlib.util
import tempfile
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location("cira_run_state", Path(__file__).resolve().parents[1] / "portfolio-engine" / "run_state.py")
rs = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(rs)


class RunStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original = (rs.STATE, rs.universe_tickers)
        rs.STATE = Path(self.tmp.name) / "run-exclusions.json"
        self.universe = [f"T{i}" for i in range(12)]
        rs.universe_tickers = lambda: list(self.universe)

    def tearDown(self):
        rs.STATE, rs.universe_tickers = self.original
        self.tmp.cleanup()

    def test_no_state_means_all_active(self):
        self.assertEqual(rs.active_tickers(), tuple(self.universe))

    def test_exclude_removes_from_active_and_keeps_first_reason(self):
        rs.reset()
        rs.exclude("T3", "market-prices", "HTTP 404")
        rs.exclude("T3", "market-analysis", "later stage")
        self.assertNotIn("T3", rs.active_tickers())
        self.assertEqual(rs.exclusions()["T3"]["stage"], "market-prices")

    def test_reset_clears_previous_run(self):
        rs.exclude("T1", "x", "y")
        rs.reset()
        self.assertEqual(rs.exclusions(), {})

    def test_threshold_allows_one_of_twelve(self):
        rs.reset()
        rs.exclude("T0", "financial-report", "No annual revenue period found")
        self.assertIn("T0", rs.check_threshold())

    def test_threshold_rejects_two_of_twelve(self):
        rs.reset()
        rs.exclude("T0", "a", "b")
        rs.exclude("T1", "a", "b")
        with self.assertRaises(RuntimeError):
            rs.check_threshold()

    def test_limit_scales_with_universe(self):
        self.assertEqual(rs.allowed_exclusions(12), 1)
        self.assertEqual(rs.allowed_exclusions(67), 6)

    def test_reason_is_sanitised_and_bounded(self):
        rs.reset()
        rs.exclude("T2", "s", "line1\nline2 " + "x" * 500)
        reason = rs.exclusions()["T2"]["reason"]
        self.assertNotIn("\n", reason)
        self.assertLessEqual(len(reason), 300)


if __name__ == "__main__":
    unittest.main()
