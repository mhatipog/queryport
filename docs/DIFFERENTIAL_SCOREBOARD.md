# QueryPort vs pinned legacy SQLGlot — executable SQL portability scoreboard

This is the first **side-by-side** SQL output correctness benchmark. It is not a
claim that QueryPort is 10× better across SQL generally.

The benchmark runs **identical, committed SQL examples** through two
installations, then executes the transpiled SQLite SQL and checks independent
reference outputs. Each row records the generated target SQL, actual observed
value, source dialect, comparison, error and pass/fail outcome.

- Legacy pinned SQLGlot commit: `2deb754793ee39a69c2535b198b5b07d2cf04f31`
- Candidate: exact QueryPort branch/main SHA checked out by OCI workflow
- Fixture: [`research/sqlite_differential_cases.json`](../research/sqlite_differential_cases.json)
- Runner: [`research/run_sqlite_differential.py`](../research/run_sqlite_differential.py)
- Comparator: [`research/compare_sqlite_benchmarks.py`](../research/compare_sqlite_benchmarks.py)
- OCI workflow: [`mhatipog/web-operations/.github/workflows/sqlglot-oci-validation.yml`](https://github.com/mhatipog/web-operations/actions/workflows/sqlglot-oci-validation.yml)

Run the same program with distinct `PYTHONPATH` roots:

```bash
PYTHONPATH=/path/to/legacy-sqlglot python3 research/run_sqlite_differential.py \
  --label legacy --output /tmp/legacy.json
PYTHONPATH=/path/to/queryport python3 research/run_sqlite_differential.py \
  --label queryport --output /tmp/queryport.json
python3 research/compare_sqlite_benchmarks.py \
  /tmp/legacy.json /tmp/queryport.json --require-gain
```

The `--require-gain` gate fails if QueryPort introduces **any** observed
regression or has **zero** independently observed improvements on this corpus.
The comparator checks case-ID equality so a branch cannot increase its apparent
success rate by deleting hard cases.

### Current coverage

The 32 curated source cases focus on important date and calendar semantics:
T-SQL DATEDIFF boundaries, MySQL/Oracle/Spark end-of-month rules, DuckDB/BigQuery
DATE_DIFF and PostgreSQL/DuckDB explicitly typed DATE subtraction.
The QueryPort source-aware date API is used only in the two clearly marked
cases; SQLGlot's stock transpiler is the original baseline.

### Scientific limitations

- These are **selected regression fixtures**, not a representative random
  sample of all SQL. The measured percentage is not the overall dialect
  correctness rate, nor a 10× performance or correctness claim.
- Target **SQLite is executed**; source engine results are derived from
  documented semantics and canonical expected outputs. More demanding
  cross-engine execution against actual Oracle, Spark and Fabric remains needed.
- A syntax-valid SQL string is not evidence of semantic correctness. Baseline
  or candidate parse/generator/execution failure counts as a failed case.
- Each baseline comparison requires **the same version and fixture set**;
  later upstream SQLGlot releases should receive their own separately pinned
  comparison rather than silently changing this baseline.
- The checker intentionally does not upload datasets, source code or results as
  GitHub artifacts.
