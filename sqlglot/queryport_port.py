"""Source-aware DATE-minus-DATE portability for PostgreSQL/DuckDB -> SQLite.

Deliberately opt-in. SQLite subtraction of ISO date strings/casts otherwise silently
coerces to numbers (usually the year), yielding wrong results. Do NOT install this
rewrite globally: PostgreSQL/DuckDB DATE - DATE means elapsed whole days; SQLite
and other dialects do not guarantee that semantic. Untyped subtraction is left
unchanged with a warning, not misrepresented as a verified conversion.

References:
  https://www.postgresql.org/docs/current/functions-datetime.html
  https://duckdb.org/docs/current/sql/data_types/interval
  https://www.sqlite.org/lang_datefunc.html
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlglot import exp, parse
from sqlglot.errors import ErrorLevel
from sqlglot.optimizer.annotate_types import annotate_types


_DATE_TYPES = frozenset({exp.DType.DATE, exp.DType.DATE32})
_SOURCE_DIALECTS = frozenset({"postgres", "duckdb"})


class UnsafeDateConversion(ValueError):
    """A statement could not be safely parsed/gener­ated with this operation."""


@dataclass(frozen=True)
class DatePortResult:
    sql: tuple[str, ...]
    read: str
    write: str = "sqlite"
    date_subtractions_rewritten: int = 0
    untyped_subtractions: int = 0
    engine_executed: bool = False
    semantic_equivalence_proven: bool = False


def _explicit_date(expr: exp.Expr) -> bool:
    if isinstance(expr, exp.Paren):
        return _explicit_date(expr.this)
    if isinstance(expr, (exp.Cast, exp.TryCast)):
        to = expr.args.get("to")
        return isinstance(to, exp.DataType) and to.this in _DATE_TYPES
    return isinstance(expr, (exp.DateStrToDate, exp.TsOrDsToDate))


def _single_table_schema_type(
    node: exp.Expr, schema: dict[str, Any] | None
) -> str | None:
    """Resolve an unqualified column ONLY for a single physical-table SELECT.

    SQLGlot type annotation handles qualified columns, but deliberately leaves
    unqualified identifiers unresolved. We can safely resolve them ourselves
    only when there is exactly one physical source table and no nested sources.
    """
    if not schema or not isinstance(node, exp.Column) or node.table:
        return None
    select = node.find_ancestor(exp.Select)
    if select is None:
        return None
    tables = list(select.find_all(exp.Table))
    if len(tables) != 1:
        return None
    table_name = tables[0].name
    candidates = [value for name, value in schema.items()
                  if isinstance(name, str) and name.lower() == table_name.lower()]
    if len(candidates) != 1 or not isinstance(candidates[0], dict):
        return None
    columns = candidates[0]
    matched = [v for k, v in columns.items()
               if isinstance(k, str) and k.lower() == node.name.lower()]
    if len(matched) != 1:
        return None
    value = matched[0]
    if isinstance(value, exp.DataType):
        return value.this.value
    return value.upper().strip() if isinstance(value, str) else None


def _date_operand(expr: exp.Expr, schema: dict[str, Any] | None) -> bool:
    if _explicit_date(expr):
        return True
    if schema is None:
        return False
    if expr.is_type(*_DATE_TYPES):
        return True
    return _single_table_schema_type(expr, schema) in ("DATE", "DATE32")


def _ambiguous_subtraction(expr: exp.Sub, schema: dict[str, Any] | None) -> bool:
    def unresolved(side: exp.Expr) -> bool:
        if _explicit_date(side):
            return False
        if schema is not None and (
            (side.type and not side.is_type(exp.DType.UNKNOWN))
            or _single_table_schema_type(side, schema) is not None
        ):
            return False
        return any(isinstance(node, exp.Column) for node in side.walk())

    return unresolved(expr.this) or unresolved(expr.expression)


def port_date_subtraction(
    sql: str, *, read: str, schema: dict[str, Any] | None = None
) -> DatePortResult:
    """Rewrite explicit or schema-typed DATE - DATE in PG/DuckDB for SQLite.

    An optional *trusted* column schema can resolve column subtractions. The
    return value reports the number of transformed and unresolved expressions.
    No actual source engine is run and semantic equivalence is not certified.

    Usage:
      port_date_subtraction(
          "SELECT d2 - d1 FROM events",
          read="postgres",
          schema={"events": {"d1": "DATE", "d2": "DATE"}},
      ).sql
    """
    if read not in _SOURCE_DIALECTS:
        raise ValueError(f"Only PostgreSQL and DuckDB are supported; got {read!r}")

    trees = parse(sql, read=read, error_level=ErrorLevel.RAISE)
    if not trees or any(tree is None for tree in trees):
        raise UnsafeDateConversion("Missing/empty source statement")

    results: list[str] = []
    rewritten = 0
    ambiguous = 0
    for tree in trees:
        if isinstance(tree, exp.Command) or tree.find(exp.Command):
            raise UnsafeDateConversion("Opaque source SQL cannot be safely rewritten")

        if schema is not None:
            tree = annotate_types(tree, schema=schema, dialect=read)

        def transform(node: exp.Expr) -> exp.Expr:
            nonlocal rewritten, ambiguous
            if not isinstance(node, exp.Sub):
                return node
            if _date_operand(node.this, schema) and _date_operand(
                node.expression, schema
            ):
                rewritten += 1
                return exp.DateDiff(
                    this=node.this.copy(),
                    expression=node.expression.copy(),
                    unit=exp.var("DAY"),
                    date_part_boundary=True,
                )
            if _ambiguous_subtraction(node, schema):
                ambiguous += 1
            return node

        fixed = tree.transform(transform, copy=True)
        generated = fixed.sql(dialect="sqlite", unsupported_level=ErrorLevel.RAISE)
        if not generated.strip():
            raise UnsafeDateConversion("Empty target SQL")
        target = parse(generated, read="sqlite", error_level=ErrorLevel.RAISE)
        if len(target) != 1 or target[0] is None or (
            isinstance(target[0], exp.Command) or target[0].find(exp.Command)
        ):
            raise UnsafeDateConversion("Generated SQLite SQL did not fully reparse")
        results.append(generated)

    return DatePortResult(
        sql=tuple(results),
        read=read,
        date_subtractions_rewritten=rewritten,
        untyped_subtractions=ambiguous,
    )
