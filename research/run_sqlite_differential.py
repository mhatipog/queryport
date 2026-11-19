#!/usr/bin/env python3
"""Execute a fixed, source-dialect SQL portability benchmark against SQLite.

Use this same runner on two different PYTHONPATH roots to measure the *pinned*
legacy SQLGlot vs QueryPort, rather than scoring different test cases.
No database other than local SQLite is invoked.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3

from sqlglot import parse_one
from sqlglot.errors import ErrorLevel


CASES = Path(__file__).with_name("sqlite_differential_cases.json")


def _conversion(sql: str, read: str, api: str) -> str:
    if api == "source_date_port":
        try:
            from sqlglot.queryport_port import port_date_subtraction
        except ImportError:
            # Legacy SQLGlot has no source-aware opt-in implementation. Report
            # the actual behavior of its stock transpiler for comparison.
            pass
        else:
            return port_date_subtraction(sql, read=read).sql[0]
    elif api != "sqlglot_transpile":
        raise ValueError("Unrecognized benchmark API: " + api)

    return parse_one(sql, read=read).sql("sqlite", unsupported_level=ErrorLevel.IMMEDIATE)


def evaluate(case: dict) -> dict:
    record = {
        "id": case["id"], "read": case["read"], "api": case["api"],
        "sql": case["sql"], "expected": case["expected"],
        "actual": None, "converted_sql": None, "passed": False,
        "engine_executed": False, "error": None,
    }
    try:
        converted = _conversion(case["sql"], case["read"], case["api"])
        record["converted_sql"] = converted
        with sqlite3.connect(":memory:") as connection:
            # DUAL is a one-row Oracle virtual table. It is harmless to use a
            # one-row fixture if the target generator preserves FROM dual.
            connection.execute("CREATE TABLE dual (dummy INTEGER)")
            connection.execute("INSERT INTO dual VALUES (1)")
            row = connection.execute(converted).fetchone()
            if row is None:
                raise AssertionError("SQL emitted no result")
            actual = row[0]
        record["actual"] = actual
        record["engine_executed"] = True
        if case["comparison"] == "date":
            record["passed"] = isinstance(actual, str) and actual[:10] == case["expected"]
        elif case["comparison"] == "integer":
            record["passed"] = type(actual) is int and actual == case["expected"]
        else:
            raise ValueError("Unsupported comparison: " + case["comparison"])
    except Exception as exc:
        record["error"] = type(exc).__name__ + ": " + str(exc)[:600]
    return record


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", choices=("legacy", "queryport"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    cases = json.loads(CASES.read_text(encoding="utf-8"))["cases"]
    if len(cases) != len(set(case["id"] for case in cases)):
        raise ValueError("Case IDs are not unique")
    rows = [evaluate(case) for case in cases]
    report = {
        "label": args.label,
        "comparison": "independent SQLite execution, not live source-engine validation",
        "case_count": len(rows),
        "passed": sum(row["passed"] for row in rows),
        "failed": sum(not row["passed"] for row in rows),
        "rows": rows,
    }
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8")
    for row in rows:
        print(f'{row["id"]:32} {"PASS" if row["passed"] else "FAIL"} '
              f'actual={row["actual"]!r} expected={row["expected"]!r} '
              f'{row["error"] or ""}', flush=True)
    print(f'RESULT {args.label}: {report["passed"]}/{report["case_count"]} PASS',
          flush=True)


if __name__ == "__main__":
    main()
