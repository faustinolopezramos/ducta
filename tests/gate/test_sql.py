import importlib
import sys
from unittest.mock import MagicMock, patch

import pytest

from ducta.gate.exceptions import ConfigurationError
from ducta.gate.sql import SQLGLOT_AVAILABLE, SqlSafetyMixin, SQLSanitizer, UnityCatalogDDL

# ── Tests using regex fallback (sqlglot not installed) ───────────────────────


class TestSQLSanitizerValidQueries:
    def test_simple_select(self):
        result = SQLSanitizer.sanitize_query("SELECT 1 AS col")
        assert result == "SELECT 1 AS col"

    def test_select_from_table(self):
        sql = "SELECT id, name FROM users WHERE age > 18"
        result = SQLSanitizer.sanitize_query(sql)
        assert result == sql

    def test_with_clause(self):
        sql = "WITH cte AS (SELECT 1 AS x) SELECT * FROM cte"
        result = SQLSanitizer.sanitize_query(sql)
        assert result == sql

    def test_query_with_whitespace(self):
        sql = "  SELECT 1 AS col  "
        result = SQLSanitizer.sanitize_query(sql)
        assert result == "  SELECT 1 AS col  "

    def test_complex_select(self):
        sql = "SELECT a.*, b.name FROM schema.table_a a JOIN schema.table_b b ON a.id = b.id"
        result = SQLSanitizer.sanitize_query(sql)
        assert result == sql


class TestSQLSanitizerInvalidQueries:
    def test_drop_table(self):
        with pytest.raises(ConfigurationError, match="dangerous|allowed|Only SELECT"):
            SQLSanitizer.sanitize_query("DROP TABLE users")

    def test_delete_query(self):
        with pytest.raises(ConfigurationError):
            SQLSanitizer.sanitize_query("DELETE FROM users WHERE id = 1")

    def test_insert_query(self):
        with pytest.raises(ConfigurationError):
            SQLSanitizer.sanitize_query("INSERT INTO users VALUES (1, 'test')")

    def test_update_query(self):
        with pytest.raises(ConfigurationError):
            SQLSanitizer.sanitize_query("UPDATE users SET name = 'x' WHERE id = 1")

    def test_create_table(self):
        with pytest.raises(ConfigurationError):
            SQLSanitizer.sanitize_query("CREATE TABLE t (id INT)")

    def test_alter_table(self):
        with pytest.raises(ConfigurationError):
            SQLSanitizer.sanitize_query("ALTER TABLE t ADD COLUMN x INT")

    def test_truncate_table(self):
        with pytest.raises(ConfigurationError):
            SQLSanitizer.sanitize_query("TRUNCATE TABLE t")

    def test_execute_command(self):
        with pytest.raises(ConfigurationError):
            SQLSanitizer.sanitize_query("EXEC sp_who")

    def test_merge_query(self):
        with pytest.raises(ConfigurationError):
            SQLSanitizer.sanitize_query(
                "MERGE INTO t USING s ON t.id=s.id WHEN MATCHED THEN UPDATE SET t.x=s.x"
            )


class TestSQLSanitizerEmptyInput:
    def test_empty_string(self):
        with pytest.raises(ConfigurationError, match="non-empty"):
            SQLSanitizer.sanitize_query("")

    def test_none(self):
        with pytest.raises(ConfigurationError, match="non-empty"):
            SQLSanitizer.sanitize_query(None)

    def test_only_whitespace(self):
        with pytest.raises(ConfigurationError, match="empty after stripping"):
            SQLSanitizer.sanitize_query("   \n  \t  ")

    def test_non_string(self):
        with pytest.raises(ConfigurationError, match="non-empty"):
            SQLSanitizer.sanitize_query(123)


class TestSQLSanitizerComments:
    def test_line_comment(self):
        result = SQLSanitizer.sanitize_query("SELECT 1 AS col -- this is a comment")
        assert "SELECT" in result

    def test_block_comment(self):
        result = SQLSanitizer.sanitize_query("SELECT 1 /* block */ AS col")
        assert "SELECT" in result

    def test_comment_with_dangerous_keyword(self):
        with pytest.raises(ConfigurationError, match="dangerous|forbidden|Comments contain"):
            SQLSanitizer.sanitize_query("SELECT 1 AS col -- DROP TABLE users")


class TestSQLSanitizerSuspiciousPatterns:
    def test_hex_literal(self):
        with pytest.raises(ConfigurationError):
            SQLSanitizer.sanitize_query("SELECT 0x1a2b FROM t")

    def test_char_function(self):
        with pytest.raises(ConfigurationError):
            SQLSanitizer.sanitize_query("SELECT CHAR(65) FROM t")

    def test_ascii_function(self):
        with pytest.raises(ConfigurationError):
            SQLSanitizer.sanitize_query("SELECT ASCII('A') FROM t")

    def test_waitfor_delay(self):
        with pytest.raises(ConfigurationError):
            SQLSanitizer.sanitize_query("SELECT 1; WAITFOR DELAY '00:00:05'")


class TestSQLSanitizerMultipleStatements:
    def test_two_selects_with_semicolon(self):
        with pytest.raises(ConfigurationError, match="Multiple SQL statements"):
            SQLSanitizer.sanitize_query("SELECT 1; SELECT 2")


@pytest.mark.skipif(not SQLGLOT_AVAILABLE, reason="requires the real sqlglot")
class TestSQLSanitizerAgainstRealSqlglot:
    """The lexical layer must keep working while sqlglot is installed.

    These previously passed only because sqlglot was *absent* in CI. With it
    present, `_sanitize_with_sqlglot` replaced the lexical checks outright, so
    installing the package that was supposed to harden the sanitizer silently
    removed four of its five defenses.
    """

    @pytest.mark.parametrize(
        "query",
        [
            "SELECT * FROM t WHERE id = 0x41414141",  # hex literal
            "SELECT char(65) FROM t",  # char() obfuscation
            "SELECT ascii('A') FROM t",  # ascii() obfuscation
            "SELECT * FROM t -- DROP TABLE users",  # payload in a comment
            "SELECT * FROM users; SELECT * FROM secrets",  # stacked statements
            "SELECT * FROM information_schema.tables",  # schema enumeration
            "SELECT * FROM pg_shadow",  # engine catalog probing
        ],
    )
    def test_rejects_injection_shapes_the_ast_does_not_model(self, query):
        with pytest.raises(ConfigurationError):
            SQLSanitizer.sanitize_query(query)

    @pytest.mark.parametrize(
        "query",
        [
            "SELECT 1 AS col",
            "SELECT id, name FROM users WHERE age > 18",
            "WITH cte AS (SELECT 1 AS x) SELECT * FROM cte",
            "SELECT a.*, b.name FROM db.table_a a JOIN db.table_b b ON a.id = b.id",
            "SELECT 1 /* harmless */ AS col",
            "SELECT count(*) AS n FROM events WHERE ts > '2026-01-01'",
        ],
    )
    def test_accepts_ordinary_read_only_queries(self, query):
        assert SQLSanitizer.sanitize_query(query) == query

    # Data-modifying CTEs are the reason the AST scan exists at all: sqlglot
    # parses these with a *Select* at the root, so the "must be SELECT/WITH"
    # check waves them through and only the nested-node scan sees the write.
    @pytest.mark.parametrize(
        ("query", "operation"),
        [
            ("WITH x AS (INSERT INTO t VALUES (1) RETURNING *) SELECT * FROM x", "Insert"),
            ("WITH x AS (DELETE FROM t RETURNING *) SELECT * FROM x", "Delete"),
            ("WITH x AS (UPDATE t SET a=1 RETURNING *) SELECT * FROM x", "Update"),
        ],
    )
    def test_rejects_data_modifying_ctes(self, query, operation):
        with pytest.raises(ConfigurationError, match=f"forbidden operation: {operation}"):
            SQLSanitizer.sanitize_query(query)

    def test_missing_expression_class_does_not_disable_the_scan(self, monkeypatch):
        """A renamed sqlglot class must not take the whole AST scan down with it.

        `Truncate` was removed in sqlglot 30; because the dangerous-operation
        tuple was built eagerly, that single AttributeError skipped every other
        class too and was swallowed as a warning — which is what let the
        data-modifying CTEs above through.
        """
        import sqlglot

        monkeypatch.delattr(sqlglot.expressions, "Drop", raising=False)

        with pytest.raises(ConfigurationError, match="forbidden operation: Insert"):
            SQLSanitizer.sanitize_query(
                "WITH x AS (INSERT INTO t VALUES (1) RETURNING *) SELECT * FROM x"
            )

    def test_fails_closed_when_no_expression_class_resolves(self, monkeypatch):
        for name in SQLSanitizer.DANGEROUS_EXPRESSIONS:
            monkeypatch.delattr(f"sqlglot.expressions.{name}", raising=False)

        with pytest.raises(ConfigurationError, match="AST validation unavailable"):
            SQLSanitizer.sanitize_query("SELECT 1 AS col")

    # `SELECT ... INTO` (SQL Server/Sybase/Postgres) creates and populates a
    # table. sqlglot parses it with a `Select` root — not Create/Insert — and
    # models the target as a separate `Into` node, so neither the AST scan for
    # Drop/Insert/Update/... nor the lexical DANGEROUS_KEYWORDS list (which only
    # has "into outfile"/"into dumpfile") caught it.
    @pytest.mark.parametrize(
        "query",
        [
            "SELECT a, b INTO archive_table FROM live_table",
            "SELECT a, b INTO archive_table FROM live_table WHERE 1=1",
            "WITH src AS (SELECT * FROM t) SELECT * INTO new_table FROM src",
        ],
    )
    def test_rejects_select_into(self, query):
        with pytest.raises(ConfigurationError, match="SELECT ... INTO"):
            SQLSanitizer.sanitize_query(query)

    def test_ordinary_subquery_is_not_mistaken_for_select_into(self):
        # A subquery in a WHERE/IN clause must not false-positive.
        query = "SELECT * FROM t WHERE x IN (SELECT y FROM z)"
        assert SQLSanitizer.sanitize_query(query) == query


class TestSQLSanitizerUtilities:
    def test_is_select_query(self):
        assert SQLSanitizer._is_select_query("SELECT * FROM t") is True

    def test_is_with_query(self):
        assert SQLSanitizer._is_select_query("WITH cte AS (SELECT 1) SELECT * FROM cte") is True

    def test_not_select_query(self):
        assert SQLSanitizer._is_select_query("DROP TABLE t") is False

    def test_remove_comments(self):
        result = SQLSanitizer._remove_comments("SELECT 1 -- comment\nFROM t")
        assert "comment" not in result
        assert "SELECT 1" in result

    def test_remove_block_comment(self):
        result = SQLSanitizer._remove_comments("SELECT 1 /* block */ FROM t")
        assert "block" not in result

    def test_mask_string_literals(self):
        result = SQLSanitizer._mask_string_literals("SELECT 'hello' AS col")
        assert "hello" not in result
        assert "'" in result

    def test_count_semicolons(self):
        count = SQLSanitizer._count_semicolons_outside_strings("SELECT 1; SELECT 2")
        assert count == 1

    def test_count_semicolons_inside_string(self):
        count = SQLSanitizer._count_semicolons_outside_strings("SELECT 'a;b' AS col")
        assert count == 0

    def test_is_quote_escaped(self):
        assert SQLSanitizer._is_quote_escaped("\\'", 1) is True
        assert SQLSanitizer._is_quote_escaped("'hello'", 0) is False


# ── Tests with sqlglot mocked (AST path) ────────────────────────────────────


class MockSelect:
    """Mimics sqlglot.ast.Select for AST-based validation tests."""

    def find(self, *args, **kwargs):
        return None


MockSelect.__name__ = "Select"


class _SqlglotMockSuite:
    """Helper to set up a realistic sqlglot mock."""

    @staticmethod
    def install():
        import sys

        mock = MagicMock()
        mock.parse_one = MagicMock()
        mock.ParseError = type("ParseError", (Exception,), {})

        # Build expressions sub-module with all dangerous types
        expr_mod = MagicMock()
        expr_mod.Drop = type("Drop", (), {})
        expr_mod.Delete = type("Delete", (), {})
        expr_mod.Insert = type("Insert", (), {})
        expr_mod.Update = type("Update", (), {})
        expr_mod.Create = type("Create", (), {})
        expr_mod.Alter = type("Alter", (), {})
        expr_mod.Truncate = type("Truncate", (), {})
        expr_mod.Merge = type("Merge", (), {})
        expr_mod.Command = type("Command", (), {})
        mock.expressions = expr_mod

        sys.modules["sqlglot"] = mock

    @staticmethod
    def uninstall():
        import sys

        if "sqlglot" in sys.modules:
            del sys.modules["sqlglot"]


@pytest.fixture
def _with_sqlglot():
    _SqlglotMockSuite.install()
    importlib.reload(sys.modules["ducta.gate.sql"])
    yield
    _SqlglotMockSuite.uninstall()
    importlib.reload(sys.modules["ducta.gate.sql"])


class TestSQLSanitizerWithSqlglot:
    def test_valid_select(self, _with_sqlglot):
        import sqlglot

        mock_select = MagicMock()
        mock_select.__class__.__name__ = "Select"
        mock_select.find.return_value = None
        sqlglot.parse_one.return_value = mock_select
        from ducta.gate.sql import SQLSanitizer as SS

        result = SS.sanitize_query("SELECT 1 AS col")
        assert result == "SELECT 1 AS col"

    def test_dangerous_operation_detected(self, _with_sqlglot):
        import sqlglot

        mock_drop = MagicMock()
        mock_drop.__class__.__name__ = "Select"
        sqlglot.parse_one.return_value = mock_drop

        # Make find() return a truthy value to simulate finding a Drop node
        mock_drop.find.return_value = True

        from ducta.gate.sql import SQLSanitizer as SS

        with pytest.raises(ConfigurationError, match="forbidden"):
            SS.sanitize_query("DROP TABLE t")

    def test_invalid_syntax(self, _with_sqlglot):
        import sqlglot

        sqlglot.parse_one.side_effect = sqlglot.ParseError("syntax error")
        from ducta.gate.sql import SQLSanitizer as SS

        with pytest.raises(ConfigurationError, match="syntax"):
            SS.sanitize_query("SELECT invalid SQL")

    def test_parse_error_sets_none(self, _with_sqlglot):
        import sqlglot

        sqlglot.parse_one.return_value = None
        from ducta.gate.sql import SQLSanitizer as SS

        with pytest.raises(ConfigurationError, match="Failed to parse"):
            SS.sanitize_query("SELECT 1")


class TestSqlSafetyMixin:
    def test_quote_identifier(self):
        mixin = SqlSafetyMixin()
        assert mixin.quote_identifier("my_col") == "`my_col`"

    def test_quote_identifier_with_backtick(self):
        mixin = SqlSafetyMixin()
        assert mixin.quote_identifier("my`col") == "`my``col`"

    def test_quote_identifier_empty(self):
        mixin = SqlSafetyMixin()
        with pytest.raises(ConfigurationError):
            mixin.quote_identifier("")

    def test_escape_string(self):
        mixin = SqlSafetyMixin()
        assert mixin.escape_string("it's") == "it''s"

    def test_quote_table_name(self):
        mixin = SqlSafetyMixin()
        result = mixin.quote_table_name("cat.sch.tbl")
        assert result == "`cat`.`sch`.`tbl`"

    def test_quote_table_name_invalid_parts(self):
        mixin = SqlSafetyMixin()
        with pytest.raises(ConfigurationError):
            mixin.quote_table_name("cat.sch")


class TestUnityCatalogDDL:
    def test_catalog_exists_query(self):
        sql = UnityCatalogDDL.catalog_exists_query("my_cat")
        assert sql == (
            "SELECT 1 FROM system.information_schema.catalogs WHERE catalog_name = 'my_cat' LIMIT 1"
        )

    def test_catalog_exists_query_escapes_quote(self):
        sql = UnityCatalogDDL.catalog_exists_query("o'brien")
        assert "o''brien" in sql

    def test_schema_exists_query(self):
        sql = UnityCatalogDDL.schema_exists_query("cat", "sch")
        assert sql == (
            "SELECT 1 FROM system.information_schema.schemata "
            "WHERE catalog_name = 'cat' AND schema_name = 'sch' LIMIT 1"
        )

    def test_create_catalog(self):
        assert UnityCatalogDDL.create_catalog("my_cat") == "CREATE CATALOG `my_cat`"

    def test_create_catalog_escapes_backtick(self):
        sql = UnityCatalogDDL.create_catalog("my`cat")
        assert sql == "CREATE CATALOG `my``cat`"

    def test_create_schema_no_location(self):
        sql = UnityCatalogDDL.create_schema("cat", "sch")
        assert sql == "CREATE SCHEMA IF NOT EXISTS `cat`.`sch`"

    def test_create_schema_with_location_external(self):
        sql = UnityCatalogDDL.create_schema("cat", "sch", location="/base/path", managed=False)
        assert sql == "CREATE SCHEMA IF NOT EXISTS `cat`.`sch` LOCATION '/base/path'"

    def test_create_schema_with_location_managed(self):
        sql = UnityCatalogDDL.create_schema("cat", "sch", location="/base/path", managed=True)
        assert sql == "CREATE SCHEMA IF NOT EXISTS `cat`.`sch` MANAGED LOCATION '/base/path'"

    def test_create_schema_escapes_location_quote(self):
        sql = UnityCatalogDDL.create_schema("cat", "sch", location="it's/path")
        assert "it''s/path" in sql

    def test_create_external_table(self):
        sql = UnityCatalogDDL.create_external_table("cat.sch.tbl", "/data/path")
        assert (
            sql == "CREATE TABLE IF NOT EXISTS `cat`.`sch`.`tbl` USING DELTA LOCATION '/data/path'"
        )

    def test_comment_on_table(self):
        sql = UnityCatalogDDL.comment_on_table("`cat`.`sch`.`tbl`", "Some comment")
        assert sql == "COMMENT ON TABLE `cat`.`sch`.`tbl` IS 'Some comment'"

    def test_comment_on_table_escapes_quote(self):
        sql = UnityCatalogDDL.comment_on_table("`cat`.`sch`.`tbl`", "it's a comment")
        assert "it''s a comment" in sql

    def test_optimize_where(self):
        sql = UnityCatalogDDL.optimize_where(
            "`cat`.`sch`.`tbl`", "event_date", "2024-01-01", "2024-01-31"
        )
        assert sql == (
            "OPTIMIZE `cat`.`sch`.`tbl` WHERE `event_date` BETWEEN '2024-01-01' AND '2024-01-31'"
        )

    def test_vacuum(self):
        sql = UnityCatalogDDL.vacuum("`cat`.`sch`.`tbl`", 168)
        assert sql == "VACUUM `cat`.`sch`.`tbl` RETAIN 168 HOURS"

    def test_replace_where_clause(self):
        sql = UnityCatalogDDL.replace_where_clause("event_date", "2024-01-01", "2024-01-31")
        assert sql == "`event_date` BETWEEN '2024-01-01' AND '2024-01-31'"
