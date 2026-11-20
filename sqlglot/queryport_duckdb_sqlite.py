"""Opt-in, source-aware DuckDB -> stock SQLite semantic conversions.

The ordinary SQLGlot generator and other source dialects remain unchanged.
Only transformations that have independently executable DuckDB/SQLite
regression tests should be added here; unsupported cases are reported, not
silently described as semantically equivalent.
"""
from __future__ import annotations

from dataclasses import dataclass
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
    sql: str, *, schema: dict[str, Any] | None = None, strict: bool = True
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
    pad_count = date_count = 0

    for tree in trees:
        if isinstance(tree, exp.Command) or tree.find(exp.Command):
            raise UnsafeDuckDBPort("Opaque SQL command cannot be verified")
        if schema is not None:
            tree = annotate_types(tree, schema=schema, dialect="duckdb")

        def fix(node: exp.Expr) -> exp.Expr:
            nonlocal pad_count, date_count
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
        unresolved=tuple(dict.fromkeys(unresolved)),
    )
