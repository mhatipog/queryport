"""Live DuckDB→SQLite string, ISO-week and month-end execution checks."""
from __future__ import annotations

import datetime as dt
import sqlite3
import unittest

import duckdb
from sqlglot import parse_one
from sqlglot.errors import ErrorLevel


def _normalize(x):
    if isinstance(x, dt.datetime):
        return x.isoformat(sep=" ")
    if isinstance(x, dt.date):
        return x.isoformat()
    if isinstance(x, bool):
        return int(x)
    return x


class TestQueryPortSQLiteTextIso(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.duck = duckdb.connect(":memory:")
        cls.sqlite = sqlite3.connect(":memory:")
        cls.duck.execute("CREATE TABLE t(id INTEGER, s VARCHAR, s2 VARCHAR, n INT, d DATE)")
        cls.sqlite.execute("CREATE TABLE t(id INTEGER, s TEXT, s2 TEXT, n INT, d TEXT)")
        cls.rows = [
            (0, "abcd", "xyz", 2, "2020-12-31"),
            (1, "abcd", "", -2, "2021-01-01"),
            (2, "", "", 0, "2021-01-04"),
            (3, None, "x", None, "2024-02-29"),
            (4, "café", None, 10, "2024-12-31"),
            (5, "abc", "abc", -10, "2024-01-01"),
            (6, "x", "x", 1, "2000-01-01"),
            (7, "a", "b", -1, None),
            (8, None, None, 5, "2023-12-31"),
        ]
        cls.duck.executemany("INSERT INTO t VALUES (?, ?, ?, ?, ?)", cls.rows)
        cls.sqlite.executemany("INSERT INTO t VALUES (?, ?, ?, ?, ?)", cls.rows)

    @classmethod
    def tearDownClass(cls):
        cls.duck.close()
        cls.sqlite.close()

    def assert_engine_equivalence(self, expression: str):
        source = "SELECT " + expression + " FROM t ORDER BY id"
        target = parse_one(source, read="duckdb").sql(
            "sqlite", unsupported_level=ErrorLevel.RAISE
        )
        original = [_normalize(row[0]) for row in self.duck.execute(source).fetchall()]
        converted = [_normalize(row[0]) for row in self.sqlite.execute(target).fetchall()]
        self.assertEqual(original, converted, (source, target))

    def test_string_slicing_including_negative_lengths_and_nulls(self):
        for expr in (
            "LEFT(s, 2)", "LEFT(s, -2)", "LEFT(s, 0)", "LEFT(s, 10)",
            "RIGHT(s, 2)", "RIGHT(s, -2)", "RIGHT(s, 0)", "RIGHT(s, 10)",
            "LEFT(s, n)", "RIGHT(s, n)",
        ):
            with self.subTest(expr=expr):
                self.assert_engine_equivalence(expr)

    def test_prefix_suffix_and_null_behavior(self):
        for expr in (
            "STARTS_WITH(s, 'a')", "STARTS_WITH(s, '')",
            "ENDS_WITH(s, 'd')", "ENDS_WITH(s, '')",
            "STARTS_WITH(s, NULL)", "ENDS_WITH(s, NULL)",
        ):
            with self.subTest(expr=expr):
                self.assert_engine_equivalence(expr)

    def test_concat_ws_including_empty_fields(self):
        for expr in (
            "CONCAT_WS('-', s, s2)",
            "CONCAT_WS('-', s, NULL, s2)",
            "CONCAT_WS('', s, s2)",
            "CONCAT_WS(NULL, s, s2)",
            "CONCAT_WS('-', '', '')",
        ):
            with self.subTest(expr=expr):
                self.assert_engine_equivalence(expr)

    def test_iso_calendar_and_last_day(self):
        for expr in (
            "EXTRACT(ISODOW FROM d)",
            "EXTRACT(WEEK FROM d)",
            "EXTRACT(ISOYEAR FROM d)",
            "LAST_DAY(d)",
        ):
            with self.subTest(expr=expr):
                self.assert_engine_equivalence(expr)


if __name__ == "__main__":
    unittest.main()
