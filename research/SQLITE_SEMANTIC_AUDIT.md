# SQLite semantic audit — 19 November 2026

Independent, stdlib-only executable tests for SQLGlot's SQLite transpilation, using
the same SQLGlot commit as the OCI validation workflow.

```bash
PYTHONPATH=. python3 research/sqlite_semantic_audit.py
```

The tests cover:

- MySQL / PostgreSQL / BigQuery unbounded random functions → SQLite
- Preservation of native SQLite's signed integer `RANDOM()`
- Five exact signed 64-bit boundary values
- 50,000 seeded pseudo-random values (range, mean, 10-bin chi-square)
- 1,000 randomly generated date pairs compared to Python's datetime arithmetic
- Leap years, year boundaries, negative day differences, and NULL values
- One `unittest.expectedFailure` marking upstream's unresolved issue
  [#9259](https://github.com/tobymao/sqlglot/issues/9259)

## Why this is a research branch, not an upstream PR

The source-level fix for SQLite `RAND` semantics was already implemented and
merged by a SQLGlot maintainer in
[commit 1055c0a](https://github.com/tobymao/sqlglot/commit/1055c0a657cb5d260f32d43678cfeddc569a91ee).

The date subtraction bug exists, but an unconditional SQLite generator rewrite
would be unsafe: PostgreSQL and DuckDB define DATE - DATE as a number of elapsed
days, whereas MySQL dates may be implicitly converted into numbers in arithmetic
expressions. A correct cross-dialect solution needs a source-aware or otherwise
semantics-preserving strategy, including column-type inference.

- PostgreSQL: https://www.postgresql.org/docs/current/functions-datetime.html
- DuckDB: https://duckdb.org/docs/current/sql/data_types/interval
- MySQL: https://dev.mysql.com/doc/refman/8.0/en/using-date.html
- SQLite: https://www.sqlite.org/lang_datefunc.html

The upstream maintainer has proposed a policy limiting upstream PR authorship to
maintainers, while retaining issue-based external contributions:
https://github.com/tobymao/sqlglot/pull/9262

## OCI verification

CI controller repository: private `mhatipog/web-operations`, workflow:
`.github/workflows/sqlglot-oci-validation.yml`. It checks out a pinned SHA
and runs on the existing self-hosted `vecture` OCI ARM64 runner, with no
artifact uploads or paid hosted runners.

Successful pre-branch baseline run:
https://github.com/mhatipog/web-operations/actions/runs/44579807895

- SQLite/shared dialect: 160 tests, 1 skipped
- All Python tests: 1752 tests, 61 skipped
- 50k RNG checks, 1k date pairs

This script is independent test evidence; its date difference expression is an
oracle candidate, **not** a claimed generally correct SQLGlot patch.
