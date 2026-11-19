# Verified semantic bug backlog — 19 November 2026

These gaps were **reproduced on real DuckDB (source) and SQLite (target)**
using the deterministic 58-case, 904-row
[cross-type differential harness](../research/duckdb_sqlite_cross_type_sweep.py).

**Evidence:** [OCI discovery run](https://github.com/mhatipog/web-operations/actions/runs/44608827747)
and [eight-fix OCI validation](https://github.com/mhatipog/web-operations/actions/runs/44611602018).

**Current:** 48/58 equivalent value cases; **5 silent mismatches** and
**5 target execution errors** remain. These are deliberately challenging,
nonrepresentative cases; percentages cannot be extrapolated to all SQL.

The repository inherits **GitHub Issues disabled** from the original fork.
This file tracks the independently verified issues until Issues can be enabled.

## Priority 1 — Silent wrong answers (do first)

### QP-001: DuckDB FLOAT/DOUBLE → INTEGER casting

- Reproducer: `SELECT CAST(x AS INTEGER)` with `x=-1081.5003595119194`.
- Observed: source DuckDB `-1082`, target SQLite `-1081`.
- Scope: `numeric_23`, **224/904 mismatching** test rows.
- Cause: DuckDB rounds to nearest, **ties to even**; SQLite integer casts
  truncate. Source: [DuckDB numerical types](https://duckdb.org/docs/stable/sql/data_types/numeric).
- Acceptance: source-aware, opt-in translation with trusted input type and
  range/overflow diagnostics; live DuckDB/SQLite tests for ±0.5, ±1.5,
  ±2.5, ±3.5, 0, NULL, fractional values and integer overflow; do not
  change MySQL, PostgreSQL, Oracle, T-SQL or native SQLite cast semantics.

### QP-002: Unicode LOWER/UPPER collations and case mapping

- Reproducer: `UPPER('café')` → DuckDB `CAFÉ`, stock SQLite `CAFé`;
  also `LOWER('İstanbul')`.
- Scope: `string_01` (111/904 different) and `string_02`
  (200/904 different).
- Cause: SQLite built-in casing without an ICU extension is ASCII-oriented.
- Acceptance: target capability/runtime profiling plus explicit Unicode
  risk warnings or fail-closed diagnostic; if an ICU-enabled SQLite runtime
  is available, prove its exact Unicode version and behavior. Test
  Turkish, Latin, Greek, combining marks and normalization.
- **Do not silently replace** Unicode-sensitive casing with ASCII-only
  SQLite calls and claim semantic equivalence.

### QP-003: DuckDB DATE_ADD date→timestamp return contract

- Reproducer: `SELECT DATE_ADD(d, INTERVAL 1 MONTH)` and `1 YEAR`.
- Scope: `calendar_13`, `calendar_14`, 904/904 strict value differences
  per case despite matching calendar days.
- Observed: source result `2024-02-29 00:00:00`, target
  `2024-02-29` for `d=2024-01-31`.
- Acceptance: source-aware return types (DATE vs TIMESTAMP), explicit
  temporal type checking, real engine comparisons for time-of-day,
  fractional precision and NULL values. Do not change Spark/MySQL
  `DATE_ADD` types based on DuckDB's behavior.
- The 26-case date-only benchmark deliberately ignored timestamp type:
  it cannot be counted as evidence of complete type fidelity.

## Priority 2 — Generated SQL fails to execute

### QP-004: Missing string functions in the SQLite target

The source DuckDB executes the following, but QueryPort's SQLite output
still calls absent built-ins:

| Case | Function | Required action |
| --- | --- | --- |
| `string_14` | `LPAD` | Correct SQL rewrite or explicit unsupported |
| `string_15` | `RPAD` | Correct SQL rewrite or explicit unsupported |
| `string_16` | `SPLIT_PART` | Preserve part indexing and empty/null fields |
| `string_17` | `REVERSE` | Grapheme-vs-codepoint semantics and extension policy |
| `string_20` | `REGEXP_REPLACE` | Regex engine/pattern compatibility; no blind rewrite |

- Acceptance: prove each rewrite on real DuckDB/SQLite over NULL, empty,
  Unicode, negative/boundary parameters; if no faithful built-in mapping
  exists, emit an explicit `UnsupportedError` rather than invalid SQL.
- Beware SQLite version-specific built-in availability and optional ICU,
  math and regex extensions.

## Priority 3 — Broader dialect capability (separate experiments)

- Oracle PL/SQL parser and procedural IR: `PLS001` through `PLS004`
  in [38-case portability corpus](../research/portability_cases.json)
  do not constitute verified source/target equivalence; build explicit
  variable, cursor, exception and side-effect semantics before codegen.
- Oracle `(+)` outer joins and `TO_CHAR` format mappings to Spark or
  Fabric: generator errors in `ORA006` and `ORA009`.
- Microsoft Fabric: keep Warehouse distinct from the Lakehouse SQL
  analytics endpoint and validate on **real authorized Fabric engines**,
  not merely generic T-SQL parsing.
- Apache Spark: test at pinned 3.5 and 4.1 versions; SQL scripting is
  version-specific and cannot serve as an automatic equivalent to PL/SQL.
- Upstream synchronization: periodically compare latest upstream SQLGlot
  with QueryPort's pinned legacy baseline; do not assume upstream remains
  static or claim improvements that upstream has since incorporated.

## Autonomous development quality gate

For each item:

1. Reproduce on **both engines** (or the intended source and target), pin
   versions, schema, locale/timezone and deterministic inputs.
2. Minimize to one SQL statement and a small fixture without hiding
   duplicates, NULLs or side effects.
3. Implement a source-aware transform or a truthful unsupported warning;
   no global dialect behavior change unless it is proven valid generally.
4. Run local semantic oracle, unrelated dialect-negative tests,
   26-case live DuckDB benchmark, 58-case cross-type sweep, 32-case
   legacy comparison, targeted dialect tests and the full SQLGlot suite.
5. Merge only with **zero measured regressions**; update this backlog and
   CI evidence, including any remaining unverified behavior.

The development target is **measured fewer wrong answers**, not
a marketing claim of 10× superiority based on intentionally hard cases.
