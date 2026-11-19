# SQLite text functions and ISO calendar portability

This feature extends QueryPort's SQLGlot-derived SQLite generator with verified
target expressions for source dialects such as DuckDB.

## Conversions

| Source SQL concept | SQLite implementation |
| --- | --- |
| `LEFT(text, n)`, `RIGHT(text, n)` | CASE + SUBSTR with NULL, zero and signed-length handling |
| `STARTS_WITH`, `ENDS_WITH` | SUBSTR/LENGTH comparison, including empty prefixes/suffixes |
| `CONCAT_WS(separator, ...)` | Conditional separator insertion preserving empty strings and skipping NULL positions |
| `LAST_DAY(date)` | DATE(date, 'start of month', '+1 month', '-1 day') |
| `EXTRACT(ISODOW FROM date)` | Monday=1 through Sunday=7 from SQLite %w |
| `EXTRACT(WEEK FROM date)` | ISO-8601 week via nearest Thursday, including year transitions |
| `EXTRACT(ISOYEAR FROM date)` | ISO week-based year via nearest Thursday |

The `LEFT/RIGHT` AST includes a source-specific
`negative_length_returns_empty` flag. The generator follows it rather
than assuming all source dialects treat negative lengths alike.

`CONCAT_WS` retains **empty non-NULL arguments** as actual positions.
That avoids a SQLite 3.44–3.50.1 edge case where the built-in function
could omit them, changing results such as
`CONCAT_WS('-', '', '')` from `'-'` to `''`.

## Tests and evidence

- [Live cross-type engine sweep](../research/duckdb_sqlite_cross_type_sweep.py):
  58 expressions over 904 synthetic fixture rows, source DuckDB, target
  SQLite. Specific fixes are pinned with `--require-ids` in CI.
- [Independent live engine regression suite](../tests/test_queryport_sqlite_string_iso.py):
  25 source expressions over 9 focused rows, including negative lengths,
  NULLs, Unicode, ISO week/year transitions and empty fields.
- ISO week/year/weekday expression independently compared against 10,000
  random Python `date.isocalendar()` values (1900–2099), all equal.
- Entire original SQLGlot test suite remains a mandatory merge gate.

## Boundaries

These are **value comparisons**, not universal proof of equivalence.
Unicode casing, locale-sensitive collations, grapheme-cluster string slicing,
float-to-int casting, FULL timestamp types, time zones, and various
unsupported functions remain separate issues. In particular, stock
SQLite `LOWER/UPPER` does not implement arbitrary Unicode casing; QueryPort
must not silently call a conversion verified when those expressions are
present without matching runtime capabilities.

Official reference:
- [DuckDB text functions](https://duckdb.org/docs/stable/sql/functions/char)
- [SQLite core scalar functions](https://sqlite.org/lang_corefunc.html)
- [SQLite CONCAT_WS issue](https://sqlite.org/forum/forumpost/52503ac21d)
