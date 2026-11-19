# DuckDB → SQLite live execution lab

This is QueryPort's first source-engine **differential execution** suite:
the original SQL runs in real DuckDB, the transformed SQL runs in real
SQLite, against exactly the same deterministic fixture rows.

**Source:** `research/duckdb_sqlite_differential.py`

```bash
PYTHONPATH=. python3 research/duckdb_sqlite_differential.py --require-equal
```

The OCI workflow installs DuckDB only in an isolated temporary virtualenv;
no production databases, Fabric workspace or source datasets are touched.
The fixture has 1,208 rows: leap years, month ends, negative/reversed
differences and missing values, plus randomized date pairs.

## Actual bugs detected in the first run

The first run on the unmodified QueryPort main branch had **7 of 12 live
cross-engine scenarios equivalent**. DuckDB exposed five remaining failure
families, independent of our hand-written property-test expectations:

1. `DATE_DIFF('week', d1, d2)`: SQLite generator refused the unit; DuckDB
   defines whole 7-day spans, not SQL Server week boundaries.
2. `d1 + INTERVAL 1 MONTH`: SQLite overflowed Jan 31 to Mar 2 instead of
   DuckDB's Feb 29.
3. `d1 - INTERVAL 1 MONTH`: the corresponding negative-month overflow.
4. `DATE_TRUNC('month', d1)`: legacy SQLGlot generated a function call
   SQLite could not execute.
5. `EXTRACT(YEAR FROM d1)`: legacy SQLGlot kept unsupported EXTRACT syntax.

The next run after four fixes had 11/12 equivalent. The final DATE_TRUNC
case involved `TimestampTrunc` (a separate AST node for unknown column
types), so both `DateTrunc` and `TimestampTrunc` now require coverage.

The `--require-equal` option makes any remaining mismatch block the
candidate's promotion; the detailed result in the log distinguishes
generator failures, SQL execution failures, different row counts, and
different result values.

## Scope and limitations

- The result comparison currently checks integers and **calendar-date
  values**, not strict source/target type metadata, timestamp fractional
  seconds, time zones, DST, SQL collations, query plans or transactions.
- DuckDB is the real source engine, not merely a parser or Python reference.
  Source/target databases contain identical synthetic data.
- These deliberately challenging scenarios are **not** a representative
  estimate of all SQL compatibility. The scoreboard is a gating benchmark,
  not a claim of general correctness.
- Spark, Oracle, Fabric Warehouse, and Fabric Lakehouse require their own
  engine-specific versions of this workflow and independent acceptance tests.

See [engineering principles](QUERYPORT_ENGINEERING.md) and
[original SQLGlot differential scoreboard](DIFFERENTIAL_SCOREBOARD.md).
