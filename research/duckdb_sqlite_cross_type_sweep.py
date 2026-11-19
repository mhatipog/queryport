#!/usr/bin/env python3
"""Deterministic live-engine cross-type semantic discrepancy discovery.

Executes original DuckDB SQL and transpiled SQLite SQL on the same generated
rows, preserving row order. This is exploratory: recording failed conversions
is NOT a claim of verified correctness or a mandate to drop hard test cases.

python3 research/duckdb_sqlite_cross_type_sweep.py --output /tmp/semantic-sweep.json
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
from pathlib import Path
import random
import sqlite3
from collections import Counter

import duckdb
from sqlglot import parse_one
from sqlglot.errors import ErrorLevel


EXPRS = {
    "numeric": [
        "n + 3", "n - 3", "n * -2", "ABS(n)", "n % 4", "n / 4",
        "FLOOR(x)", "CEIL(x)", "ROUND(x, 2)", "ROUND(x, 0)",
        "SIGN(x)", "TRUNC(x)", "POWER(ABS(x), 0.5)", "SQRT(ABS(x))",
        "LOG10(ABS(x) + 1)", "EXP(x / 500.0)", "GREATEST(x, y)",
        "LEAST(x, y)", "NULLIF(n, 0)", "COALESCE(x, y)",
        "CASE WHEN n > 0 THEN x ELSE y END", "x / NULLIF(y, 0)",
        "CAST(x AS INTEGER)", "CAST(n AS VARCHAR)",
    ],
    "string": [
        "LOWER(s)", "UPPER(s)", "TRIM(s)", "LTRIM(s)", "RTRIM(s)",
        "REPLACE(s, 'a', 'x')", "SUBSTRING(s, 1, 2)",
        "LEFT(s, 2)", "RIGHT(s, 2)", "LENGTH(s)",
        "STRPOS(s, 'a')", "CONCAT(s, s2)", "CONCAT_WS('-', s, s2)",
        "LPAD(s, 5, '_')", "RPAD(s, 5, '_')",
        "SPLIT_PART(s, ':', 1)", "REVERSE(s)",
        "STARTS_WITH(s, 'A')", "ENDS_WITH(s, 'x')",
        "REGEXP_REPLACE(s, '[ab]', 'x')",
    ],
    "calendar": [
        "EXTRACT(YEAR FROM d)", "EXTRACT(MONTH FROM d)",
        "EXTRACT(DAY FROM d)", "EXTRACT(DOW FROM d)",
        "EXTRACT(ISODOW FROM d)", "EXTRACT(WEEK FROM d)",
        "EXTRACT(DAYOFYEAR FROM d)", "EXTRACT(QUARTER FROM d)",
        "DATE_TRUNC('month', d)", "DATE_TRUNC('week', d)",
        "DATE_TRUNC('quarter', d)", "LAST_DAY(d)",
        "DATE_ADD(d, INTERVAL 1 MONTH)", "DATE_ADD(d, INTERVAL 1 YEAR)",
    ],
}


def fixtures(count: int = 900):
    r = random.Random(20261119)
    origin = dt.date(1992, 1, 1)
    ss = ("abc", "ABC", "a:b", "  ALPHA  ", "", "café", "ß", "İstanbul", None)
    fixed = [
        (dt.date(2024, 1, 31), 5, -2.5, 1.0, "abc", None),
        (dt.date(2024, 2, 29), -5, 2.5, -1.0, "ABC", "x"),
        (dt.date(2023, 12, 31), 0, 0.0, 0.0, "", ""),
        (dt.date(2024, 1, 1), None, None, None, None, None),
    ]
    rows = list(fixed)
    for _ in range(count):
        date = origin + dt.timedelta(days=r.randrange(0, 14700))
        n = r.choice([None, r.randrange(-30, 31)])
        x = r.choice([None, r.uniform(-1500, 1500)])
        y = r.choice([None, r.uniform(-1500, 1500)])
        rows.append((date, n, x, y, r.choice(ss), r.choice(ss)))
    return [
        (i, d.isoformat() if d else None, n, x, y, s, s2)
        for i, (d, n, x, y, s, s2) in enumerate(rows)
    ]


def normalize(value):
    if isinstance(value, dt.datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def equivalent(a, b):
    a, b = normalize(a), normalize(b)
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, bool):
        return b in (a, int(a))
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(a, b, abs_tol=1e-9, rel_tol=1e-9)
    if isinstance(a, str) and isinstance(b, str):
        return a == b
    return a == b


def evaluate(name: str, category: str, expression: str, duck, sqlite, rows):
    sql = f"SELECT {expression} AS result FROM t ORDER BY id"
    record = {
        "id": name, "category": category, "expression": expression,
        "source_sql": sql, "target_sql": None,
        "source_executed": False, "target_executed": False,
        "status": "source_error", "mismatch_count": None, "examples": [],
        "error": None,
    }
    try:
        source = duck.execute(sql).fetchall()
        record["source_executed"] = True
    except Exception as exc:
        record["error"] = type(exc).__name__ + ": " + str(exc)[:500]
        return record
    try:
        generated = parse_one(sql, read="duckdb").sql(
            "sqlite", unsupported_level=ErrorLevel.RAISE
        )
        record["target_sql"] = generated
    except Exception as exc:
        record["status"] = "conversion_error"
        record["error"] = type(exc).__name__ + ": " + str(exc)[:500]
        return record
    try:
        target = sqlite.execute(generated).fetchall()
        record["target_executed"] = True
    except Exception as exc:
        record["status"] = "target_error"
        record["error"] = type(exc).__name__ + ": " + str(exc)[:500]
        return record
    if len(source) != len(target):
        record["status"] = "cardinality_mismatch"
        record["error"] = f"source {len(source)} rows; target {len(target)} rows"
        return record
    problems = [
        (index, normalize(sa[0]), normalize(tb[0]))
        for index, (sa, tb) in enumerate(zip(source, target))
        if not equivalent(sa[0], tb[0])
    ]
    record["mismatch_count"] = len(problems)
    record["status"] = "equivalent" if not problems else "value_mismatch"
    record["examples"] = [
        {
            "row_index": i, "source_value": str(a), "target_value": str(b),
            "input": {
                "id": rows[i][0], "date": rows[i][1], "n": rows[i][2],
                "x": rows[i][3], "y": rows[i][4], "s": rows[i][5], "s2": rows[i][6],
            },
        }
        for i, a, b in problems[:4]
    ]
    return record


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path)
    p.add_argument("--strict", action="store_true", help="Fail if any comparable case mismatches")
    args = p.parse_args()
    rows = fixtures()
    with duckdb.connect(":memory:") as duck, sqlite3.connect(":memory:") as sqlite:
        duck.execute("CREATE TABLE t (id INTEGER, d DATE, n INTEGER, x DOUBLE, y DOUBLE, s VARCHAR, s2 VARCHAR)")
        sqlite.execute("CREATE TABLE t (id INTEGER, d TEXT, n INTEGER, x REAL, y REAL, s TEXT, s2 TEXT)")
        duck.executemany("INSERT INTO t VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
        sqlite.executemany("INSERT INTO t VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
        results = [
            evaluate(f"{category}_{index:02d}", category, expr, duck, sqlite, rows)
            for category, expressions in EXPRS.items()
            for index, expr in enumerate(expressions, 1)
        ]
    counts = dict(sorted(Counter(r["status"] for r in results).items()))
    report = {
        "kind": "live_duckdb_sqlite_cross_type",
        "source_engine": f"DuckDB {duckdb.__version__}",
        "target_engine": f"SQLite {sqlite3.sqlite_version}",
        "fixture_rows": len(rows), "expression_cases": len(results),
        "status_counts": counts, "cases": results,
        "limitations": "No cross-engine type equality, time zones, collations, statement side-effects or SQL error equivalence claims",
    }
    for row in results:
        print(f'{row["id"]:13} {row["status"]:22} {row["expression"][:42]} '
              f'mismatches={row["mismatch_count"]} {row["error"] or ""} '
              f'examples={row["examples"][:1]}', flush=True)
    print("CROSS_TYPE_SWEEP:", json.dumps(counts, sort_keys=True), flush=True)
    if args.output:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.strict and any(row["status"] != "equivalent" for row in results):
        raise SystemExit("Cross-type live-engine conversion failures present")


if __name__ == "__main__":
    main()
