"""Execute DuckDB and SQLite ties-even INT32 casts on thousands of real values."""
from __future__ import annotations

import math
import random
import sqlite3
import unittest

import duckdb
from sqlglot import parse_one
from sqlglot.queryport_duckdb_sqlite import UnsafeDuckDBPort, port_duckdb_to_sqlite


class TestDuckDBBankersIntegerCast(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.duck = duckdb.connect(":memory:")
        cls.sqlite = sqlite3.connect(":memory:")
        cls.duck.execute("CREATE TABLE t (id INTEGER, x DOUBLE, n INTEGER)")
        cls.sqlite.execute("CREATE TABLE t (id INTEGER, x REAL, n INTEGER)")
        rng = random.Random(20261120)
        special = [
            None, 0.0, -0.0, -2147483648.0, 2147483647.0,
            -999999.5, 999999.5, -3.5, -2.5, -1.5, -0.5,
            0.5, 1.5, 2.5, 3.5, 4.5, -4.5,
            2.499999999, 2.500000001, -2.499999999, -2.500000001,
            0.499999999, 0.500000001, -0.499999999, -0.500000001,
        ]
        floats = special + [
            rng.uniform(-2000000, 2000000) for _ in range(3000)
        ] + [float(v) + 0.5 for v in range(-150, 151)]
        cls.rows = [(i, val, i % 31 - 15) for i, val in enumerate(floats)]
        cls.duck.executemany("INSERT INTO t VALUES (?, ?, ?)", cls.rows)
        cls.sqlite.executemany("INSERT INTO t VALUES (?, ?, ?)", cls.rows)
        cls.schema = {"t": {"id": "INTEGER", "x": "DOUBLE", "n": "INTEGER"}}
        cls.bounds = {"x": (-2147483648, 2147483647)}

    @classmethod
    def tearDownClass(cls):
        cls.duck.close()
        cls.sqlite.close()

    def test_3326_values_with_half_ties_and_int32_endpoints(self):
        sql = "SELECT CAST(x AS INTEGER) FROM t ORDER BY id"
        candidate = port_duckdb_to_sqlite(
            sql, schema=self.schema, float_bounds=self.bounds
        )
        self.assertEqual(candidate.rewritten_float_to_int, 1)
        self.assertEqual(candidate.unresolved, ())
        self.assertFalse(candidate.semantic_equivalence_proven)
        self.assertIn("ROUND", candidate.sql[0])
        self.assertIn("CASE", candidate.sql[0])

        expected = [row[0] for row in self.duck.execute(sql).fetchall()]
        actual = [row[0] for row in self.sqlite.execute(candidate.sql[0]).fetchall()]
        self.assertEqual(expected, actual, candidate.sql[0])
        independent = [None if val is None else round(val) for _, val, _ in self.rows]
        self.assertEqual(expected, independent)
        self.assertGreater(len(expected), 3200)
        self.assertEqual(actual[0], None)
        self.assertEqual(actual[3], -2147483648)
        self.assertEqual(actual[4], 2147483647)

    def test_int_source_unchanged_and_native_sqlite_generator_untouched(self):
        q = "SELECT CAST(n AS INTEGER) FROM t ORDER BY id"
        result = port_duckdb_to_sqlite(q, schema=self.schema)
        self.assertEqual(result.rewritten_float_to_int, 0)
        self.assertEqual(result.unresolved, ())
        self.assertEqual(
            [row[0] for row in self.sqlite.execute(result.sql[0])],
            [row[0] for row in self.duck.execute(q).fetchall()],
        )
        original = parse_one("CAST(x AS INTEGER)", read="duckdb").sql("sqlite")
        self.assertNotIn("ROUND", original)

    def test_missing_or_unsafe_range_rejected(self):
        source = "SELECT CAST(x AS INTEGER) FROM t"
        for bounds in (
            None, {},
            {"x": (-math.inf, 20)},
            {"x": (-3, math.inf)},
            {"x": (20, -20)},
            {"x": (-2147483649, 100)},
            {"x": (-100, 2147483648)},
        ):
            with self.subTest(bounds=bounds):
                with self.assertRaises(UnsafeDuckDBPort):
                    port_duckdb_to_sqlite(
                        source, schema=self.schema, float_bounds=bounds
                    )

    def test_ambiguous_or_different_source_types_fail_closed(self):
        source = "SELECT CAST(x AS INTEGER) FROM t"
        for schema in (
            None,
            {"t": {"x": "FLOAT"}},
            {"t": {"x": "DECIMAL(12,2)"}},
            {"t": {"x": "VARCHAR"}},
        ):
            with self.subTest(schema=schema):
                with self.assertRaises(UnsafeDuckDBPort):
                    port_duckdb_to_sqlite(
                        source, schema=schema, float_bounds=self.bounds
                    )

    def test_diagnostic_mode_tracks_unknown_conversion(self):
        result = port_duckdb_to_sqlite(
            "SELECT CAST(x AS INTEGER) FROM t",
            schema=self.schema, strict=False,
        )
        self.assertEqual(result.rewritten_float_to_int, 0)
        self.assertTrue(any("CAST" in item for item in result.unresolved))
        self.assertFalse(result.semantic_equivalence_proven)


if __name__ == "__main__":
    unittest.main()
