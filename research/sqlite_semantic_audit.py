"""OCI-reproducible SQLGlot SQLite semantic audit.

Run: python3 research/sqlite_semantic_audit.py
Only Python's stdlib and the checked-out SQLGlot are required.
An expected failure records the unresolved cross-dialect DATE subtraction issue.
"""
from __future__ import annotations

import datetime as dt
import random
import sqlite3
import statistics
import unittest

from sqlglot import parse_one, transpile

RANDOM_MASK = 9007199254740991
RANDOM_DENOM = 9007199254740992


class SQLiteSemanticAudit(unittest.TestCase):
    def test_random_dialect_equivalence(self):
        outputs = {
            read: parse_one(f"SELECT {function} < 0.1", read=read).sql("sqlite")
            for read, function in (
                ("mysql", "RAND()"),
                ("postgres", "RANDOM()"),
                ("bigquery", "RAND()"),
            )
        }
        self.assertEqual(len(set(outputs.values())), 1, outputs)
        for value in outputs.values():
            self.assertIn("9007199254740991", value)
            self.assertIn("RANDOM()", value)
        self.assertEqual(parse_one("SELECT RANDOM()", read="sqlite").sql("sqlite"), "SELECT RANDOM()")

    def test_random_extreme_integer_values(self):
        expr = parse_one("RAND()", read="mysql").sql("sqlite")
        with sqlite3.connect(":memory:") as conn:
            for raw, expected in (
                (-9223372036854775807, 2**-53),
                (-1, 1 - 2**-53),
                (0, 0.0),
                (1, 2**-53),
                (9223372036854775807, 1 - 2**-53),
            ):
                with self.subTest(raw=raw):
                    conn.create_function("RANDOM", 0, lambda value=raw: value)
                    result = conn.execute("SELECT " + expr).fetchone()[0]
                    self.assertIsInstance(result, float)
                    self.assertEqual(result, expected)
                    self.assertTrue(0 <= result < 1)

    def test_random_distribution_50000(self):
        expr = parse_one("RAND()", read="postgres").sql("sqlite")
        rng = random.Random(20261119)
        with sqlite3.connect(":memory:") as conn:
            conn.create_function(
                "RANDOM", 0, lambda: rng.randrange(-(2**63 - 1), 2**63)
            )
            samples = [conn.execute("SELECT " + expr).fetchone()[0] for _ in range(50_000)]
        self.assertTrue(all(0 <= x < 1 for x in samples))
        mean = statistics.fmean(samples)
        below_tenth = sum(x < 0.1 for x in samples) / len(samples)
        hist = [sum(i / 10 <= x < (i + 1) / 10 for x in samples) for i in range(10)]
        chi_square = sum((count - 5000) ** 2 / 5000 for count in hist)
        print(
            f"random: n=50000 mean={mean:.6f}, P(x<0.1)={below_tenth:.6f}, "
            f"chi2_10bins={chi_square:.4f}", flush=True
        )
        self.assertLess(abs(mean - 0.5), 0.01)
        self.assertTrue(0.09 < below_tenth < 0.11)
        self.assertLess(chi_square, 35)

    def test_sqlite_date_difference_arithmetic_oracle_1000(self):
        rng = random.Random(20261119)
        with sqlite3.connect(":memory:") as conn:
            for _ in range(1000):
                a = dt.date(1990, 1, 1) + dt.timedelta(days=rng.randrange(25_000))
                b = dt.date(1990, 1, 1) + dt.timedelta(days=rng.randrange(25_000))
                value = conn.execute(
                    "SELECT CAST(JULIANDAY(DATE(?)) - JULIANDAY(DATE(?)) AS INTEGER)",
                    (a.isoformat(), b.isoformat()),
                ).fetchone()[0]
                self.assertEqual(value, (a - b).days)

    def test_date_diff_null_and_leap_year(self):
        with sqlite3.connect(":memory:") as conn:
            cases = [
                ("2024-03-01", "2024-02-01", 29),
                ("2023-03-01", "2023-02-01", 28),
                ("2024-01-01", "2023-12-01", 31),
                ("2023-12-01", "2024-01-01", -31),
                ("2024-01-01", "2024-01-01", 0),
                (None, "2024-01-01", None),
                ("2024-01-01", None, None),
            ]
            for left, right, expected in cases:
                with self.subTest(left=left, right=right):
                    value = conn.execute(
                        "SELECT CAST(JULIANDAY(DATE(?)) - JULIANDAY(DATE(?)) AS INTEGER)",
                        (left, right),
                    ).fetchone()[0]
                    self.assertEqual(value, expected)

    @unittest.expectedFailure
    def test_unresolved_postgres_date_subtraction_transpilation(self):
        # https://github.com/tobymao/sqlglot/issues/9259
        source = "SELECT CAST('2024-03-01' AS DATE) - CAST('2024-02-01' AS DATE)"
        sqlite_sql = transpile(source, read="postgres", write="sqlite")[0]
        with sqlite3.connect(":memory:") as conn:
            observed = conn.execute(sqlite_sql).fetchone()[0]
        print(f"known issue #9259: {sqlite_sql!r} returned {observed!r}, expected 29", flush=True)
        self.assertEqual(observed, 29)


if __name__ == "__main__":
    unittest.main(verbosity=2)
