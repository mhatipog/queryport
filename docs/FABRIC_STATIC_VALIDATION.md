# QueryPort strict Fabric validation (experimental)

The stable `sqlglot` API is unchanged. A new opt-in API refuses **known invalid**
Fabric target constructs before returning transpiled SQL:

```python
from sqlglot.queryport import strict_transpile, UnsupportedFabricFeature

try:
    result = strict_transpile(
        "SELECT TOP (10) amount FROM dbo.sales ORDER BY amount DESC",
        read="tsql",
        profile="fabric-warehouse",
    )
    print(result.sql)
    # result.semantic_equivalence_proven is always False
except UnsupportedFabricFeature as exc:
    print("Needs manual migration:", exc)
```

Supported profiles: `fabric-warehouse` and `fabric-lakehouse-sql-endpoint`.
The validator uses T-SQL lexical tokens, ignores SQL text inside string literals and
quoted identifiers, and rejects opaque SQLGlot command fallbacks.

## Recognized limitations

Warehouse: CREATE USER, CREATE MATERIALIZED VIEW, CREATE TRIGGER,
CREATE SYNONYM, SELECT FOR XML, SET ROWCOUNT,
SET TRANSACTION ISOLATION LEVEL, WITH RECURSIVE.

Lakehouse SQL analytics endpoint additionally rejects DML
INSERT/UPDATE/DELETE/MERGE/TRUNCATE and CREATE/ALTER/DROP TABLE. Note the
Lakehouse SQL endpoint still supports certain *metadata* objects, e.g. views;
a blanket read-only ban on all DDL would be incorrect.

When translating **from Oracle**, strict mode also blocks a zero-length string
literal, because Oracle interprets it as NULL whereas Fabric SQL Server-style T-SQL
does not. This is a source semantic incompatibility, not a Fabric syntax error.
[Oracle: Nulls](https://docs.oracle.com/en/database/oracle/oracle-database/19/sqlrf/Nulls.html).

This is an intentionally limited static denylist, **not** a Fabric-compatible
SQL grammar or proof of successful execution. Some unsupported constructs may
escape detection. Even if no violations are reported, independently validate
against the actual Fabric endpoint, credentials, workspace, schemas, version,
data types, workload and results before executing production SQL.

## Documentation

- [Microsoft: Fabric Warehouse T-SQL surface area](https://learn.microsoft.com/en-us/fabric/data-warehouse/tsql-surface-area)
- [Microsoft: Lakehouse SQL analytics endpoint](https://learn.microsoft.com/en-us/fabric/data-engineering/lakehouse-sql-analytics-endpoint)

The source and output SQL both require a valid SQLGlot AST without `Command`
fallbacks; an unsupported or opaque conversion fails closed.
