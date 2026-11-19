# Live DuckDB → SQLite semantic discrepancy sweep

QueryPort's exploratory [cross-type sweep](../research/duckdb_sqlite_cross_type_sweep.py)
executes **58 source SQL expressions in DuckDB** and their **transpiled
equivalents in SQLite** over 904 identical deterministic fixture rows.

It compares values rather than SQL text, retains NULLs and Unicode strings,
and records minimal first-row counterexamples, input values, generated SQL
and execution errors. No customer data or paid engines are used.

## Initial run (19 November 2026)

[OCI evidence](https://github.com/mhatipog/web-operations/actions/runs/44608827747)

| Status | Cases | Meaning |
| --- | ---: | --- |
| Equivalent for tested values | 40 | Source/target values matched |
| Silent value mismatch | 6 | Both engines ran, but values differed |
| Target execution error | 10 | Generated SQL could not execute in local SQLite |
| Explicitly unsupported | 2 | SQLGlot raised an unsupported-conversion error |

### High-impact failures worth solving

1. **Float→integer cast:** `CAST(x AS INTEGER)` disagreed on 224/904
   rows. DuckDB rounds to nearest, with ties-to-even; SQLite truncates
   toward zero. This is a *semantic*, not grammatical, mismatch.
2. **Unicode casing:** `LOWER(s)` differed in 111 rows and `UPPER(s)`
   in 200 rows, because stock SQLite casing is ASCII-focused without
   ICU; e.g. `café` and `İstanbul`.
3. **`CONCAT_WS` empty fields:** 167 discrepancies: SQLite versions
   3.44.0 through 3.50.1 have historically omitted empty strings.
4. **Date result type:** `DATE_ADD(d, INTERVAL 1 MONTH/YEAR)` returned
   text timestamps at midnight in DuckDB but bare dates in generated
   SQLite. Calendar dates matched; full timestamp-valued equality did not.
5. **Missing SQLite functions:** LEFT, RIGHT, LPAD, RPAD, SPLIT_PART,
   REVERSE, STARTS_WITH, ENDS_WITH, REGEXP_REPLACE, LAST_DAY.
6. **ISO date fields:** ISODOW and WEEK extraction were detected and
   explicitly rejected by the SQLite generator.

**Important:** These counts represent a reproducible **intentionally
challenging** test corpus, not a random estimate of SQLGlot's overall
failure rate. DuckDB and SQLite type and collation semantics are
fundamentally different. Some conversions require explicit unsupported
diagnostics or a deployment-time extension, not a blind generator patch.

Official relevant references:
- [DuckDB numeric cast rounding](https://duckdb.org/docs/stable/sql/data_types/numeric)
- [DuckDB string functions](https://duckdb.org/docs/stable/sql/functions/char)
- [SQLite built-in functions](https://sqlite.org/lang_corefunc.html)
- [SQLite CONCAT_WS empty-string issue](https://sqlite.org/forum/forumpost/52503ac21d)

Follow-up changes should promote individual fixes only after comparing
the same source and target engines, verifying NULLs and Unicode, and
running the entire pinned SQLGlot regression suite.
