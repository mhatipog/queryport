#!/usr/bin/env python3
"""Actual DuckDB -> SQLite differential execution lab.

Unlike parser round-trips, source SQL is executed on DuckDB and transpiled SQL
on SQLite, using identical deterministic inputs. Calendar-date and integer
results are compared; timestamp time-of-day/type fidelity is a *separate gate*.
The initial run is exploratory and records failures without falsely passing them.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
import random
import sqlite3

import duckdb
from sqlglot import parse_one
from sqlglot.errors import ErrorLevel
from sqlglot.queryport_port import port_date_subtraction


SQL_CASES = (
    ("date_subtraction", "SELECT d2 - d1 FROM event_dates ORDER BY id", "source_date_port", "integer"),
    ("diff_days", "SELECT DATE_DIFF('day', d1, d2) FROM event_dates ORDER BY id", "transpile", "integer"),
    ("diff_months", "SELECT DATE_DIFF('month', d1, d2) FROM event_dates ORDER BY id", "transpile", "integer"),
    ("diff_years", "SELECT DATE_DIFF('year', d1, d2) FROM event_dates ORDER BY id", "transpile", "integer"),
    ("diff_quarters", "SELECT DATE_DIFF('quarter', d1, d2) FROM event_dates ORDER BY id", "transpile", "integer"),
    ("diff_weeks", "SELECT DATE_DIFF('week', d1, d2) FROM event_dates ORDER BY id", "transpile", "integer"),
    ("add_months_function", "SELECT DATE_ADD(d1, INTERVAL 1 MONTH) FROM event_dates ORDER BY id", "transpile", "date"),
    ("plus_month_interval", "SELECT d1 + INTERVAL 1 MONTH FROM event_dates ORDER BY id", "transpile", "date"),
    ("minus_month_interval", "SELECT d1 - INTERVAL 1 MONTH FROM event_dates ORDER BY id", "transpile", "date"),
    ("plus_day_interval", "SELECT d1 + INTERVAL 1 DAY FROM event_dates ORDER BY id", "transpile", "date"),
    ("trunc_month", "SELECT DATE_TRUNC('month', d1) FROM event_dates ORDER BY id", "transpile", "date"),
    ("extract_year", "SELECT EXTRACT(YEAR FROM d1) FROM event_dates ORDER BY id", "transpile", "integer"),
)


def _normalize(value, comparison: str):
    if value is None:
        return None
    if comparison == "integer":
        return int(value) if isinstance(value, int) and not isinstance(value, bool) else value
    if comparison == "date":
        if isinstance(value, dt.datetime):
            value = value.date()
        if isinstance(value, dt.date):
            return value.isoformat()
        if isinstance(value, str):
            return value[:10]
    return value


def _fixtures(count: int = 1200):
    rng = random.Random(20261119)
    origin = dt.date(2000, 1, 1)
    fixed = [
        (dt.date(2024, 1, 31), dt.date(2024, 2, 29)),
        (dt.date(2023, 2, 28), dt.date(2023, 3, 31)),
        (dt.date(2023, 12, 31), dt.date(2024, 1, 1)),
        (dt.date(2024, 3, 31), dt.date(2024, 2, 29)),
        (dt.date(2024, 2, 29), dt.date(2025, 2, 28)),
        (None, dt.date(2024, 1, 1)),
        (dt.date(2024, 1, 1), None),
        (None, None),
    ]
    fixed += [
        (
            origin + dt.timedelta(days=rng.randrange(0, 10956)),
            origin + dt.timedelta(days=rng.randrange(0, 10956)),
        )
        for _ in range(count)
    ]
    return [
        (i, a.isoformat() if a is not None else None, b.isoformat() if b is not None else None)
        for i, (a, b) in enumerate(fixed)
    ]


def evaluate(case, duck, sqlite):
    ident, sql, api, comparison = case
    record = {
        "id": ident, "comparison": comparison, "source_sql": sql,
        "target_sql": None, "source_executed": False, "target_executed": False,
        "equal": False, "mismatch_count": None, "examples": [], "error": None,
    }
    try:
        source_rows = duck.execute(sql).fetchall()
        record["source_executed"] = True
        if api == "source_date_port":
            conversion = port_date_subtraction(
                sql, read="duckdb",
                schema={"event_dates": {"d1": "DATE", "d2": "DATE", "id": "INT"}},
            )
            target_sql = conversion.sql[0]
        else:
            target_sql = parse_one(sql, read="duckdb").sql(
                "sqlite", unsupported_level=ErrorLevel.RAISE,
            )
        record["target_sql"] = target_sql
        target_rows = sqlite.execute(target_sql).fetchall()
        record["target_executed"] = True
        if len(source_rows) != len(target_rows):
            record["error"] = f"Cardinality mismatch: source={len(source_rows)}, target={len(target_rows)}"
            return record
        mismatches = [
            (i, _normalize(a[0], comparison), _normalize(b[0], comparison))
            for i, (a, b) in enumerate(zip(source_rows, target_rows))
            if _normalize(a[0], comparison) != _normalize(b[0], comparison)
        ]
        record["mismatch_count"] = len(mismatches)
        record["equal"] = not mismatches
        record["examples"] = [
            {"row": i, "source": str(a), "target": str(b)}
            for i, a, b in mismatches[:5]
        ]
    except Exception as exc:
        record["error"] = type(exc).__name__ + ": " + str(exc)[:600]
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--require-equal", action="store_true",
                        help="Exit nonzero if any source/target result differs")
    args = parser.parse_args()
    rows = _fixtures()
    with duckdb.connect(":memory:") as duck, sqlite3.connect(":memory:") as sqlite:
        duck.execute("CREATE TABLE event_dates (id INTEGER, d1 DATE, d2 DATE)")
        sqlite.execute("CREATE TABLE event_dates (id INTEGER, d1 TEXT, d2 TEXT)")
        duck.executemany("INSERT INTO event_dates VALUES (?, ?, ?)", rows)
        sqlite.executemany("INSERT INTO event_dates VALUES (?, ?, ?)", rows)
        cases = [evaluate(case, duck, sqlite) for case in SQL_CASES]
    passed = sum(c["equal"] for c in cases)
    result = {
        "kind": "LIVE_DUCKDB_TO_SQLITE_DIFFERENTIAL",
        "note": "Tests calendar-date value, not timestamp return type or timezone",
        "source_engine": f"DuckDB {duckdb.__version__}",
        "fixture_rows": len(rows),
        "case_count": len(cases),
        "equal_cases": passed,
        "unequal_cases": len(cases) - passed,
        "cases": cases,
    }
    for c in cases:
        status = "EQUAL" if c["equal"] else "MISMATCH"
        print(f'{c["id"]:25} {status:8} mismatches={c["mismatch_count"]} '
              f'error={c["error"]} examples={c["examples"][:2]}')
    print(f'LIVE_DUCKDB_TO_SQLITE: {passed}/{len(cases)} cases equivalent under stated normalization')
    if args.output:
        args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n",
                               encoding="utf-8")
    if args.require_equal and passed != len(cases):
        raise SystemExit(f"Live DuckDB/SQLite semantic regressions: {len(cases) - passed}")


if __name__ == "__main__":
    main()
