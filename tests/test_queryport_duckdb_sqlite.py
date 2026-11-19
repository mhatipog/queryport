"""Guard canonical DuckDB to SQLite conversions independently of live engine tests."""
import sqlite3
import unittest

from sqlglot import exp, parse_one
from sqlglot.errors import ErrorLevel, UnsupportedError


class TestQueryPortDuckDBSQLite(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")

    def tearDown(self):
        self.con.close()

    def check(self, source: str, expected):
        converted = parse_one(source, read="duckdb").sql(
            "sqlite", unsupported_level=ErrorLevel.RAISE
        )
        actual = self.con.execute(converted).fetchone()[0]
        self.assertEqual(actual, expected, converted)

    def test_truncation_calendar_boundaries(self):
        for source, expected in (
            ("SELECT DATE_TRUNC('week', DATE '2024-01-01')", "2024-01-01"),
            ("SELECT DATE_TRUNC('week', DATE '2024-01-07')", "2024-01-01"),
            ("SELECT DATE_TRUNC('week', DATE '2024-01-08')", "2024-01-08"),
            ("SELECT DATE_TRUNC('month', DATE '2024-02-29')", "2024-02-01"),
            ("SELECT DATE_TRUNC('quarter', DATE '2024-05-19')", "2024-04-01"),
            ("SELECT DATE_TRUNC('year', DATE '2024-05-19')", "2024-01-01"),
        ):
            with self.subTest(source=source):
                self.check(source, expected)

    def test_extract(self):
        for source, expected in (
            ("SELECT EXTRACT(YEAR FROM DATE '2024-03-31')", 2024),
            ("SELECT EXTRACT(QUARTER FROM DATE '2024-03-31')", 1),
            ("SELECT EXTRACT(MONTH FROM DATE '2024-03-31')", 3),
            ("SELECT EXTRACT(DAY FROM DATE '2024-03-31')", 31),
            ("SELECT EXTRACT(DAYOFYEAR FROM DATE '2024-12-31')", 366),
        ):
            with self.subTest(source=source):
                self.check(source, expected)

    def test_interval_month_clamping(self):
        for source, expected in (
            ("SELECT DATE '2024-01-31' + INTERVAL 1 MONTH", "2024-02-29"),
            ("SELECT DATE '2024-03-31' - INTERVAL 1 MONTH", "2024-02-29"),
            ("SELECT DATE '2024-02-29' + INTERVAL 1 YEAR", "2025-02-28"),
        ):
            with self.subTest(source=source):
                converted = parse_one(source, read="duckdb").sql("sqlite")
                value = self.con.execute(converted).fetchone()[0]
                self.assertEqual(value[:10], expected, converted)

    def test_week_date_diff_retains_source_semantics(self):
        for start, end, expected in (
            ("2024-01-01", "2024-01-07", 0),
            ("2024-01-01", "2024-01-08", 1),
            ("2024-01-01", "2024-01-14", 1),
            ("2024-01-14", "2024-01-01", -1),
        ):
            sql = f"SELECT DATE_DIFF('week', DATE '{start}', DATE '{end}')"
            with self.subTest(sql=sql):
                self.check(sql, expected)

    def test_tsql_week_semantics_are_not_guessed(self):
        sql = "SELECT DATEDIFF(week, '2024-01-06', '2024-01-07')"
        expr = parse_one(sql, read="tsql")
        with self.assertRaises(UnsupportedError):
            expr.sql("sqlite", unsupported_level=ErrorLevel.RAISE)


if __name__ == "__main__":
    unittest.main()
