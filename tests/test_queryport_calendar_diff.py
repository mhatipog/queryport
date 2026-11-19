"""QueryPort regression and property tests for cross-dialect calendar DATEDIFF.

These tests execute transpiled queries in real SQLite against independent Python
datetime/calendar reference values; SQLite parser acceptance alone is not sufficient.
"""
import datetime as dt
import random
import sqlite3
import unittest

from sqlglot import transpile


START = dt.datetime(1990, 1, 1)


def boundary_difference(end: dt.datetime, start: dt.datetime, unit: str) -> int:
    if unit == "year":
        return end.year - start.year
    if unit == "quarter":
        return (end.year * 4 + (end.month - 1) // 3) - (
            start.year * 4 + (start.month - 1) // 3
        )
    if unit == "month":
        return (end.year * 12 + end.month) - (start.year * 12 + start.month)
    if unit == "day":
        return (end.date() - start.date()).days
    truncate = {
        "hour": lambda a: a.replace(minute=0, second=0, microsecond=0),
        "minute": lambda a: a.replace(second=0, microsecond=0),
        "second": lambda a: a.replace(microsecond=0),
    }[unit]
    seconds = {"hour": 3600, "minute": 60, "second": 1}[unit]
    return int((truncate(end) - truncate(start)).total_seconds() / seconds)


class QueryPortSQLiteCalendarDiff(unittest.TestCase):
    def test_sql_server_boundary_semantics_against_independent_oracle(self):
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE events (start_ts TEXT, end_ts TEXT)")
        r = random.Random(20261119)
        pairs = [
            (dt.datetime(2023, 12, 31, 23, 59, 59, 900000),
             dt.datetime(2024, 1, 1, 0, 0, 0, 100000)),
            (dt.datetime(2024, 2, 28, 23, 59, 59),
             dt.datetime(2024, 3, 1, 0, 0, 0)),
            (dt.datetime(2024, 2, 29, 23, 59, 59),
             dt.datetime(2024, 3, 1, 0, 0, 1)),
            (dt.datetime(2024, 1, 31, 12), dt.datetime(2024, 2, 1, 12)),
            (dt.datetime(2024, 1, 1, 0, 59, 59),
             dt.datetime(2024, 1, 1, 1, 0, 1)),
            (dt.datetime(2024, 2, 1), dt.datetime(2024, 1, 31, 23, 59, 59)),
        ]
        pairs += [
            (
                START + dt.timedelta(seconds=r.randrange(0, 1_200_000_000),
                                     microseconds=r.randrange(1_000_000)),
                START + dt.timedelta(seconds=r.randrange(0, 1_200_000_000),
                                     microseconds=r.randrange(1_000_000)),
            )
            for _ in range(2000)
        ]
        con.executemany(
            "INSERT INTO events VALUES (?, ?)",
            [(a.isoformat(sep=" "), b.isoformat(sep=" ")) for a, b in pairs],
        )
        for unit in ("year", "quarter", "month", "day", "hour", "minute", "second"):
            # SQL Server start comes before end. SQLGlot's DateDiff AST normalizes
            # to this/expression; executing here also tests that argument order.
            query = (
                f"SELECT DATEDIFF({unit}, start_ts, end_ts) AS value "
                "FROM events ORDER BY rowid"
            )
            converted = transpile(query, read="tsql", write="sqlite")[0]
            with self.subTest(unit=unit, converted=converted):
                actual = [row[0] for row in con.execute(converted)]
                expect = [boundary_difference(end, start, unit) for start, end in pairs]
                self.assertEqual(actual, expect)

    def test_null_propagation(self):
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE events (start_ts TEXT, end_ts TEXT)")
        con.executemany("INSERT INTO events VALUES (?, ?)", [
            (None, "2024-01-01 00:00:00"),
            ("2024-01-01 00:00:00", None),
            (None, None),
        ])
        for unit in ("year", "quarter", "month", "day", "hour", "minute", "second"):
            query = f"SELECT DATEDIFF({unit}, start_ts, end_ts) FROM events"
            converted = transpile(query, read="tsql", write="sqlite")[0]
            with self.subTest(unit=unit):
                self.assertEqual([row[0] for row in con.execute(converted)],
                                 [None, None, None])

    def test_source_dates_can_be_cast_or_text(self):
        con = sqlite3.connect(":memory:")
        for read, query, expected in (
            ("duckdb", "SELECT DATE_DIFF('month', DATE '2023-12-31', DATE '2024-01-01')", 1),
            ("tsql", "SELECT DATEDIFF(month, '2024-01-31', '2024-02-01')", 1),
            ("tsql", "SELECT DATEDIFF(year, '2023-12-31', '2024-01-01')", 1),
            ("tsql", "SELECT DATEDIFF(day, '2024-01-01 23:59:59', '2024-01-02 00:00:01')", 1),
            ("tsql", "SELECT DATEDIFF(second, '2024-01-01 00:00:00.900', '2024-01-01 00:00:01.100')", 1),
        ):
            converted = transpile(query, read=read, write="sqlite")[0]
            with self.subTest(query=query, converted=converted):
                self.assertEqual(con.execute(converted).fetchone()[0], expected)


if __name__ == "__main__":
    unittest.main()
