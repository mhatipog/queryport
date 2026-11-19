"""Documented Fabric surface-area safety tests for QueryPort."""
import unittest

from sqlglot.queryport import (
    StaticConversion,
    UnsupportedFabricFeature,
    fabric_violations,
    strict_transpile,
)


class TestFabricCapabilities(unittest.TestCase):
    def test_fabric_warehouse_documented_forbidden_constructs(self):
        examples = {
            "CREATE USER analyst WITHOUT LOGIN": "FABRIC_CREATE_USER",
            "CREATE MATERIALIZED VIEW dbo.v AS SELECT id FROM dbo.t": "FABRIC_MATERIALIZED_VIEW",
            "CREATE TRIGGER trg ON dbo.t AFTER INSERT AS SELECT 1": "FABRIC_TRIGGERS",
            "CREATE SYNONYM dbo.a FOR dbo.b": "FABRIC_SYNONYMS",
            "SELECT * FROM dbo.t FOR XML AUTO": "FABRIC_FOR_XML",
            "SET ROWCOUNT 10": "FABRIC_SET_ROWCOUNT",
            "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE": "FABRIC_SET_ISOLATION",
            "WITH RECURSIVE t AS (SELECT 1 UNION ALL SELECT 2) SELECT * FROM t": "FABRIC_RECURSIVE_CTE",
        }
        for sql, code in examples.items():
            with self.subTest(sql=sql):
                self.assertIn(code, fabric_violations(sql, "fabric-warehouse"))

    def test_lakehouse_readonly(self):
        cases = {
            "INSERT INTO t VALUES (1)": "LAKEHOUSE_READONLY_INSERT",
            "UPDATE dbo.t SET v = 1": "LAKEHOUSE_READONLY_UPDATE",
            "DELETE FROM dbo.t": "LAKEHOUSE_READONLY_DELETE",
            "MERGE INTO t USING s ON t.id = s.id WHEN MATCHED THEN UPDATE SET t.v = s.v":
                "LAKEHOUSE_READONLY_MERGE",
            "TRUNCATE TABLE dbo.t": "LAKEHOUSE_READONLY_TRUNCATE",
            "CREATE TABLE dbo.t (id int)": "LAKEHOUSE_READONLY_CREATE_TABLE",
            "ALTER TABLE dbo.t ADD x int": "LAKEHOUSE_READONLY_ALTER_TABLE",
            "DROP TABLE dbo.t": "LAKEHOUSE_READONLY_DROP_TABLE",
        }
        for sql, code in cases.items():
            with self.subTest(sql=sql):
                self.assertIn(code, fabric_violations(sql, "fabric-lakehouse-sql-endpoint"))
                self.assertNotIn(code, fabric_violations(sql, "fabric-warehouse"))

    def test_quoted_sql_text_is_not_code(self):
        sqls = [
            "SELECT 'CREATE USER' AS documentation",
            "SELECT 'FOR XML' AS documentation",
            "SELECT [CREATE USER] AS expression FROM dbo.t",
            "SELECT 'INSERT INTO t' AS metadata",
            "SELECT 1 -- FOR XML",
            "SELECT N'CREATE MATERIALIZED VIEW' AS d",
            "SELECT 'SET TRANSACTION ISOLATION LEVEL' AS d",
        ]
        for sql in sqls:
            with self.subTest(sql=sql):
                self.assertEqual(fabric_violations(sql, "fabric-lakehouse-sql-endpoint"), ())

    def test_warehouse_merge_allowed_by_static_gate(self):
        sql = (
            "MERGE INTO dbo.dest AS d USING dbo.src AS s "
            "ON d.id = s.id WHEN MATCHED THEN UPDATE SET d.v = s.v"
        )
        self.assertEqual(fabric_violations(sql, "fabric-warehouse"), ())
        self.assertIn(
            "LAKEHOUSE_READONLY_MERGE",
            fabric_violations(sql, "fabric-lakehouse-sql-endpoint"),
        )

    def test_strict_api_reports_only_syntactic_gates(self):
        result = strict_transpile(
            "SELECT TOP (10) order_id FROM dbo.orders ORDER BY order_id",
            read="tsql", profile="fabric-warehouse",
        )
        self.assertIsInstance(result, StaticConversion)
        self.assertEqual(len(result.sql), 1)
        self.assertFalse(result.engine_executed)
        self.assertFalse(result.semantic_equivalence_proven)

    def test_strict_api_catches_warehouse_xml_and_lakehouse_mutations(self):
        with self.assertRaises(UnsupportedFabricFeature):
            strict_transpile("SELECT * FROM dbo.t FOR XML AUTO",
                             read="tsql", profile="fabric-warehouse")
        with self.assertRaises(UnsupportedFabricFeature):
            strict_transpile("INSERT INTO dbo.t VALUES (1)",
                             read="tsql", profile="fabric-lakehouse-sql-endpoint")
        with self.assertRaises(UnsupportedFabricFeature):
            strict_transpile("CREATE USER user_a WITHOUT LOGIN",
                             read="tsql", profile="fabric-warehouse")

    def test_strict_api_source_can_be_oracle(self):
        result = strict_transpile("SELECT NVL(amount, 0) AS safe FROM orders",
                                  read="oracle", profile="fabric-warehouse")
        self.assertEqual(len(result.sql), 1)
        self.assertFalse(result.semantic_equivalence_proven)

    def test_oracle_empty_string_is_a_semantic_blocker(self):
        for sql in (
            "SELECT '' AS payload FROM dual",
            "SELECT CASE WHEN name = '' THEN 1 ELSE 0 END FROM t",
            "SELECT COALESCE('', 'fallback') AS x FROM dual",
        ):
            with self.subTest(sql=sql), self.assertRaisesRegex(
                UnsupportedFabricFeature, "ORACLE_EMPTY_STRING_NULL_SEMANTICS"
            ):
                strict_transpile(sql, read="oracle", profile="fabric-warehouse")

    def test_invalid_profile_rejected(self):
        with self.assertRaises(ValueError):
            fabric_violations("SELECT 1", "sqlserver")
        with self.assertRaises(ValueError):
            strict_transpile("SELECT 1", read="tsql", profile="sqlserver")


if __name__ == "__main__":
    unittest.main()
