"""Executed 5,000+ DATE-minus-DATE property fixtures for QueryPort.

Tests distinguish independent date-subtraction semantics from mere SQLGlot
round-trip equality. No live PostgreSQL/DuckDB engine is required for the
documented date-to-date integer-day operation.
"""
from __future__ import annotations

import datetime as dt
import random
import sqlite3
import unittest

from sqlglot.queryport_port import DatePortResult, port_date_subtraction


class TestDateSubtractionPort(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.connection = sqlite3.connect(":memory:")
        cls.connection.execute("CREATE TABLE events (d1 TEXT, d2 TEXT, x INTEGER, y INTEGER)")
        r = random.Random(20261119)
        origin = dt.date(1900, 1, 1)
        cls.rows = [
            (dt.date(2024, 2, 1), dt.date(2024, 3, 1), 12, 7),
            (dt.date(2024, 2, 29), dt.date(2024, 3, 1), 1, 9),
            (dt.date(2000, 1, 1), dt.date(1999, 12, 31), -5, 20),
        ]
        cls.rows += [
            (
                origin + dt.timedelta(days=r.randrange(0, 66000)),
                origin + dt.timedelta(days=r.randrange(0, 66000)),
                r.randrange(-1000000, 1000000),
                r.randrange(-1000000, 1000000),
            )
            for _ in range(2500)
        ]
        cls.connection.executemany(
            "INSERT INTO events VALUES (?, ?, ?, ?)",
            [(a.isoformat(), b.isoformat(), x, y) for a, b, x, y in cls.rows],
        )

    @classmethod
    def tearDownClass(cls):
        cls.connection.close()

    def _assert_days(self, read: str, sql: str, schema=None):
        result = port_date_subtraction(sql, read=read, schema=schema)
        self.assertIsInstance(result, DatePortResult)
        self.assertEqual(result.date_subtractions_rewritten, 1, result)
        self.assertFalse(result.engine_executed)
        self.assertFalse(result.semantic_equivalence_proven)
        actual = [row[0] for row in self.connection.execute(result.sql[0])]
        expected = [(b - a).days for a, b, _, _ in self.rows]
        self.assertEqual(actual, expected)

    def test_explicit_casts_postgres_and_duckdb(self):
        for dialect in ("postgres", "duckdb"):
            with self.subTest(dialect=dialect):
                self._assert_days(
                    dialect,
                    "SELECT CAST(d2 AS DATE) - CAST(d1 AS DATE) FROM events ORDER BY rowid",
                )

    def test_schema_typed_columns_postgres_and_duckdb(self):
        schema = {"events": {"d1": "DATE", "d2": "DATE", "x": "INT", "y": "INT"}}
        for dialect in ("postgres", "duckdb"):
            with self.subTest(dialect=dialect):
                self._assert_days(dialect,
                                  "SELECT d2 - d1 FROM events ORDER BY rowid", schema)

    def test_date_literals_and_null(self):
        for dialect in ("postgres", "duckdb"):
            with self.subTest(dialect=dialect):
                result = port_date_subtraction(
                    "SELECT DATE '2024-03-01' - DATE '2024-02-01'",
                    read=dialect,
                )
                self.assertEqual(self.connection.execute(result.sql[0]).fetchone()[0], 29)
                self.assertEqual(result.date_subtractions_rewritten, 1)

                result = port_date_subtraction(
                    "SELECT CAST(NULL AS DATE) - CAST('2024-01-01' AS DATE)", read=dialect
                )
                self.assertIsNone(self.connection.execute(result.sql[0]).fetchone()[0])

    def test_numeric_subtraction_unchanged(self):
        for dialect in ("postgres", "duckdb"):
            with self.subTest(dialect=dialect):
                result = port_date_subtraction(
                    "SELECT y - x FROM events ORDER BY rowid",
                    read=dialect,
                    schema={"events": {"x": "INT", "y": "INT"}},
                )
                self.assertEqual(result.date_subtractions_rewritten, 0)
                actual = [r[0] for r in self.connection.execute(result.sql[0])]
                self.assertEqual(actual, [y - x for _, _, x, y in self.rows])

    def test_schema_unavailable_returns_uncertainty(self):
        result = port_date_subtraction(
            "SELECT d2 - d1 FROM events", read="postgres",
        )
        self.assertEqual(result.date_subtractions_rewritten, 0)
        self.assertEqual(result.untyped_subtractions, 1)
        self.assertFalse(result.semantic_equivalence_proven)

    def test_integer_constants_and_mixed_date_arithmetic_not_rewritten(self):
        cases = (
            "SELECT 12 - 9",
            "SELECT CAST('2024-02-01' AS DATE) - 1",
            "SELECT 12 - CAST('2024-02-01' AS DATE)",
        )
        for sql in cases:
            with self.subTest(sql=sql):
                result = port_date_subtraction(sql, read="postgres")
                self.assertEqual(result.date_subtractions_rewritten, 0)

    def test_multi_statement_and_invalid_source_rejected(self):
        result = port_date_subtraction(
            "SELECT CAST('2024-03-01' AS DATE) - CAST('2024-02-01' AS DATE); SELECT 2-1",
            read="duckdb",
        )
        self.assertEqual(len(result.sql), 2)
        self.assertEqual(result.date_subtractions_rewritten, 1)
        with self.assertRaises(ValueError):
            port_date_subtraction("SELECT 1", read="mysql")


if __name__ == "__main__":
    unittest.main()
