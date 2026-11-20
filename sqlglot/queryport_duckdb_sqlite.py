"""Opt-in, source-aware DuckDB -> stock SQLite semantic conversions.

The ordinary SQLGlot generator and other source dialects remain unchanged.
Only transformations that have independently executable DuckDB/SQLite
regression tests should be added here; unsupported cases are reported, not
silently described as semantically equivalent.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from sqlglot import exp, parse
from sqlglot.errors import ErrorLevel
from sqlglot.optimizer.annotate_types import annotate_types
from sqlglot.queryport_port import _date_operand


class UnsafeDuckDBPort(ValueError):
    """An unverified conversion was requested in strict mode."""


@dataclass(frozen=True)
class DuckDBPortResult:
    sql: tuple[str, ...]
    rewritten_date_timestamp: int = 0
    rewritten_padding: int = 0
    rewritten_float_to_int: int = 0
    unresolved: tuple[str, ...] = ()
    source_engine_executed: bool = False
    target_engine_executed: bool = False
    semantic_equivalence_proven: bool = False


def _pad_sqlite(node: exp.Pad, schema: dict[str, Any] | None) -> str | None:
    """Return a bounded, portable scalar CASE for one-character padding.

    No evaluation of volatile string expressions: only a column with a trusted
    string type or a literal can be repeated in the generated SQL. Stock SQLite
    has no LPAD/RPAD; a fixed-size ZEROBLOB expands to exactly N pad characters.
    This does not handle embedded NUL, grapheme-based lengths or binary pads.
    """
    source = node.this
    amount = node.expression
    fill = node.args.get("fill_pattern")
    if not isinstance(amount, exp.Literal) or not amount.is_number:
        return None
    try:
        width = int(amount.name)
    except ValueError:
        return None
    if str(width) != amount.name or not 0 <= width <= 1024:
        return None
    if fill is None:
        pattern = " "
    elif isinstance(fill, exp.Literal) and fill.is_string:
        pattern = fill.name
    else:
        return None
    if len(pattern) != 1 or pattern == "\x00":
        return None
    if isinstance(source, exp.Literal):
        if not source.is_string:
            return None
    elif isinstance(source, exp.Column):
        # Columns without a trusted schema may be numeric/blob/JSON and their
        # source DuckDB LPAD overload cannot be inferred from the SQL alone.
        from sqlglot.queryport_port import _single_table_schema_type
        source_type = _single_table_schema_type(source, schema)
        if source_type not in ("VARCHAR", "STRING", "TEXT", "CHAR", "CHARACTER", "BPCHAR"):
            return None
    else:
        return None

    value = source.sql("sqlite", unsupported_level=ErrorLevel.RAISE)
    fill_sql = exp.Literal.string(pattern).sql("sqlite")
    padded = f"REPLACE(HEX(ZEROBLOB({width})), '00', {fill_sql})"
    prefix = f"SUBSTR({padded}, 1, {width} - LENGTH({value}))"
    preserved = f"SUBSTR({value}, 1, {width})"
    if node.args.get("is_left"):
        branch = f"{prefix} || {value}"
    else:
        branch = f"{value} || {prefix}"
    return (
        f"(CASE WHEN {value} IS NULL THEN NULL "
        f"WHEN LENGTH({value}) >= {width} THEN {preserved} "
        f"ELSE {branch} END)"
    )


def _bankers_int_cast_sql(
    expression: exp.Cast,
    schema: dict[str, Any] | None,
    bounds: dict[str, tuple[float, float]] | None,
) -> tuple[str | None, str | None]:
    """SQLite truncates double -> INT; DuckDB rounds to nearest, ties even.

    The rewrite only applies to one-table DOUBLE columns with a trusted
    finite input range that is guaranteed to fit DuckDB's signed INT32.
    Decimal, FLOAT32, dynamic expressions, unbounded inputs, overflow and
    TRY_CAST are intentionally excluded. Column expressions are stable under
    repeated evaluation in the generated scalar CASE.
    """
    if type(expression) is not exp.Cast or not expression.is_type(exp.DType.INT):
        return None, None
    source = expression.this
    if not isinstance(source, exp.Column):
        return None, None
    from sqlglot.queryport_port import _single_table_schema_type
    if _single_table_schema_type(source, schema) != "DOUBLE":
        return None, None
    interval = bounds.get(source.name) if bounds is not None else None
    if (
        interval is None or len(interval) != 2
        or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in interval)
        or interval[0] > interval[1]
        or interval[0] < -2147483648 or interval[1] > 2147483647
    ):
        return None, "CAST(DOUBLE AS INTEGER): supply trusted finite signed-INT32-safe column bounds"

    x = source.sql("sqlite", unsupported_level=ErrorLevel.RAISE)
    trunc = f"CAST({x} AS INTEGER)"
    # SQLite ROUND() uses half-away-from-zero; handle *only* exact ties
    # separately using the parity of the truncated integer.
    tie = f"ABS({x}) - CAST(ABS({x}) AS INTEGER) = 0.5"
    candidate = (
        f"(CASE WHEN {tie} THEN "
        f"(CASE WHEN ({trunc} % 2) = 0 THEN {trunc} "
        f"ELSE {trunc} + (CASE WHEN {x} < 0 THEN -1 ELSE 1 END) END) "
        f"ELSE ROUND({x}) END)"
    )
    return f"CAST({candidate} AS INTEGER)", None


def _duckdb_date_plus_interval(node: exp.Expr, schema: dict[str, Any] | None) -> bool:
    """Recognize DuckDB DATE + an interval whose unit is explicit.

    Return TIMESTAMP only for trusted DATE operands, not TIMESTAMP, VARCHAR,
    integer or untyped expressions. The SQLite month/day arithmetic comes
    from the existing generator; DATETIME preserves the DuckDB result type.
    """
    if isinstance(node, exp.DateAdd):
        base, interval = node.this, node.expression
    elif isinstance(node, exp.Add):
        base, interval = node.this, node.expression
        if isinstance(base, exp.Interval):
            base, interval = interval, base
    else:
        return False
    return (
        isinstance(interval, exp.Interval)
        and interval.unit is not None
        and _date_operand(base, schema)
    )


def port_duckdb_to_sqlite(
    sql: str, *, schema: dict[str, Any] | None = None,
    float_bounds: dict[str, tuple[float, float]] | None = None,
    strict: bool = True
) -> DuckDBPortResult:
    """Convert proven DuckDB scalar cases, leaving ordinary SQLGlot unchanged.

    schema is a trusted DuckDB source schema: e.g.
        {"t": {"d": "DATE", "s": "VARCHAR"}}
    strict=True raises on recognized but unverified operations rather than
    emitting SQL that stock SQLite may execute incorrectly or not at all.
    """
    trees = parse(sql, read="duckdb", error_level=ErrorLevel.RAISE)
    if not trees or any(tree is None for tree in trees):
        raise UnsafeDuckDBPort("No complete source SQL statement")
    converted: list[str] = []
    unresolved: list[str] = []
    pad_count = date_count = numeric_count = 0

    for tree in trees:
        if isinstance(tree, exp.Command) or tree.find(exp.Command):
            raise UnsafeDuckDBPort("Opaque SQL command cannot be verified")
        if schema is not None:
            tree = annotate_types(tree, schema=schema, dialect="duckdb")

        def fix(node: exp.Expr) -> exp.Expr:
            nonlocal pad_count, date_count, numeric_count
            if type(node) is exp.Cast and node.is_type(exp.DType.INT):
                replacement, warning = _bankers_int_cast_sql(
                    node, schema, float_bounds
                )
                if warning:
                    unresolved.append(warning)
                    return node
                if replacement:
                    numeric_count += 1
                    return exp.paren(parse(
                        replacement, read="sqlite", error_level=ErrorLevel.RAISE
                    )[0])
            if isinstance(node, exp.Pad):
                rewritten = _pad_sqlite(node, schema)
                if rewritten is None:
                    unresolved.append("LPAD/RPAD: requires trusted text and bounded literal one-character padding")
                    return node
                pad_count += 1
                return exp.paren(parse(rewritten, read="sqlite", error_level=ErrorLevel.RAISE)[0])
            if _duckdb_date_plus_interval(node, schema):
                date_count += 1
                return exp.Anonymous(this="DATETIME", expressions=[node.copy()])
            # A DATE_ADD with no trustworthy base type can silently lose the
            # DuckDB TIMESTAMP return contract. Do not present that as safe.
            if isinstance(node, exp.DateAdd) and isinstance(node.expression, exp.Interval):
                base = node.this
                if not base.is_type(*exp.DataType.TEMPORAL_TYPES):
                    unresolved.append("DATE_ADD: untyped temporal base; supply trusted source schema")
            if isinstance(node, (exp.Reverse, exp.RegexpReplace, exp.SplitPart)):
                unresolved.append(f"{type(node).__name__}: stock SQLite has no verified equivalent")
            return node

        fixed = tree.transform(fix, copy=True)
        if strict and unresolved:
            raise UnsafeDuckDBPort("; ".join(dict.fromkeys(unresolved)))
        generated = fixed.sql("sqlite", unsupported_level=ErrorLevel.RAISE)
        reparsed = parse(generated, read="sqlite", error_level=ErrorLevel.RAISE)
        if len(reparsed) != 1 or reparsed[0] is None or (
            isinstance(reparsed[0], exp.Command) or reparsed[0].find(exp.Command)
        ):
            raise UnsafeDuckDBPort("Target SQL failed a complete SQLite parse")
        converted.append(generated)
    return DuckDBPortResult(
        sql=tuple(converted),
        rewritten_date_timestamp=date_count,
        rewritten_padding=pad_count,
        rewritten_float_to_int=numeric_count,
        unresolved=tuple(dict.fromkeys(unresolved)),
    )
