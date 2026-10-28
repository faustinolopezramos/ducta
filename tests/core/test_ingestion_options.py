"""A node's ``options`` cannot replace the checked statement or the connection.

The ingestion node sanitizes ``query`` / ``table`` and takes the connection from the source,
then merged the node's own ``options`` over the result — so ``options: {query: ...}``,
``{dbtable: ...}``, ``{url: ...}`` or ``{sessionInitStatement: ...}`` reached Spark in place of
(or beside) what had been checked.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ducta.core.execution.ingestion import IngestionExecutor
from ducta.gate.gateway.connector import RESERVED_READ_OPTIONS, reserved_read_options
from ducta.setting.project.loader import ProjectConfigError, validate_project


@pytest.fixture
def harness():
    spark = MagicMock()
    reader = spark.read.format.return_value
    reader.options.return_value = reader
    connection = SimpleNamespace(
        jdbc_url="jdbc:postgresql://h:5432/d",
        jdbc_properties={"user": "u", "password": "p", "driver": "org.postgresql.Driver"},
    )
    context = SimpleNamespace(
        spark=spark,
        config_paths={},
        global_config={},
        _ingestion_managers={"config/sources.yaml": SimpleNamespace(get=lambda name: connection)},
    )
    quality = MagicMock()
    executor = IngestionExecutor(
        context, MagicMock(), quality, settings=SimpleNamespace(ingestion={})
    )

    def run(node):
        reader.options.reset_mock()
        executor.execute("n", node, "2024-01-01", "2024-01-02", {})
        return reader.options.call_args.kwargs

    return run


class TestExecutorRefusesReservedOptions:
    @pytest.mark.parametrize(
        "option",
        [
            {"query": "DROP TABLE users"},
            {"dbtable": "(DELETE FROM users) q"},
            {"sessionInitStatement": "DROP TABLE users"},
            {"prepareQuery": "WITH x AS (SELECT 1)"},
            {"url": "jdbc:mysql://evil:3306/x?autoDeserialize=true"},
            {"driver": "com.evil.Driver"},
        ],
    )
    def test_each_reserved_option_is_refused(self, harness, option):
        with pytest.raises(ValueError, match="cannot set"):
            harness({"source": "s", "table": "t", "options": option})

    @pytest.mark.parametrize("name", ["URL", "Query", "SESSIONINITSTATEMENT", "dbTable"])
    def test_spark_reads_option_names_without_regard_to_case_and_so_do_we(self, harness, name):
        with pytest.raises(ValueError, match="cannot set"):
            harness({"source": "s", "table": "t", "options": {name: "x"}})

    def test_the_message_names_the_option(self, harness):
        with pytest.raises(ValueError, match="sessionInitStatement"):
            harness({"source": "s", "table": "t", "options": {"sessionInitStatement": "x"}})

    def test_ordinary_options_still_reach_spark(self, harness):
        passed = harness(
            {"source": "s", "table": "t", "options": {"fetchsize": 500, "numPartitions": 4}}
        )
        assert passed["fetchsize"] == "500" and passed["numPartitions"] == "4"
        assert passed["dbtable"] == "t"
        assert passed["url"] == "jdbc:postgresql://h:5432/d"
        assert passed["password"] == "p"

    def test_user_and_password_can_still_be_set_per_node(self, harness):
        passed = harness(
            {"source": "s", "table": "t", "options": {"user": "etl", "PASSWORD": "pw"}}
        )
        assert passed["user"] == "etl"
        assert passed["PASSWORD"] == "pw"
        assert "password" not in passed  # the same name in another case is replaced, not doubled

    def test_the_connection_and_statement_are_what_was_checked(self, harness):
        passed = harness({"source": "s", "query": "SELECT 1", "options": {"fetchsize": 1}})
        assert passed["query"] == "SELECT 1"
        assert passed["user"] == "u"


class TestReservedOptionsHelper:
    def test_finds_names_ignoring_case_and_returns_them_as_written(self):
        assert reserved_read_options({"URL": 1, "fetchsize": 2, "dbTable": 3}) == ["URL", "dbTable"]

    def test_anything_but_a_mapping_has_none(self):
        assert reserved_read_options(None) == []
        assert reserved_read_options(["url"]) == []

    def test_the_set_is_lowercase_so_the_comparison_is_case_insensitive(self):
        assert all(name == name.lower() for name in RESERVED_READ_OPTIONS)

    def test_user_and_password_are_not_reserved(self):
        assert reserved_read_options({"user": "a", "password": "b"}) == []


class TestProjectValidationRefusesThemToo:
    def _project(self, tmp_path, options):
        (tmp_path / "ducta.yaml").write_text(
            "version: 2\nproject: demo\npaths: {input: d, output: d}\n"
        )
        (tmp_path / "catalog.yaml").write_text("raw: {format: parquet, path: d/raw}\n")
        (tmp_path / "pipelines").mkdir()
        (tmp_path / "pipelines" / "p.yaml").write_text(
            "nodes:\n  pull:\n    kind: ingest\n    ingest:\n      source: crm\n      table: customers\n"
            f"      options: {options}\n    outputs: [raw]\n"
        )
        return tmp_path

    def test_a_reserved_option_is_a_located_validation_error(self, tmp_path):
        root = self._project(tmp_path, "{sessionInitStatement: DROP TABLE x}")
        with pytest.raises(ProjectConfigError) as caught:
            validate_project(root)
        text = str(caught.value)
        assert "sessionInitStatement" in text
        assert "pipelines/p.yaml" in text

    def test_ordinary_options_validate(self, tmp_path):
        root = self._project(tmp_path, "{fetchsize: 500}")
        assert validate_project(root).pipelines["p"].nodes["pull"].ingest.options == {
            "fetchsize": 500
        }


def test_a_table_name_with_a_trailing_newline_is_not_an_identifier():
    with pytest.raises(ValueError, match="plain identifier"):
        IngestionExecutor._build_dbtable("n", "users\n", None, None)
    assert IngestionExecutor._build_dbtable("n", "dbo.users", None, None) == "dbo.users"
