"""Live DuckDB and SQLite regression oracles for opt-in QueryPort porting."""
from __future__ import annotations

import datetime as dt
import sqlite3
import random
import unittest

import duckdb

from sqlglot.queryport_duckdb_sqlite import (
    DuckDBPortResult,
    UnsafeDuckDBPort,
    port_duckdb_to_sqlite,
)


def _norm(value):
    if isinstance(value, dt.datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, dt.date):
        return value.isoformat()
    return value


class TestDuckDBToSQLiteOptIn(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.duck = duckdb.connect(":memory:")
        cls.sqlite = sqlite3.connect(":memory:")
        cls.schema = {"t": {"id": "INTEGER", "d": "DATE", "s": "VARCHAR"}}
        cls.duck.execute("CREATE TABLE t (id INTEGER, d DATE, s VARCHAR)")
        cls.sqlite.execute("CREATE TABLE t (id INTEGER, d TEXT, s TEXT)")
        cls.rows = [
            (0, "2024-01-31", "a:b"),
            (1, "2024-02-29", "café"),
            (2, "2023-12-31", ""),
            (3, "2020-02-29", "İstanbul"),
            (4, "1999-01-01", "ß"),
            (5, "2024-03-01", "a\u0301"),
            (6, None, None),
            (7, "2024-01-01", "longer-than-eight"),
        ]
        rng = random.Random(20261120)
        alphabet = ("a", "é", "ß", "💾", "e\\u0301", "0", " ", "'", "あ", "\\n")
        for k in range(500):
            date = dt.date(1901, 1, 1) + dt.timedelta(days=rng.randrange(0, 60000))
            size = rng.randrange(0, 18)
            word = "".join(rng.choice(alphabet) for _ in range(size))
            cls.rows.append((k + 8, date.isoformat(), word))
        cls.duck.executemany("INSERT INTO t VALUES (?, ?, ?)", cls.rows)
        cls.sqlite.executemany("INSERT INTO t VALUES (?, ?, ?)", cls.rows)

    @classmethod
    def tearDownClass(cls):
        cls.duck.close()
        cls.sqlite.close()

    def check_equivalent(self, expression, *, expected_date=0, expected_pad=0):
        source = f"SELECT {expression} FROM t ORDER BY id"
        result = port_duckdb_to_sqlite(source, schema=self.schema)
        self.assertIsInstance(result, DuckDBPortResult)
        self.assertEqual(result.rewritten_date_timestamp, expected_date, source)
        self.assertEqual(result.rewritten_padding, expected_pad, source)
        self.assertEqual(result.unresolved, ())
        self.assertFalse(result.semantic_equivalence_proven)
        src = [_norm(row[0]) for row in self.duck.execute(source).fetchall()]
        target = [_norm(row[0]) for row in self.sqlite.execute(result.sql[0]).fetchall()]
        self.assertEqual(src, target, (expression, result.sql[0]))
        return result.sql[0]

    def test_dateadd_timestamp_result_around_leap_and_month_boundaries(self):
        for expr in (
            "DATE_ADD(d, INTERVAL 1 MONTH)",
            "DATE_ADD(d, INTERVAL 1 YEAR)",
            "d + INTERVAL 1 DAY",
            "INTERVAL 1 DAY + d",
            "d + INTERVAL 1 MONTH",
        ):
            with self.subTest(expr=expr):
                self.check_equivalent(expr, expected_date=1)

    def test_padding_null_unicode_empty_and_truncation(self):
        for expr in (
            "LPAD(s, 5, '_')",
            "RPAD(s, 5, '_')",
            "LPAD(s, 1, 'x')",
            "RPAD(s, 8, 'y')",
            "LPAD(s, 0, 'z')",
            "LPAD(s, 14, 'é')",
            "RPAD(s, 14, '💾')",
            "LPAD(s, 7, ' ')",
            "RPAD(s, 0, 'z')",
            "LPAD('abc', 6, '-')",
            "RPAD('café', 6, '*')",
        ):
            with self.subTest(expr=expr):
                self.check_equivalent(expr, expected_pad=1)

    def test_unknown_types_or_pads_are_not_silently_rewritten(self):
        for expr, schema in (
            ("LPAD(s, 5, '_')", None),
            ("LPAD(s, 5, 'xy')", self.schema),
            ("RPAD(s, -1, '_')", self.schema),
            ("LPAD(s, 100000, '_')", self.schema),
            ("LPAD(s, n, '_')", self.schema),
            ("SPLIT_PART(s, ':', 1)", self.schema),
            ("REVERSE(s)", self.schema),
            ("REGEXP_REPLACE(s, '[ab]', 'x')", self.schema),
        ):
            with self.subTest(expr=expr):
                with self.assertRaises(UnsafeDuckDBPort):
                    port_duckdb_to_sqlite(f"SELECT {expr} FROM t", schema=schema)

    def test_original_native_sqlite_and_numeric_subtraction_untouched(self):
        result = port_duckdb_to_sqlite("SELECT id - 3 FROM t", schema=self.schema)
        self.assertEqual(result.rewritten_date_timestamp, 0)
        self.assertEqual(result.rewritten_padding, 0)
        self.assertEqual(
            [r[0] for r in self.sqlite.execute(result.sql[0])],
            [r[0] for r in self.duck.execute("SELECT id - 3 FROM t").fetchall()],
        )

    def test_unchecked_mode_reports_unhandled_function(self):
        result = port_duckdb_to_sqlite(
            "SELECT SPLIT_PART(s, ':', 1) FROM t", schema=self.schema, strict=False
        )
        self.assertTrue(any("SplitPart" in issue for issue in result.unresolved))
        self.assertFalse(result.semantic_equivalence_proven)


if __name__ == "__main__":
    unittest.main()
