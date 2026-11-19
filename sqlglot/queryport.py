"""QueryPort strict, *statically scoped* transpilation for Microsoft Fabric targets.

No claim of target-engine acceptance or semantic equivalence is made. A clean static
validation only means no *known and encoded* Fabric feature violation was detected.

Compatibility policy sources (reviewed 2026-11-19):
  https://learn.microsoft.com/en-us/fabric/data-warehouse/tsql-surface-area
  https://learn.microsoft.com/en-us/fabric/data-engineering/lakehouse-sql-analytics-endpoint
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal

from sqlglot import exp, parse
from sqlglot.dialects.tsql import TSQL
from sqlglot.errors import ErrorLevel
from sqlglot.tokens import TokenType


Profile = Literal["fabric-warehouse", "fabric-lakehouse-sql-endpoint"]
_PROFILES = frozenset(("fabric-warehouse", "fabric-lakehouse-sql-endpoint"))
_NON_CODE = frozenset({
    TokenType.STRING, TokenType.NATIONAL_STRING, TokenType.RAW_STRING,
    TokenType.NATIONAL_RAW_STRING, TokenType.UNICODE_STRING, TokenType.HEX_STRING,
    TokenType.BYTE_STRING, TokenType.BIT_STRING, TokenType.IDENTIFIER,
})


class UnsupportedFabricFeature(ValueError):
    """A source/target operation violates a documented Fabric capability."""


@dataclass(frozen=True)
class StaticConversion:
    sql: tuple[str, ...]
    read: str
    profile: Profile
    gates: tuple[str, ...] = (
        "source_parsed",
        "target_reparsed",
        "known_fabric_unsupported_patterns_checked",
    )
    engine_executed: bool = False
    semantic_equivalence_proven: bool = False


def _word_tokens(sql: str) -> list[str]:
    """Tokenize T-SQL and ignore string literals and quoted identifiers.

    A text regex over raw SQL would wrongly reject statements such as
    SELECT 'CREATE USER' AS documentation. A real tokenizer is essential.
    """
    result: list[str] = []
    for token in TSQL.Tokenizer().tokenize(sql):
        if token.token_type in _NON_CODE:
            result.append("<literal>")
        else:
            result.extend(re.findall(r"[A-Z_][A-Z_0-9]*|[()]", token.text.upper()))
    return result


def _has_sequence(words: list[str], *pattern: str) -> bool:
    n = len(pattern)
    return any(tuple(words[i:i + n]) == pattern for i in range(len(words) - n + 1))


def fabric_violations(sql: str, profile: Profile) -> tuple[str, ...]:
    """Return recognized target incompatibilities; empty does NOT mean verified.

    This is a conservative denylist of well-documented unsupported constructs,
    not a full Fabric dialect parser. Quoted literals/identifiers are ignored.
    """
    if profile not in _PROFILES:
        raise ValueError(f"Unknown Fabric target profile {profile!r}")

    words = _word_tokens(sql)
    issues: list[str] = []

    forbidden = (
        (("CREATE", "USER"), "FABRIC_CREATE_USER"),
        (("CREATE", "MATERIALIZED", "VIEW"), "FABRIC_MATERIALIZED_VIEW"),
        (("CREATE", "TRIGGER"), "FABRIC_TRIGGERS"),
        (("CREATE", "SYNONYM"), "FABRIC_SYNONYMS"),
        (("FOR", "XML"), "FABRIC_FOR_XML"),
        (("SET", "ROWCOUNT"), "FABRIC_SET_ROWCOUNT"),
        (("SET", "TRANSACTION", "ISOLATION", "LEVEL"), "FABRIC_SET_ISOLATION"),
        (("WITH", "RECURSIVE"), "FABRIC_RECURSIVE_CTE"),
    )
    for sequence, code in forbidden:
        if _has_sequence(words, *sequence):
            issues.append(code)

    if profile == "fabric-lakehouse-sql-endpoint":
        for command in ("INSERT", "UPDATE", "DELETE", "MERGE", "TRUNCATE"):
            if command in words:
                issues.append("LAKEHOUSE_READONLY_" + command)
        for operation in ("CREATE", "ALTER", "DROP"):
            if _has_sequence(words, operation, "TABLE"):
                issues.append("LAKEHOUSE_READONLY_" + operation + "_TABLE")

    return tuple(sorted(set(issues)))


def strict_transpile(sql: str, *, read: str, profile: Profile) -> StaticConversion:
    """Transpile with parse/generate checks and known Fabric restrictions.

    Callers must separately validate SQL on the actual Fabric engine and perform
    semantic comparison if they need correctness guarantees. No claim that these
    syntactic gates cover all unsupported features is implied.
    """
    if profile not in _PROFILES:
        raise ValueError(f"Unknown Fabric target profile {profile!r}")

    source = parse(sql, read=read, error_level=ErrorLevel.IMMEDIATE)
    if not source or any(tree is None for tree in source):
        raise UnsupportedFabricFeature("Empty or incomplete SQL parse")

    output: list[str] = []
    for tree in source:
        if tree.find(exp.Command) or isinstance(tree, exp.Command):
            raise UnsupportedFabricFeature("Opaque source statement cannot be verified")
        generated = tree.sql(dialect="tsql", unsupported_level=ErrorLevel.IMMEDIATE)
        if not generated.strip():
            raise UnsupportedFabricFeature("Generation produced an empty statement")
        target_trees = parse(generated, read="tsql", error_level=ErrorLevel.IMMEDIATE)
        if not target_trees or any(
            target is None or target.find(exp.Command) or isinstance(target, exp.Command)
            for target in target_trees
        ):
            raise UnsupportedFabricFeature("Generated target could not be fully parsed")
        issues = fabric_violations(generated, profile)
        if issues:
            raise UnsupportedFabricFeature(
                f"{profile}: documented unsupported features: " + ", ".join(issues)
            )
        output.append(generated)

    return StaticConversion(sql=tuple(output), read=read, profile=profile)
