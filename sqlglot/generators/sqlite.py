from __future__ import annotations

import typing as t

from sqlglot import exp, generator, transforms
from sqlglot.dialects.dialect import (
    any_value_to_max_sql,
    arrow_json_extract_sql,
    count_if_to_sum,
    generate_series_sql,
    groupconcat_sql,
    no_ilike_sql,
    no_pivot_sql,
    no_tablesample_sql,
    no_trycast_sql,
    rename_func,
    strposition_sql,
)
from sqlglot.generator import unsupported_args
from sqlglot.parsers.sqlite import SQLITE_NOW
from sqlglot.tokens import TokenType


def _transform_create(expression: exp.Expr) -> exp.Expr:
    """Move primary key to a column and place auto_increment after it."""
    schema = expression.this

    if isinstance(expression, exp.Create) and isinstance(schema, exp.Schema):
        defs = {}
        primary_key = None

        for e in schema.expressions:
            if isinstance(e, exp.ColumnDef):
                defs[e.name] = e
            elif isinstance(e, exp.PrimaryKey):
                primary_key = e

        if primary_key and len(primary_key.expressions) == 1:
            column = defs[primary_key.expressions[0].name]
            column.append(
                "constraints", exp.ColumnConstraint(kind=exp.PrimaryKeyColumnConstraint())
            )
            schema.expressions.remove(primary_key)

        for column in defs.values():
            primary_key_index = -1
            auto_increment = None
            auto_increment_index = -1

            for i, constraint in enumerate(column.constraints):
                if isinstance(constraint.kind, exp.PrimaryKeyColumnConstraint):
                    primary_key_index = i
                elif isinstance(constraint.kind, exp.AutoIncrementColumnConstraint):
                    auto_increment = constraint
                    auto_increment_index = i

            if auto_increment is not None and 0 <= auto_increment_index < primary_key_index:
                column.constraints.remove(auto_increment)
                column.constraints.insert(primary_key_index, auto_increment)

    return expression


def _generated_to_auto_increment(expression: exp.Expr) -> exp.Expr:
    if not isinstance(expression, exp.ColumnDef):
        return expression

    generated = expression.find(exp.GeneratedAsIdentityColumnConstraint)

    # Only rewrite true identity columns. Expression-bearing forms are computed
    # columns (GENERATED ALWAYS AS (expr)) and must keep their expression.
    if generated and generated.expression is None:
        t.cast(exp.ColumnConstraint, generated.parent).pop()

        not_null = expression.find(exp.NotNullColumnConstraint)
        if not_null:
            t.cast(exp.ColumnConstraint, not_null.parent).pop()

        expression.append(
            "constraints", exp.ColumnConstraint(kind=exp.AutoIncrementColumnConstraint())
        )

    return expression


class SQLiteGenerator(generator.Generator):
    SELECT_KINDS = ()
    TRY_SUPPORTED = False
    SUPPORTS_UESCAPE = False
    SUPPORTS_DECODE_CASE = False
    SET_OP_PARENTHESIZED_OPERANDS = False

    AFTER_HAVING_MODIFIER_TRANSFORMS = generator.AFTER_HAVING_MODIFIER_TRANSFORMS

    JOIN_HINTS = False
    TABLE_HINTS = False
    QUERY_HINTS = False
    NVL2_SUPPORTED = False
    JSON_PATH_BRACKETED_KEY_SUPPORTED = False
    SUPPORTS_CREATE_TABLE_LIKE = False
    SUPPORTS_TABLE_ALIAS_COLUMNS = False
    SUPPORTS_TO_NUMBER = False
    SUPPORTS_WINDOW_EXCLUDE = True
    EXCEPT_INTERSECT_SUPPORT_ALL_CLAUSE = False
    SUPPORTS_MEDIAN = False
    JSON_KEY_VALUE_PAIR_SEP = ","
    PARSE_JSON_NAME: str | None = None

    SUPPORTED_JSON_PATH_PARTS = {
        exp.JSONPathKey,
        exp.JSONPathRoot,
        exp.JSONPathSubscript,
    }

    TYPE_MAPPING = {
        **{k: v for k, v in generator.Generator.TYPE_MAPPING.items() if k != exp.DType.BLOB},
        exp.DType.BOOLEAN: "INTEGER",
        exp.DType.TINYINT: "INTEGER",
        exp.DType.SMALLINT: "INTEGER",
        exp.DType.INT: "INTEGER",
        exp.DType.BIGINT: "INTEGER",
        exp.DType.FLOAT: "REAL",
        exp.DType.DOUBLE: "REAL",
        exp.DType.DECIMAL: "REAL",
        exp.DType.CHAR: "TEXT",
        exp.DType.NCHAR: "TEXT",
        exp.DType.VARCHAR: "TEXT",
        exp.DType.NVARCHAR: "TEXT",
        exp.DType.BINARY: "BLOB",
        exp.DType.VARBINARY: "BLOB",
    }

    def nullsafeeq_sql(self, expression: exp.NullSafeEQ) -> str:
        return self.binary(expression, "IS")

    def nullsafeneq_sql(self, expression: exp.NullSafeNEQ) -> str:
        return self.binary(expression, "IS NOT")

    TOKEN_MAPPING = {
        TokenType.AUTO_INCREMENT: "AUTOINCREMENT",
    }

    TRANSFORMS = {
        **generator.Generator.TRANSFORMS,
        exp.AnyValue: any_value_to_max_sql,
        exp.Chr: rename_func("CHAR"),
        exp.CountIf: count_if_to_sum,
        exp.Create: transforms.preprocess([_transform_create]),
        exp.CurrentDate: lambda *_: "CURRENT_DATE",
        exp.CurrentTime: lambda *_: "CURRENT_TIME",
        exp.CurrentTimestamp: lambda *_: "CURRENT_TIMESTAMP",
        exp.CurrentVersion: lambda *_: "SQLITE_VERSION()",
        exp.ColumnDef: transforms.preprocess([_generated_to_auto_increment]),
        exp.DateStrToDate: lambda self, e: self.sql(e, "this"),
        exp.If: rename_func("IIF"),
        exp.ILike: no_ilike_sql,
        exp.JSONArrayAgg: unsupported_args("order", "null_handling", "return_type", "strict")(
            rename_func("JSON_GROUP_ARRAY")
        ),
        exp.JSONObjectAgg: lambda self, e: self._jsonobject_sql(e, name="JSON_GROUP_OBJECT"),
        exp.Levenshtein: unsupported_args("ins_cost", "del_cost", "sub_cost", "max_dist")(
            rename_func("EDITDIST3")
        ),
        exp.LogicalOr: rename_func("MAX"),
        exp.LogicalAnd: rename_func("MIN"),
        exp.Pivot: no_pivot_sql,
        exp.RegexpLike: lambda self, e: self.binary(e, "REGEXP"),
        exp.Select: transforms.preprocess(
            [
                transforms.eliminate_distinct_on,
                transforms.eliminate_qualify,
                transforms.eliminate_semi_and_anti_joins,
            ]
        ),
        exp.StrPosition: lambda self, e: strposition_sql(self, e, func_name="INSTR"),
        exp.TableSample: no_tablesample_sql,
        exp.TimeStrToTime: lambda self, e: self.sql(e, "this"),
        exp.TimeToStr: lambda self, e: self.func("STRFTIME", self.format_time(e), e.this),
        exp.TryCast: no_trycast_sql,
        exp.TsOrDsToTimestamp: lambda self, e: self.sql(e, "this"),
    }

    # SQLite doesn't generally support CREATE TABLE .. properties
    # https://www.sqlite.org/lang_createtable.html
    PROPERTIES_LOCATION = {
        **{
            prop: exp.Properties.Location.UNSUPPORTED
            for prop in generator.Generator.PROPERTIES_LOCATION
        },
        # There are a few exceptions (e.g. temporary tables) which are supported or
        # can be transpiled to SQLite, so we explicitly override them accordingly
        exp.LikeProperty: exp.Properties.Location.POST_SCHEMA,
        exp.ModuleProperty: exp.Properties.Location.POST_SCHEMA,
        exp.StrictProperty: exp.Properties.Location.POST_SCHEMA,
        exp.TemporaryProperty: exp.Properties.Location.POST_CREATE,
        exp.VirtualProperty: exp.Properties.Location.POST_CREATE,
        exp.WithoutRowidProperty: exp.Properties.Location.POST_SCHEMA,
    }

    LIMIT_FETCH = "LIMIT"

    def root_properties(self, properties: exp.Properties) -> str:
        return self.expressions(properties, indent=False, sep=", ")

    def offset_limit_modifiers(
        self, expression: exp.Expr, fetch: bool, limit: exp.Fetch | exp.Limit | None
    ) -> list[str]:
        if expression.args.get("offset") and (
            not limit or (isinstance(limit, exp.Limit) and limit.is_limit_all)
        ):
            limit = exp.Limit(expression=exp.Literal.number(-1))
        return super().offset_limit_modifiers(expression, fetch, limit)

    def subquery_sql(self, expression: exp.Subquery, sep: str = " AS ") -> str:
        if any(expression.args.get(key) for key in ("order", "limit", "offset")):
            query = expression.this
            keys = ("order", "limit", "offset", "with_")
            # Merge grouping modifiers unless doing so would overwrite an inner clause.
            if any(expression.args.get(key) and query.args.get(key) for key in keys):
                query = exp.select("*").from_(query.subquery(copy=False), copy=False)
            for key in keys:
                if value := expression.args.get(key):
                    query.set(key, value.pop())
            return self.sql(query)

        return super().subquery_sql(expression, sep=sep)

    def autoincrementcolumnconstraint_sql(
        self, expression: exp.AutoIncrementColumnConstraint
    ) -> str:
        column = expression.find_ancestor(exp.ColumnDef)
        if column and column.find(exp.PrimaryKeyColumnConstraint):
            return super().autoincrementcolumnconstraint_sql(expression)

        self.unsupported("SQLite AUTOINCREMENT requires an INTEGER PRIMARY KEY")
        return ""

    def insert_sql(self, expression: exp.Insert) -> str:
        if expression.args.get("ignore"):
            expression.set("ignore", False)
            expression.set("alternative", "IGNORE")

        return super().insert_sql(expression)

    def rand_sql(self, expression: exp.Rand) -> str:
        random = self.func("RANDOM", expression.this)
        if any(expression.args.values()):
            return random

        # Keep 53 bits so even the largest draw is exactly representable and strictly below 1 after division.
        return f"(CAST({random} & 9007199254740991 AS REAL) / 9007199254740992)"

    def bitwiseandagg_sql(self, expression: exp.BitwiseAndAgg) -> str:
        self.unsupported("BITWISE_AND aggregation is not supported in SQLite")
        return self.function_fallback_sql(expression)

    def bitwiseoragg_sql(self, expression: exp.BitwiseOrAgg) -> str:
        self.unsupported("BITWISE_OR aggregation is not supported in SQLite")
        return self.function_fallback_sql(expression)

    def bitwisexoragg_sql(self, expression: exp.BitwiseXorAgg) -> str:
        self.unsupported("BITWISE_XOR aggregation is not supported in SQLite")
        return self.function_fallback_sql(expression)

    def jsonextract_sql(self, expression: exp.JSONExtract) -> str:
        if expression.expressions:
            return self.function_fallback_sql(expression)
        return arrow_json_extract_sql(self, expression)

    def jsonextractscalar_sql(self, expression: exp.JSONExtractScalar) -> str:
        if expression.args.get("json_subtype"):
            # json_extract() keeps the JSON subtype on object/array results;
            # ->> strips it, observable when the result feeds another JSON function
            return self.func("JSON_EXTRACT", expression.this, expression.expression)
        return arrow_json_extract_sql(self, expression)

    def attimezone_sql(self, expression: exp.AtTimeZone) -> str:
        if expression == SQLITE_NOW:
            # SQLite date functions accept 'now' directly and retain its milliseconds.
            if expression.arg_key == "this" and isinstance(
                expression.parent, (exp.Date, exp.TimeToStr)
            ):
                return "'now'"
            return self.func("STRFTIME", "'%Y-%m-%d %H:%M:%f'", "'now'")
        return super().attimezone_sql(expression)

    def _month_shift_sql(
        self,
        base: exp.Expr,
        month_count: exp.Expr | str,
        preserve_end_of_month: bool = False,
        preserve_time: bool = True,
    ) -> str:
        """Add calendar months without SQLite's default overflowing-day behavior.

        Oracle ADD_MONTHS also preserves end-of-month across month lengths.
        Spark/MySQL/T-SQL month addition clamps only if the target month lacks
        the original day. Uses pre-3.46 SQLite built-ins (no 'floor' modifier).
        """
        value = self.sql(base)
        months = month_count if isinstance(month_count, str) else self.sql(month_count)
        first = f"DATE({value}, 'start of month', ({months}) || ' months')"
        target_last = f"DATE({first}, '+1 month', '-1 day')"
        target_day_count = f"CAST(STRFTIME('%d', {target_last}) AS INTEGER)"
        source_day = f"CAST(STRFTIME('%d', {value}) AS INTEGER)"
        day = f"MIN({source_day}, {target_day_count})"
        if preserve_end_of_month:
            original_last = f"DATE({value}, 'start of month', '+1 month', '-1 day')"
            day = (
                f"(CASE WHEN DATE({value}) = {original_last} "
                f"THEN {target_day_count} ELSE {day} END)"
            )

        shifted = f"DATE({first}, ({day} - 1) || ' days')"
        if not preserve_time:
            return shifted

        # Preserve textual time-of-day for datetime inputs; don't accidentally
        # turn '2024-01-31 12:34:56' into a bare date at the month boundary.
        time_suffix = (
            f"CASE WHEN INSTR({value}, ' ') > 0 "
            f"THEN SUBSTR({value}, INSTR({value}, ' ')) ELSE '' END"
        )
        return f"({shifted} || {time_suffix})"

    def addmonths_sql(self, expression: exp.AddMonths) -> str:
        return self._month_shift_sql(
            expression.this,
            expression.expression,
            preserve_end_of_month=bool(expression.args.get("preserve_end_of_month")),
            preserve_time=bool(expression.args.get("preserve_end_of_month")),
        )

    def dateadd_sql(self, expression: exp.DateAdd) -> str:
        return self._date_delta_sql(expression, expression.this, expression.expression)

    def _date_delta_sql(self, expression: exp.Expr, base: exp.Expr, modifier: exp.Expr) -> str:
        unit = expression.args.get("unit")
        # An INTERVAL amount carries its own unit, e.g. DATE_ADD(d, INTERVAL 1 DAY);
        # unwrap it so the unit is not left inside the quoted modifier string.
        if isinstance(modifier, exp.Interval):
            unit = unit or modifier.unit
            modifier = modifier.this

        if isinstance(expression, (exp.Sub, exp.DateSub)):
            modifier = self._negate_date_modifier(modifier)

        # Plural units (e.g. Postgres INTERVAL '2 hours') are valid SQLite modifiers
        unit_name = unit.name.upper().removesuffix("S") if unit else ""
        if unit_name == "WEEK":
            modifier = modifier * 7
            unit = exp.var("DAY")

        if isinstance(expression, (exp.DateAdd, exp.DateSub, exp.Add, exp.Sub)) and unit_name in ("MONTH", "YEAR"):
            month_count = (
                modifier.name if isinstance(modifier, exp.Literal) and modifier.is_string
                else self.sql(modifier)
            )
            if unit_name == "YEAR":
                month_count = f"({month_count} * 12)"
            return self._month_shift_sql(base, month_count)

        # DATE + INTERVAL can return DATE or TIMESTAMP depending on the source dialect.
        if expression.is_type(exp.DType.DATE, exp.DType.DATE32):
            func = "DATE"
        elif expression.is_type(exp.DType.TIME, exp.DType.TIMETZ):
            func = "TIME"
        elif (
            expression.is_type(*exp.DataType.TEMPORAL_TYPES)
            or unit_name in ("HOUR", "MINUTE", "SECOND")
            or isinstance(base, exp.CurrentTimestamp)
            or base.is_type(exp.DType.DATETIME, exp.DType.TIMESTAMP, exp.DType.TIMESTAMPNTZ)
        ):
            func = "DATETIME"
        else:
            func = "DATE"

        modifier = modifier.unnest()
        if (
            unit
            and not isinstance(modifier, exp.Literal)
            and not (isinstance(modifier, exp.Neg) and modifier.this.is_number)
        ):
            return self.func(
                func,
                base,
                exp.DPipe(
                    this=exp.paren(modifier),
                    expression=exp.Literal.string(f" {unit.name}"),
                ),
            )
        value = modifier.name if modifier.is_string else self.sql(modifier)
        return self.func(func, base, exp.Literal.string(f"{value} {unit.name}" if unit else value))

    # SQLite has no INTERVAL type, so `x +/- INTERVAL n unit` uses date modifiers.
    # Intervals without a unit (e.g. Postgres INTERVAL '1 day 2 hours') are left as is.
    def add_sql(self, expression: exp.Add) -> str:
        this, other = expression.this, expression.expression
        if isinstance(this, exp.Interval) and not isinstance(other, exp.Interval):
            this, other = other, this
        if isinstance(other, exp.Interval) and other.unit:
            return self._date_delta_sql(expression, this, other)
        return super().add_sql(expression)

    def sub_sql(self, expression: exp.Sub) -> str:
        interval = expression.expression
        if isinstance(interval, exp.Interval) and interval.unit:
            return self._date_delta_sql(expression, expression.this, interval)
        return super().sub_sql(expression)

    def datesub_sql(self, expression: exp.DateSub) -> str:
        return self._date_delta_sql(expression, expression.this, expression.expression)

    def _negate_date_modifier(self, amount: exp.Expr) -> exp.Expr:
        amount = amount.unnest()
        if isinstance(amount, exp.Neg):
            return amount.this
        if isinstance(amount, exp.Literal):
            text = amount.name.removeprefix("+")
            return exp.Literal.string(text[1:] if text.startswith("-") else f"-{text}")
        return exp.Neg(
            this=amount
            if isinstance(amount, (exp.Column, exp.Func))
            else exp.paren(amount, copy=False)
        )

    def cast_sql(self, expression: exp.Cast, safe_prefix: str | None = None) -> str:
        if expression.is_type("date"):
            return self.func("DATE", expression.this)
        if expression.is_type("datetime", "timestamp", "timestampntz"):
            return self.func("DATETIME", expression.this)
        if expression.is_type("time"):
            return self.func("TIME", expression.this)
        if expression.is_type("json", "jsonb"):
            return self.func("JSON", expression.this)

        return super().cast_sql(expression)

    # https://www.sqlite.org/gencol.html
    # Inline unsupported check: mypyc cannot compile @unsupported_args on an
    # override of an undecorated base-class method.
    def computedcolumnconstraint_sql(self, expression: exp.ComputedColumnConstraint) -> str:
        if expression.args.get("data_type"):
            self.unsupported("SQLite generated columns do not support a data type")

        this = expression.this
        this_sql = self.sql(this) if isinstance(this, exp.Paren) else f"({self.sql(this)})"
        storage = " STORED" if expression.args.get("persisted") else ""
        not_null = " NOT NULL" if expression.args.get("not_null") else ""
        return f"AS {this_sql}{storage}{not_null}"

    # Note: SQLite's TRUNC always returns REAL (e.g., trunc(10.99) -> 10.0), not INTEGER.
    # This creates a transpilation gap affecting division semantics, similar to Presto.
    # Unlike Presto where this only affects decimals=0, SQLite has no decimals parameter
    # so every use of TRUNC is affected. Modeling precisely would require exp.FloatTrunc.
    @unsupported_args("decimals")
    def trunc_sql(self, expression: exp.Trunc) -> str:
        return self.func("TRUNC", expression.this)

    def generateseries_sql(self, expression: exp.GenerateSeries) -> str:
        parent = expression.parent
        alias = parent and parent.args.get("alias")

        if isinstance(alias, exp.TableAlias) and alias.columns:
            column_alias = alias.columns[0]
            alias.set("columns", None)
            sql = self.sql(
                exp.select(exp.alias_("value", column_alias)).from_(expression).subquery()
            )
        else:
            sql = generate_series_sql("GENERATE_SERIES")(self, expression)

        return sql

    def left_sql(self, expression: exp.Left) -> str:
        value, count = self.sql(expression, "this"), self.sql(expression, "expression")
        if expression.args.get("negative_length_returns_empty"):
            negative = "''"
        else:
            negative = f"SUBSTR({value}, 1, MAX(LENGTH({value}) + {count}, 0))"
        return (
            f"(CASE WHEN {value} IS NULL OR {count} IS NULL THEN NULL "
            f"WHEN {count} >= 0 THEN SUBSTR({value}, 1, {count}) "
            f"ELSE {negative} END)"
        )

    def right_sql(self, expression: exp.Right) -> str:
        value, count = self.sql(expression, "this"), self.sql(expression, "expression")
        if expression.args.get("negative_length_returns_empty"):
            negative = "''"
        else:
            negative = f"SUBSTR({value}, 1 - {count})"
        return (
            f"(CASE WHEN {value} IS NULL OR {count} IS NULL THEN NULL "
            f"WHEN {count} = 0 THEN '' "
            f"WHEN {count} > 0 THEN SUBSTR({value}, -{count}) "
            f"ELSE {negative} END)"
        )

    def startswith_sql(self, expression: exp.StartsWith) -> str:
        value, prefix = self.sql(expression, "this"), self.sql(expression, "expression")
        return f"(SUBSTR({value}, 1, LENGTH({prefix})) = {prefix})"

    def endswith_sql(self, expression: exp.EndsWith) -> str:
        value, suffix = self.sql(expression, "this"), self.sql(expression, "expression")
        return (
            f"(CASE WHEN {value} IS NULL OR {suffix} IS NULL THEN NULL "
            f"WHEN LENGTH({suffix}) = 0 THEN 1 "
            f"ELSE SUBSTR({value}, -LENGTH({suffix})) = {suffix} END)"
        )

    def lastday_sql(self, expression: exp.LastDay) -> str:
        unit = expression.args.get("unit")
        if unit and unit.name.upper() != "MONTH":
            self.unsupported("SQLite LAST_DAY supports only calendar months")
            return self.func("LAST_DAY", expression.this)
        return f"DATE({self.sql(expression, 'this')}, 'start of month', '+1 month', '-1 day')"

    def concatws_sql(self, expression: exp.ConcatWs) -> str:
        # SQLite 3.44..3.50.1 CONCAT_WS skipped empty strings, whereas DuckDB
        # and the SQL standard's skip-NULL behavior retain empty fields.
        # Construct the separator only between non-NULL *positions*.
        args = expression.expressions
        if len(args) < 2:
            self.unsupported("CONCAT_WS needs a separator and at least one value")
            return super().concatws_sql(expression)
        sep = self.sql(args[0])
        values = [self.sql(value) for value in args[1:]]
        pieces = []
        prior = []
        for value in values:
            separator = (
                "''" if not prior
                else f"(CASE WHEN ({' OR '.join(f'{p} IS NOT NULL' for p in prior)}) "
                f"THEN {sep} ELSE '' END)"
            )
            pieces.append(
                f"(CASE WHEN {value} IS NULL THEN '' ELSE {separator} || {value} END)"
            )
            prior.append(value)
        condition = f"{sep} IS NULL"
        if not expression.args.get("coalesce"):
            condition += " OR " + " OR ".join(f"{value} IS NULL" for value in values)
        return f"(CASE WHEN {condition} THEN NULL ELSE ({' || '.join(pieces)}) END)"

    def extract_sql(self, expression: exp.Extract) -> str:
        unit = expression.this.name.upper()
        value = self.sql(expression, "expression")
        mapping = {
            "YEAR": "%Y",
            "MONTH": "%m",
            "DAY": "%d",
            "DAYOFMONTH": "%d",
            "DAYOFYEAR": "%j",
            "DOY": "%j",
            "HOUR": "%H",
            "MINUTE": "%M",
            "SECOND": "%S",
            "DOW": "%w",
            "DAYOFWEEK": "%w",
        }
        if unit in mapping:
            return f"CAST(STRFTIME('{mapping[unit]}', {value}) AS INTEGER)"
        if unit == "ISODOW":
            weekday = f"CAST(STRFTIME('%w', {value}) AS INTEGER)"
            return f"((({weekday} + 6) % 7) + 1)"
        if unit in ("WEEK", "ISOYEAR"):
            thursday = f"DATE({value}, '-3 days', 'weekday 4')"
            if unit == "ISOYEAR":
                return f"CAST(STRFTIME('%Y', {thursday}) AS INTEGER)"
            day = f"CAST(STRFTIME('%j', {thursday}) AS INTEGER)"
            return f"(CAST(({day} - 1) / 7 AS INTEGER) + 1)"
        if unit == "QUARTER":
            month = f"CAST(STRFTIME('%m', {value}) AS INTEGER)"
            return f"CAST(({month} + 2) / 3 AS INTEGER)"
        self.unsupported(f"SQLite cannot safely extract '{unit}'")
        return super().extract_sql(expression)

    def datetrunc_sql(self, expression: exp.DateTrunc) -> str:
        unit = expression.unit.name.upper()
        value = self.sql(expression, "this")
        if unit == "YEAR":
            return f"DATE({value}, 'start of year')"
        if unit == "QUARTER":
            month = f"CAST(STRFTIME('%m', {value}) AS INTEGER)"
            offset = f"(CAST(({month} - 1) / 3 AS INTEGER) * 3)"
            return f"DATE({value}, 'start of year', ({offset}) || ' months')"
        if unit == "MONTH":
            return f"DATE({value}, 'start of month')"
        if unit == "WEEK":
            # DuckDB DATE_TRUNC('week') starts Monday. SQLite %w: 0=Sunday.
            weekday = f"CAST(STRFTIME('%w', {value}) AS INTEGER)"
            offset = f"(({weekday} + 6) % 7)"
            return f"DATE({value}, '-' || {offset} || ' days')"
        if unit == "DAY":
            return f"DATE({value})"
        if unit == "HOUR":
            return f"STRFTIME('%Y-%m-%d %H:00:00', {value})"
        if unit == "MINUTE":
            return f"STRFTIME('%Y-%m-%d %H:%M:00', {value})"
        if unit == "SECOND":
            return f"STRFTIME('%Y-%m-%d %H:%M:%S', {value})"
        self.unsupported(f"SQLite cannot safely truncate '{unit}'")
        return super().datetrunc_sql(expression)

    def timestamptrunc_sql(self, expression: exp.TimestampTrunc) -> str:
        # DuckDB's DATE_TRUNC with a column of unknown type parses as a
        # TimestampTrunc, not DateTrunc. SQLite has neither built-in function;
        # reuse the calendar truncation implementation and preserve the
        # timestamp-shaped output instead of emitting DATE_TRUNC(MONTH, col).
        date_trunc = exp.DateTrunc(
            this=expression.this.copy(),
            unit=expression.unit.copy(),
        )
        return f"DATETIME({self.datetrunc_sql(date_trunc)})"

    def datediff_sql(self, expression: exp.DateDiff) -> str:
        unit = expression.args.get("unit")
        unit = unit.name.upper() if unit else "DAY"
        end = self.sql(expression, "this")
        start = self.sql(expression, "expression")

        # Calendar-based DATE_DIFF/DATEDIFF functions count unit boundaries, not
        # elapsed durations divided by an approximate unit length. For example,
        # 2023-12-31 -> 2024-01-01 crosses one MONTH and one YEAR boundary.
        if unit in ("YEAR", "QUARTER", "MONTH"):
            def calendar_index(value: str) -> str:
                year = f"CAST(STRFTIME('%Y', {value}) AS INTEGER)"
                if unit == "YEAR":
                    return year
                month = f"CAST(STRFTIME('%m', {value}) AS INTEGER)"
                if unit == "MONTH":
                    return f"({year} * 12 + {month})"
                return f"({year} * 4 + CAST(({month} - 1) / 3 AS INTEGER))"

            return f"({calendar_index(end)} - {calendar_index(start)})"

        if unit == "WEEK":
            if expression.args.get("date_part_boundary") is False:
                # DuckDB counts complete seven-day spans, unlike T-SQL's
                # calendar week-boundary semantics. Never silently conflate them.
                elapsed = f"(JULIANDAY(DATE({end})) - JULIANDAY(DATE({start})))"
                return f"CAST({elapsed} / 7 AS INTEGER)"
            self.unsupported("SQLite WEEK DATEDIFF needs source-specific week boundary rules")
            return f"DATEDIFF(WEEK, {start}, {end})"

        if unit == "DAY":
            # Drop time-of-day before computing day boundaries; truncating a
            # 2-second gap across midnight would incorrectly produce zero.
            return f"CAST((JULIANDAY(DATE({end})) - JULIANDAY(DATE({start}))) AS INTEGER)"

        if unit in ("HOUR", "MINUTE", "SECOND"):
            # Truncate both timestamps independently to the requested boundary,
            # then subtract exact integral Unix seconds. This avoids the floating
            # point rounding errors of JULIANDAY(timestamp) * 86400.
            truncation = {
                "HOUR": ("%Y-%m-%d %H:00:00", 3600),
                "MINUTE": ("%Y-%m-%d %H:%M:00", 60),
                "SECOND": ("%Y-%m-%d %H:%M:%S", 1),
            }
            format_string, seconds = truncation[unit]

            def boundary_epoch(value: str) -> str:
                return (
                    f"CAST(STRFTIME('%s', STRFTIME('{format_string}', {value})) "
                    "AS INTEGER)"
                )

            return (
                f"CAST(({boundary_epoch(end)} - {boundary_epoch(start)}) "
                f"/ {seconds} AS INTEGER)"
            )

        # Sub-millisecond and higher precision require separate capabilities;
        # leave the established generator behavior in place until independently
        # verified against engines that support those precisions.
        sql = f"(JULIANDAY({end}) - JULIANDAY({start}))"
        if unit == "MILLISECOND":
            sql = f"{sql} * 86400000.0"
        elif unit == "MICROSECOND":
            sql = f"{sql} * 86400000000.0"
        elif unit == "NANOSECOND":
            sql = f"{sql} * 86400000000000.0"
        else:
            self.unsupported(f"DATEDIFF unsupported for '{unit}'.")
        return f"CAST({sql} AS INTEGER)"

    def groupconcat_sql(self, expression: exp.GroupConcat) -> str:
        node = expression.parent if isinstance(expression.parent, exp.Filter) else expression
        window = node.parent

        if (
            isinstance(expression.this, exp.Order)
            and isinstance(window, exp.Window)
            and window.this is node
        ):
            self.unsupported(
                "SQLite GROUP_CONCAT window functions do not support argument ORDER BY"
            )
            expression.set("this", expression.this.this)

        this = expression.this
        if isinstance(this, exp.Order):
            this = this.this
        if isinstance(this, exp.Distinct) and expression.args.get(
            "separator"
        ) == exp.Literal.string(","):
            # DISTINCT aggregates accept one argument; SQLite already defaults to a comma separator.
            expression.set("separator", None)

        return groupconcat_sql(
            self, expression, func_name="GROUP_CONCAT", sep=None, within_group=False
        )

    def _greatest_least_sql(self, expression: exp.Greatest | exp.Least) -> str:
        if not expression.expressions:
            return self.sql(expression, "this")

        name = "MAX" if isinstance(expression, exp.Greatest) else "MIN"

        if not expression.args.get("ignore_nulls"):
            return rename_func(name)(self, expression)

        # SQLite's multi-argument MAX/MIN return NULL if any argument is NULL.
        # GREATEST(a, b, c) -> MAX(COALESCE(a, b, c), COALESCE(b, c, a), COALESCE(c, a, b)).
        args = [expression.this, *expression.expressions]

        coalesces = []
        for i in range(len(args)):
            rotated = args[i:] + args[:i]
            coalesces.append(exp.Coalesce(this=rotated[0], expressions=rotated[1:]))

        return self.func(name, *coalesces)

    def greatest_sql(self, expression: exp.Greatest) -> str:
        return self._greatest_least_sql(expression)

    def least_sql(self, expression: exp.Least) -> str:
        return self._greatest_least_sql(expression)

    def transaction_sql(self, expression: exp.Transaction) -> str:
        this = expression.this
        this = f" {this}" if this else ""
        return f"BEGIN{this} TRANSACTION"

    def isascii_sql(self, expression: exp.IsAscii) -> str:
        return f"(NOT {self.sql(expression.this)} GLOB CAST(x'2a5b5e012d7f5d2a' AS TEXT))"

    @unsupported_args("this")
    def currentschema_sql(self, expression: exp.CurrentSchema) -> str:
        return "'main'"

    def ignorenulls_sql(self, expression: exp.IgnoreNulls) -> str:
        self.unsupported("SQLite does not support IGNORE NULLS.")
        return self.sql(expression.this)

    def respectnulls_sql(self, expression: exp.RespectNulls) -> str:
        return self.sql(expression.this)

    def windowspec_sql(self, expression: exp.WindowSpec) -> str:
        if (
            expression.text("kind").upper() == "RANGE"
            and expression.text("start").upper() == "CURRENT ROW"
            and expression.args.get("end") is None
        ):
            return "RANGE CURRENT ROW"

        return super().windowspec_sql(expression)
