# QueryPort: PostgreSQL / DuckDB DATE subtraction → SQLite

PostgreSQL and DuckDB define `DATE - DATE` as **the number of whole
calendar days between the dates**. SQLite does not: subtracting text dates
silently applies numeric coercion and can produce a plausible-looking zero.

QueryPort fixes this through an **opt-in, source-aware porting API** instead of
changing all SQLGlot SQLite subtraction globally.

```python
from sqlglot.queryport_port import port_date_subtraction

# Explicit DATE casts: safe to recognize without a table schema.
result = port_date_subtraction(
    "SELECT CAST('2024-03-01' AS DATE) - CAST('2024-02-01' AS DATE)",
    read="postgres",
)
print(result.sql[0])  # Returns 29 on SQLite.
assert result.date_subtractions_rewritten == 1

# Columns: supply a trusted source schema (DATE vs integer is critical).
result = port_date_subtraction(
    "SELECT shipment_date - ordered_date AS elapsed FROM orders",
    read="duckdb",
    schema={"orders": {"shipment_date": "DATE", "ordered_date": "DATE"}},
)

print(result.untyped_subtractions)  # 0 when safely typed
```

## Scope and guarantees

- Supported source dialects: `postgres` and `duckdb`; target: `sqlite`.
- Only explicit date-typed expressions or reliably schema-resolved `DATE - DATE`
  are rewritten. Numeric `x - y` remains unchanged.
- Unqualified columns are resolved from a trusted schema **only when a query
  has one unambiguous physical source table**. Joins and nested/multiple
  sources are not guessed.
- Untyped/ambiguous column subtraction is counted in
  `untyped_subtractions`. The caller should investigate it; generated SQL
  is **not** a semantic guarantee.
- Output must parse in SQLite without an opaque `Command` node.
- This feature only addresses date difference expressions, not arbitrary
  time-zone arithmetic, intervals, timestamp differences, negative-year
  calendar conventions or dialect compatibility outside this source/target
  pair.

Independent unit tests generate 2,503 deterministic date pairs and execute
the SQL in SQLite for both PostgreSQL and DuckDB source variants, both as
explicit casts and source-schema typed columns, plus leap-year, NULL, numeric,
ambiguous-join and multi-statement tests.

**Engine execution:** The generated target SQL is executed in actual SQLite
during tests. The source engine is not called in this harness, so the API's
`semantic_equivalence_proven` flag remains false. The expected DATE-minus-DATE
integer-day result is independently computed using Python `datetime`.

References:
- [PostgreSQL datetime operators](https://www.postgresql.org/docs/current/functions-datetime.html)
- [DuckDB interval and date subtraction](https://duckdb.org/docs/current/sql/data_types/interval)
- [SQLite date functions](https://www.sqlite.org/lang_datefunc.html)
