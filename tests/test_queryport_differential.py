"""Differential harness regression tests (no network or source engines)."""
import json
import unittest

from research.compare_sqlite_benchmarks import compare
from research.run_sqlite_differential import CASES, evaluate


class TestDifferentialHarness(unittest.TestCase):
    def test_current_queryport_matches_curated_oracles(self):
        cases = json.loads(CASES.read_text(encoding="utf-8"))["cases"]
        self.assertGreaterEqual(len(cases), 30)
        for case in cases:
            with self.subTest(case=case["id"]):
                outcome = evaluate(case)
                self.assertTrue(outcome["passed"], outcome)

    def test_comparator_detects_both_improvements_and_regressions(self):
        old = {"rows": [
            {"id": "x", "passed": False},
            {"id": "y", "passed": True},
            {"id": "z", "passed": False},
        ]}
        new = {"rows": [
            {"id": "x", "passed": True},
            {"id": "y", "passed": False},
            {"id": "z", "passed": False},
        ]}
        result = compare(old, new)
        self.assertEqual(result["improved"], ["x"])
        self.assertEqual(result["regressed"], ["y"])
        self.assertEqual(result["both_failing"], ["z"])
        with self.assertRaises(ValueError):
            compare(old, {"rows": [{"id": "missing", "passed": True}]})


if __name__ == "__main__":
    unittest.main()
