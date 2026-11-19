# QueryPort engineering plan — 19 November 2026

QueryPort is a public, MIT-licensed fork of [SQLGlot](https://github.com/tobymao/sqlglot).
It begins with its proven parser/transpiler and aims to make **dialect conversion testably correct**, especially for Oracle SQL/PLSQL, Spark SQL, and Microsoft Fabric's T-SQL surfaces. The name is a project identity, **not** a claim of superior coverage today. The Python module remains `sqlglot` until a separately tested packaging decision.

## Non-negotiable engineering contract

1. **No silent loss**: opaque `exp.Command`, dropped statements, altered types, unresolved identifiers, unsupported features and unverifiable side-effects must be reported; a syntactically emitted string is not "success".
2. **Source AND target versions**: for example, `oracle-19c` vs `oracle-26ai`, `spark-3.5` vs `spark-4.1`, `fabric-warehouse` vs `fabric-lakehouse-sql-endpoint`.
3. **Preserve semantics over syntax**: verify NULL, three-valued logic, integer/date arithmetic, precision, time zones, string collation, empty-string handling, ordering, aggregation, duplicates, transactions and errors.
4. **Independent oracles**: SQLGlot round-trip self-consistency never establishes semantic correctness. Execute source and target against their respective engines where possible, compare normalized outputs and side-effects.
5. **Deterministic and reproducible**: pin engine/library versions, SQL case IDs, generated data/seed, schema, locale/time zone and test hardware. Preserve smallest failing reproducer and first regression commit.
6. **Measured benefit**: compare the current fork to upstream with identical datasets; do not claim "10x" based on synthetic pass rates, number of dialects, or favorable hand-picked examples.
7. **Guarded autonomy**: agents may propose changes and add test cases, but changes cannot merge without established regression gates. Changes involving data loss/mutation or uncertain conversion need explicit diagnostics.

## Capability profiles (not all the same dialect)

| Profile | Real target | Distinct gate |
|---|---|---|
| `oracle-sql` | Oracle SELECT/DDL/DML, semantics incl. `NVL`, `DECODE`, `ROWNUM`, `CONNECT BY`, `DATE`, empty string | Oracle parser + execution engine; check empty-string=NULL, dates, implicit casts |
| `oracle-plsql` | Procedural blocks, packages, variables, cursors, exceptions, dynamic SQL, side-effects | Explicit procedural IR and stateful trace comparison; ordinary SQL AST insufficient |
| `spark-3.5` | Spark Runtime 1.3 in Fabric | Query/DML validation only; do not assume Spark 4.x scripting |
| `spark-4.1` | Fabric Runtime 2.0; newer Spark SQL/PSM scripting | SQL scripting version gate; compile/execute and check handler, cursor and transaction differences |
| `fabric-warehouse` | Microsoft Fabric Warehouse T-SQL | Separate capability rules; warehouse DML and `MERGE` supported, but no triggers, recursive queries, materialized views, `CREATE USER`, `FOR XML` |
| `fabric-lakehouse-sql-endpoint` | Read-centric T-SQL facade over Lakehouse Delta | No table CREATE/ALTER/DROP or INSERT/UPDATE/DELETE to lakehouse tables through SQL analytics endpoint; view/procedure/function behavior differs |
| `tsql-sqlserver` | SQL Server T-SQL reference | Not an interchangeable correctness oracle for Fabric Warehouse |

The Spark target is **version-specific**: SQL scripting/PSM is generally available in Apache Spark 4.1. For Oracle PL/SQL, first attempt a documented, semantics-preserving translation to SQL scripting on supporting runtimes, then use an explicit orchestrated/PySpark route for constructs without an equivalent. Never silently emit only the SQL queries and lose procedural control flow.

**Sources:** [Oracle 26ai PL/SQL](https://docs.oracle.com/en/database/oracle/oracle-database/26/lnpls/index.html); [Spark 4.1 scripting](https://spark.apache.org/docs/4.1.4/sql-ref-scripting.html); [Fabric Runtime 2.0](https://learn.microsoft.com/en-us/fabric/data-engineering/runtime-2-0); [Fabric Warehouse T-SQL](https://learn.microsoft.com/en-us/fabric/data-warehouse/tsql-surface-area); [Fabric persisted types](https://learn.microsoft.com/en-us/fabric/data-warehouse/data-types).

## Five independent gates

- **G0: lexical and parse coverage** — no unparsed tail, `Command` fallback or lost statement, correct source span and source kind.
- **G1: generation/round-trip** — target SQL parses under the named dialect; stable AST structure and types where justified. This is syntax evidence ONLY.
- **G2: target acceptance** — actual target engine parses/plans/compiles output in the specified version and profile.
- **G3: result equivalence** — source and target execute against paired fixtures: exact bag semantics, explicit ordering rules, NULLs, numeric tolerances only if justified, and expected error conditions.
- **G4: stateful equivalence** — procedural program output, table mutations, transactions, error handling, cardinality and side-effects match. Apply to PL/SQL, stored procedures, DML and workflow rewrites.

Report each gate separately. `G1 pass` must never be called `semantically verified`.

## Test generation and improvement loop

1. **Source cases**: licensed public dialect conformance examples; real migration patterns with secrets and business identifiers removed; high-value published bugs; curated hard cases.
2. **Contrast pairs**: Oracle→Spark 3.5/4.1; Oracle→Fabric Warehouse; Spark→Fabric Warehouse; T-SQL→Spark; round-trips on each dialect.
3. **Metamorphic expansion**: deterministic mutations of data types, NULL/empty strings, leap dates, offsets, collations, identifier quoting, nested expressions, ORDER BY ties and schema variants.
4. **Execution**: run on free OCI runner for static parsing and local DuckDB/SQLite; use licensed/free local Oracle and Spark engines only if available; use real Fabric tests only in an authorized isolated workspace and within explicit budget.
5. **Minimize failures**: shrink SQL AST and datasets while reproducing, attach dialect/version, error and outputs; reject false-positive oracles.
6. **Agent patch proposal**: a small targeted change with regression tests, SQLGlot API compatibility check and performance deltas.
7. **Promote or revert**: same full upstream suite, differential corpus, negative/unsupported tests and resource usage; failures block promotion. Prioritize by independently reproduced frequency and impact.
8. **Upstream sync**: import security/bug changes without automatically overwriting QueryPort's evidence, re-run both baseline and new corpus.

## Baselines and scoreboard

Keep upstream/fork comparisons side-by-side on **identical pinned commits and test cases**. Record for each edge and profile: attempted cases, parsed cases, target-accepted cases, result-equivalent cases, statefully equivalent cases, explicit unsupported cases, unexpected successes/failures, p50/p95 latency and CPU-memory cost. Publish a public machine-readable scoreboard with provenance and CI links; separate synthetic from real programs.

Treat unsupported-but-detected as a safer outcome than a silent wrong answer. The first major win may be converting accidental success into an explicit, actionable incompatibility report.

## Initial sequence

1. Land this engineering plan and a fixed, independently reviewed hard-case corpus.
2. Run the same corpus against unmodified SQLGlot and QueryPort on OCI. First outputs are *diagnostic*, not semantic-success claims.
3. Add Spark (pinned 3.5 and 4.1) parse/execution validation, then Oracle as a separately licensed engine, then a budget-guarded authorized Fabric validation.
4. Implement explicit `fabric-warehouse` and `fabric-lakehouse-sql-endpoint` capability validators.
5. Choose one demonstrated incorrect conversion with a small, separately validated fix and repeat differential testing.
