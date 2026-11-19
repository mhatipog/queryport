#!/usr/bin/env python3
"""Compare independent execution outcomes on IDENTICAL source fixtures.

A positive gain and zero regressions are required by default. Keep the
full report in the CI log, never write or upload user datasets.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def compare(legacy: dict, candidate: dict) -> dict:
    old = {row["id"]: row for row in legacy["rows"]}
    new = {row["id"]: row for row in candidate["rows"]}
    if set(old) != set(new):
        raise ValueError(f"Mismatched benchmark cases: old/new {set(old) ^ set(new)}")
    improved = []
    regressions = []
    still_failing = []
    unchanged_success = []
    for key in sorted(old):
        before, after = bool(old[key]["passed"]), bool(new[key]["passed"])
        if not before and after:
            improved.append(key)
        elif before and not after:
            regressions.append(key)
        elif not before and not after:
            still_failing.append(key)
        else:
            unchanged_success.append(key)
    return {
        "cases": len(old), "legacy_passed": len(unchanged_success) + len(regressions),
        "candidate_passed": len(unchanged_success) + len(improved),
        "improved": improved, "regressed": regressions,
        "both_failing": still_failing, "unchanged_success": unchanged_success,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("legacy", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--require-gain", action="store_true")
    args = parser.parse_args()
    baseline = json.loads(args.legacy.read_text(encoding="utf-8"))
    upgraded = json.loads(args.candidate.read_text(encoding="utf-8"))
    result = compare(baseline, upgraded)
    print("=== SOURCE-AWARE SQL PORTABILITY DIFFERENTIAL SCOREBOARD ===")
    print(f'Legacy:    {result["legacy_passed"]}/{result["cases"]} cases correct')
    print(f'QueryPort: {result["candidate_passed"]}/{result["cases"]} cases correct')
    print(f'Improved ({len(result["improved"])}): {", ".join(result["improved"])}')
    print(f'Regressed ({len(result["regressed"])}): {", ".join(result["regressed"])}')
    print(f'Unresolved ({len(result["both_failing"])}): {", ".join(result["both_failing"])}')
    if result["regressed"]:
        raise SystemExit("Regressions detected: do not promote QueryPort")
    if args.require_gain and not result["improved"]:
        raise SystemExit("No independently measured improvements over pinned baseline")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
