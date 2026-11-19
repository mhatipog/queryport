#!/usr/bin/env python3
"""Diagnostic SQL portability corpus runner; never claims semantic equivalence.

Run from the QueryPort/SQLGlot repository root:
  PYTHONPATH=. python3 research/portability_probe.py
  PYTHONPATH=. python3 research/portability_probe.py --json /tmp/queryport-probe.json
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

import sqlglot
from sqlglot import exp
from sqlglot.errors import ErrorLevel

ROOT = Path(__file__).resolve().parent
CASES = ROOT / "portability_cases.json"
RANK = {
    "source_parse_error": 0,
    "generator_error": 1,
    "target_parse_error": 2,
    "opaque_source": 2,
    "opaque_target": 2,
    "incomplete": 2,
    "syntax_only": 3,
}
# These are confirmed UNSUPPORTED BY MICROSOFT DOCS, not detected by the base parser.
DOCUMENTED_TARGET_INCOMPATIBILITIES = {
    "FAB001": "Materialized views unsupported in Fabric Warehouse",
    "FAB002": "CREATE USER unsupported in Fabric Warehouse",
    "FAB003": "Lakehouse SQL analytics endpoint cannot INSERT into tables",
    "FAB005": "FOR XML unsupported in Fabric Warehouse",
}


def has_opaque(expr: exp.Expression) -> bool:
    return any(isinstance(node, exp.Command) for node in expr.walk())


def check(case: dict) -> dict:
    record = {
        "id": case["id"], "read": case["read"], "write": case["write"],
        "profile": case["target_profile"], "feature": case["feature"],
        "status": "source_parse_error", "statement_count": 0,
        "target_sql": [], "detail": "",
        "semantic_validated": False,
        "engine_validated": False,
        "documented_target_incompatibility": DOCUMENTED_TARGET_INCOMPATIBILITIES.get(case["id"]),
    }
    try:
        trees = sqlglot.parse(case["sql"], read=case["read"], error_level=ErrorLevel.RAISE)
        if not trees or any(tree is None for tree in trees):
            record["status"] = "incomplete"
            record["detail"] = "Parser did not return a tree for every parsed statement"
            return record
        record["statement_count"] = len(trees)
    except Exception as exc:
        record["detail"] = type(exc).__name__ + ": " + str(exc)[:500]
        return record

    if any(has_opaque(tree) for tree in trees):
        record["status"] = "opaque_source"
        record["detail"] = "Source AST contains opaque Command fallback; cannot trust transcription"
        return record

    try:
        generated = [
            tree.sql(dialect=case["write"], unsupported_level=ErrorLevel.IMMEDIATE)
            for tree in trees
        ]
        record["target_sql"] = generated
    except Exception as exc:
        record["status"] = "generator_error"
        record["detail"] = type(exc).__name__ + ": " + str(exc)[:500]
        return record

    try:
        targets = []
        for sql in generated:
            sub = sqlglot.parse(sql, read=case["write"], error_level=ErrorLevel.RAISE)
            targets.extend(sub)
        if not targets or any(tree is None for tree in targets):
            record["status"] = "incomplete"
            record["detail"] = "Target parser returned an empty/missing AST"
        elif any(has_opaque(tree) for tree in targets):
            record["status"] = "opaque_target"
            record["detail"] = "Target AST contains opaque Command fallback"
        elif len(targets) != len(trees):
            record["status"] = "incomplete"
            record["detail"] = f"Statement count changed: {len(trees)} source to {len(targets)} target"
        else:
            record["status"] = "syntax_only"
            record["detail"] = "Source parsed and target reparsed; NO semantic or engine verification"
    except Exception as exc:
        record["status"] = "target_parse_error"
        record["detail"] = type(exc).__name__ + ": " + str(exc)[:500]

    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", dest="json_path", type=Path,
                        help="Write diagnostics to a local file, without uploads")
    args = parser.parse_args()
    payload = json.loads(CASES.read_text(encoding="utf-8"))
    cases = payload["cases"]
    assert len({case["id"] for case in cases}) == len(cases), "Duplicate corpus case IDs"
    rows = [check(c) for c in cases]
    counts = dict(sorted(Counter(r["status"] for r in rows).items()))
    report = {
        "project": "QueryPort", "test_kind": "syntax_diagnostics_not_equivalence",
        "sqlglot_version": getattr(sqlglot, "__version__", "unknown"),
        "case_count": len(rows), "counts": counts,
        "documented_incompatible_count": sum(bool(r["documented_target_incompatibility"]) for r in rows),
        "semantic_validated_count": 0,
        "engine_validated_count": 0,
        "rows": rows,
    }
    for row in rows:
        flag = " [DOCUMENTED TARGET INCOMPATIBLE]" if row["documented_target_incompatibility"] else ""
        print(f'{row["id"]:7} {row["read"]:6} -> {row["write"]:6} '
              f'{row["status"]:20} {row["feature"]}{flag}')
    print("\nDiagnostic counts:", json.dumps(counts, sort_keys=True))
    print("Engine-executed and semantic-equivalence tests: 0 (by design)")
    if args.json_path is not None:
        args.json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                                 encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
