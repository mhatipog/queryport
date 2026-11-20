# Verified semantic bug backlog — 20 November 2026

These gaps were **reproduced on real DuckDB (source) and SQLite (target)**
using the deterministic 58-case, 904-row
[cross-type differential harness](../research/duckdb_sqlite_cross_type_sweep.py).

**Evidence:** [OCI discovery](https://github.com/mhatipog/web-operations/actions/runs/44608827747),
[prior 8-fix regression](https://github.com/mhatipog/web-operations/actions/runs/44611602018),
[4 new fixes](https://github.com/mhatipog/web-operations/actions/runs/44682664149),
and [5-fix validation](https://github.com/mhatipog/web-operations/actions/runs/44683391128).

**Ordinary, unmodified SQLGlot transpilation:** 48/58 equivalent; **5 silent mismatches** and
**5 target execution errors**. The standard dialect generator has not changed.

**QueryPort's opt-in, source-aware conversion** (trusted DuckDB column types and
finite INT32-safe bounds): **53/58 equivalent**, **2 silent mismatches** and
**3 target execution errors**. Each of the five repaired benchmark expressions
matched all 904 real-engine fixture rows in this tested configuration. The full
Python regression suite ran **1,797 tests, 61 skipped, 0 failures**.

These are deliberately challenging, nonrepresentative cases; percentages
cannot be extrapolated to all SQL. The library does not execute source or
target engines or prove arbitrary SQL equivalence; tests do so for these fixtures.

The repository inherits **GitHub Issues disabled** from the original fork.
This file tracks the independently verified issues until Issues can be enabled.

## Priority 1 — Silent wrong answers (do first)

### QP-001: DuckDB FLOAT/DOUBLE → INTEGER casting — bounded DOUBLE→INT32 fixed (opt-in)

- Reproducer: `SELECT CAST(x AS INTEGER)` with `x=-1081.5003595119194`.
- Observed: source DuckDB `-1082`, target SQLite `-1081`.
- Scope: `numeric_23`, **224/904 mismatching** test rows.
- Cause: DuckDB rounds to nearest, **ties to even**; SQLite integer casts
  truncate. Source: [DuckDB numerical types](https://duckdb.org/docs/stable/sql/data_types/numeric).
- **Fixed in [PR #12](https://github.com/mhatipog/queryport/pull/12)** for
  trusted, bounded DOUBLE columns cast to signed INT32 via
  `port_duckdb_to_sqlite(..., schema=..., float_bounds=...)`.
  `numeric_23` improved **224/904 mismatches → 0/904** in live DuckDB/SQLite;
  3,326 edge/random values also agreed with an independent Python ties-even oracle.
- **Still unsupported:** unbounded/unknown data, FLOAT32, DECIMAL, text,
  other integer widths, implicit casts and faithful DuckDB overflow/NaN exceptions.
  Default SQLGlot casting is unchanged. Incorrect source metadata or bounds
  invalidate the guarantee.

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

### QP-003: DuckDB DATE_ADD date→timestamp return contract — fixed for typed DATE (opt-in)

- Reproducer: `SELECT DATE_ADD(d, INTERVAL 1 MONTH)` and `1 YEAR`.
- Scope: `calendar_13`, `calendar_14`, 904/904 strict value differences
  per case despite matching calendar days.
- Observed: source result `2024-02-29 00:00:00`, target
  `2024-02-29` for `d=2024-01-31`.
- **Fixed in [PR #11](https://github.com/mhatipog/queryport/pull/11)**
  for trusted DuckDB DATE operands using the opt-in converter:
  `calendar_13` and `calendar_14` both improved
  **904/904 value mismatches → 0/904** on real DuckDB/SQLite.
- **Still unsupported:** unknown/untyped base expressions, timezone-aware or
  fractional-second fidelity beyond tested cases, full runtime type equivalence.
  The output is a SQLite textual timestamp, not DuckDB's internal timestamp type.
  Other source dialects remain unchanged.

## Priority 2 — Generated SQL fails to execute

### QP-004: Missing string functions in the SQLite target

The source DuckDB executes the following, but QueryPort's SQLite output
still calls absent built-ins:

| Case | Function | Required action |
| --- | --- | --- |
| `string_14` | `LPAD` | **Fixed** for bounded literal width, one-codepoint fill, trusted VARCHAR source (opt-in PR #11) |
| `string_15` | `RPAD` | **Fixed** for same narrowly typed case (opt-in PR #11) |
| `string_16` | `SPLIT_PART` | Preserve part indexing and empty/null fields |
| `string_17` | `REVERSE` | Grapheme-vs-codepoint semantics and extension policy |
| `string_20` | `REGEXP_REPLACE` | Regex engine/pattern compatibility; no blind rewrite |

- **LPAD/RPAD:** tested on real engines with 508 mixed Unicode, NULL,
  empty, truncated and boundary rows, plus 904 benchmark rows for each function
  (**target error → 0 mismatches**). Does not support arbitrary fill strings,
  dynamic widths, binary data, NUL or full grapheme semantics.
- **Remaining missing functions:** `SPLIT_PART`, `REVERSE`,
  `REGEXP_REPLACE`; explicit strict-mode `UnsafeDuckDBPort` diagnostics
  are safer than pretending the SQLite target supports them.
- Future acceptance: prove any additional rewrite on both engines and
  document negative/boundary cases; don't emit invalid SQL silently in strict mode.
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
