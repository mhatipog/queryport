# DuckDB DOUBLE → INT32 casts on stock SQLite (opt-in)

DuckDB's `CAST(double AS INTEGER)` rounds to the nearest integer,
**ties to even**. SQLite's ordinary `CAST(double AS INTEGER)` truncates toward
zero. This can silently alter business counts, category IDs or bucketing.

QueryPort now provides an **opt-in**, source-type-aware rewrite.
Ordinary SQLGlot transpilation is deliberately unchanged.

```python
from sqlglot.queryport_duckdb_sqlite import port_duckdb_to_sqlite

ported = port_duckdb_to_sqlite(
    "SELECT CAST(x AS INTEGER) FROM t",
    schema={"t": {"x": "DOUBLE"}},
    float_bounds={"x": (-1500, 1500)},
)
print(ported.sql[0])
assert ported.rewritten_float_to_int == 1
```

## How it works

The emitted SQLite scalar CASE handles **exact half ties** using the
parity of the truncated integer, and delegates all non-ties to SQLite
`ROUND(x)`; a final cast returns an integer. It handles negative values,
negative zero, ordinary fractions, half ties, NULL and the signed INT32
endpoints.

**The input bounds are a trusted assertion about every non-NULL row, not
inferred or verified from the SQL text.** The `float_bounds` range must
be finite, ordered and within [−2147483648, 2147483647]. Unknown bounds,
FLOAT32/REAL, DECIMAL, numeric text, and untyped cast columns fail closed
by default. DuckDB's DECIMAL casts use **different tie behavior**; broad
float rewrites would be incorrect. The bounded contract also excludes
NaN, infinities and integer overflows; QueryPort cannot emulate all
DuckDB runtime exceptions in stock SQLite.

The converter currently recognizes only `CAST(column AS INTEGER)` for
columns typed `DOUBLE` in **one unambiguous physical source table**,
with bounds under that column name. It does not rewrite volatile
expressions (repeated evaluation changes results), implicit conversions,
`TRY_CAST` or casts to other integer widths.

## Independent verification

- Live DuckDB and SQLite execute **3,300+ deterministic examples**, including
  exact ±0.5, ±1.5, ±2.5, ±3.5, random real values and signed INT32 endpoints.
- Python's built-in round-to-even provides a third, independent scalar
  oracle.
- The existing **58-case, 904-row-per-case** benchmark runs against both
  real engines and must show a strict improvement while all original QueryPort
  test suites pass.

```bash
python3 -m unittest -v tests.test_queryport_duckdb_float_int
PYTHONPATH=. python3 research/duckdb_sqlite_cross_type_sweep.py --opt-in \
  --min-equivalent 53 \
  --require-ids numeric_23,calendar_13,calendar_14,string_14,string_15
```

**No certification claim:** the API does not itself execute source or
target engines; its `semantic_equivalence_proven` flag remains false.
These tests are diagnostic evidence, not a guarantee of general SQL
equivalence or of correctly supplied external schema/range metadata.

Reference: [DuckDB numeric casting documentation](https://duckdb.org/docs/current/sql/data_types/numeric).
