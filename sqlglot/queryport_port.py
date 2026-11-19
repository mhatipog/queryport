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


def _date_operand(expr: exp.Expr, trust_schema: bool) -> bool:
    return _explicit_date(expr) or (trust_schema and expr.is_type(*_DATE_TYPES))


def _ambiguous_subtraction(expr: exp.Sub, trust_schema: bool) -> bool:
    if trust_schema and all(
        side.type and not side.is_type(exp.DType.UNKNOWN)
        for side in (expr.this, expr.expression)
    ):
        return False
    return (
        any(isinstance(node, exp.Column) for side in (expr.this, expr.expression)
            for node in side.walk())
        and not (_explicit_date(expr.this) and _explicit_date(expr.expression))
    )


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
            if _date_operand(node.this, schema is not None) and _date_operand(
                node.expression, schema is not None
            ):
                rewritten += 1
                return exp.DateDiff(
                    this=node.this.copy(),
                    expression=node.expression.copy(),
                    unit=exp.var("DAY"),
                    date_part_boundary=True,
                )
            if _ambiguous_subtraction(node, schema is not None):
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
