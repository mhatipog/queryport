# QueryPort: opt-in DuckDB → stock SQLite value portability

This feature corrects deliberately scoped cases in the
[58-expression live benchmark](../research/duckdb_sqlite_cross_type_sweep.py)
without changing the global SQLGlot SQLite generator or other source dialects.

```python
from sqlglot.queryport_duckdb_sqlite import port_duckdb_to_sqlite

result = port_duckdb_to_sqlite(
    "SELECT DATE_ADD(d, INTERVAL 1 MONTH), LPAD(s, 5, '_') FROM t",
    schema={"t": {"d": "DATE", "s": "VARCHAR"}},
)
print(result.sql[0])
print(result.rewritten_date_timestamp, result.rewritten_padding)
```

The schema must be **trusted source metadata**. QueryPort never guesses that an
untyped `d` is a DATE or that an untyped `s` is a string merely from its name.

## Supported and measured

- DuckDB `DATE + INTERVAL` and `DATE_ADD(DATE, INTERVAL)` are **timestamp-returning**.
  A typed, opt-in expression is wrapped in `DATETIME(...)`, rather than
  returning SQLite's bare date string for whole-month and whole-year shifts.
  Date arithmetic still uses the existing QueryPort calendar implementation.
- Stock SQLite has no built-in `LPAD` or `RPAD`. For a **literal width from
  0 through 1024**, a one-codepoint literal fill, and a trusted `VARCHAR`
  input column or string literal, this port emits a scalar `CASE` expression
  using core `SUBSTR`, `LENGTH`, `HEX`, `ZEROBLOB`, and `REPLACE`.
  This handles both left and right padding, truncation, empty input and NULL
  without extension functions.
- The default `strict=True` raises `UnsafeDuckDBPort` when a recognized pad,
  `SPLIT_PART`, `REVERSE` or regex operation has no independently verified
  mapping. `strict=False` can be used for **diagnostic sweeps** only; inspect
  `unresolved` and do not label unchanged SQL semantically equivalent.

**Not supported:** arbitrary fill patterns, unbounded/dynamic widths, binary
padding, embedded-NUL text, collation/ICU-dependent graphemes,
`SPLIT_PART`, regex translation, and volatile expressions that would be
evaluated repeatedly by SQL expressions. DuckDB/SQLite engine versions and
data input validity still matter. SQLite's timestamps are textual and are not
the same storage type as DuckDB `TIMESTAMP`; the current tests compare their
normalized values, not internal types or time zones.

Outputs are not certified without executing the source and target engines:
`source_engine_executed`, `target_engine_executed`, and
`semantic_equivalence_proven` are **false**. No arbitrary SQL is certified.

## Reproduce independently

```bash
python3 -m unittest -v tests.test_queryport_duckdb_sqlite_optin
python3 research/duckdb_sqlite_cross_type_sweep.py
python3 research/duckdb_sqlite_cross_type_sweep.py --opt-in \
  --min-equivalent 52 \
  --require-ids calendar_13,calendar_14,string_14,string_15
```

Both engines must execute against the same deterministic fixtures.
These are intentionally hard diagnostic cases, not a representative sample
of all SQL queries. Zero unchanged cases may regress before merge.

References: [DuckDB string functions](https://duckdb.org/docs/stable/sql/functions/text),
[DuckDB date types](https://duckdb.org/docs/stable/sql/data_types/date),
[SQLite core functions](https://www.sqlite.org/lang_corefunc.html).
