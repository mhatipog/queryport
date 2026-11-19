"""QueryPort month-end calendar arithmetic regression tests against real SQLite."""
import calendar
import datetime as dt
import random
import sqlite3
import unittest

from sqlglot import transpile


def add_months(reference: dt.datetime, offset: int, preserve_eom: bool) -> dt.datetime:
    destination = reference.year * 12 + reference.month - 1 + offset
    year, month = divmod(destination, 12)
    month += 1
    last = calendar.monthrange(year, month)[1]
    original_last = calendar.monthrange(reference.year, reference.month)[1]
    day = (
        last if preserve_eom and reference.day == original_last
        else min(reference.day, last)
    )
    return reference.replace(year=year, month=month, day=day)


class TestMonthEndPortability(unittest.TestCase):
    def test_4000_cross_dialect_cases_against_calendar(self):
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE months (id INTEGER, d TEXT, n INT)")
        rng = random.Random(20261119)
        entries = [
            (dt.datetime(2024, 1, 31), 1),
            (dt.datetime(2024, 2, 29), 1),
            (dt.datetime(2023, 2, 28), 1),
            (dt.datetime(2024, 3, 30), -1),
            (dt.datetime(2024, 3, 31), -1),
            (dt.datetime(2024, 2, 29, 12, 34, 56), 12),
        ]
        entries += [
            (
                dt.datetime(1990, 1, 1) + dt.timedelta(
                    days=rng.randrange(0, 13000),
                    seconds=rng.randrange(0, 86400),
                ),
                rng.randrange(-72, 73),
            )
            for _ in range(1000)
        ]
        con.executemany(
            "INSERT INTO months VALUES (?, ?, ?)",
            [(i, value.isoformat(sep=" "), number) for i, (value, number) in enumerate(entries)],
        )
        cases = (
            ("oracle", "SELECT ADD_MONTHS(d, n) FROM months ORDER BY id", True),
            ("spark", "SELECT ADD_MONTHS(d, n) FROM months ORDER BY id", False),
            ("mysql", "SELECT DATE_ADD(d, INTERVAL n MONTH) FROM months ORDER BY id", False),
            ("tsql", "SELECT DATEADD(month, n, d) FROM months ORDER BY id", False),
        )
        for dialect, query, eom in cases:
            converted = transpile(query, read=dialect, write="sqlite")[0]
            with self.subTest(dialect=dialect, sql=converted):
                values = [row[0] for row in con.execute(converted)]
                expected = [add_months(value, n, eom) for value, n in entries]
                # SQLGlot may cast a T-SQL DATEADD operand to DATETIME even when
                # the original source column type isn't known. Compare full date
                # and time for strings containing a time component; all fixtures
                # deliberately contain non-timezone datetime strings.
                self.assertEqual(
                    [item.replace("T", " ") if item else item for item in values],
                    [item.isoformat(sep=" ") for item in expected],
                )

    def test_nulls_propagate(self):
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE t (d TEXT, n INT)")
        con.executemany("INSERT INTO t VALUES (?, ?)", [
            (None, 1), ("2024-01-31", None), (None, None),
        ])
        for dialect, query in (
            ("oracle", "SELECT ADD_MONTHS(d, n) FROM t"),
            ("spark", "SELECT ADD_MONTHS(d, n) FROM t"),
            ("mysql", "SELECT DATE_ADD(d, INTERVAL n MONTH) FROM t"),
        ):
            converted = transpile(query, read=dialect, write="sqlite")[0]
            with self.subTest(dialect=dialect):
                self.assertEqual([row[0] for row in con.execute(converted)],
                                 [None, None, None])

    def test_year_shift_clips_leap_day(self):
        con = sqlite3.connect(":memory:")
        for dialect, sql in (
            ("tsql", "SELECT DATEADD(year, 1, '2024-02-29')"),
            ("mysql", "SELECT DATE_ADD('2024-02-29', INTERVAL 1 YEAR)"),
        ):
            converted = transpile(sql, read=dialect, write="sqlite")[0]
            with self.subTest(dialect=dialect, converted=converted):
                result = con.execute(converted).fetchone()[0]
                self.assertEqual(result[:10], "2025-02-28")


if __name__ == "__main__":
    unittest.main()
