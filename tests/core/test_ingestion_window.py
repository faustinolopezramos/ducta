"""``ingest.incremental``: the source filters the run's window, in its own dialect.

A declarative ingestion read the whole table on every run — its ``where`` is static and the
run's ``--start-date``/``--end-date`` reached only the writer. With ``incremental: {column}``
the window becomes a predicate in the statement sent to the database, built from a plain
identifier and validated ISO dates.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ducta.core.execution.ingestion import IngestionExecutor
from ducta.core.preflight import PreflightReport, _check_ingestion_node, _check_windowed_overwrite


def _harness(source_type="postgres"):
    spark = MagicMock()
    reader = spark.read.format.return_value
    reader.options.return_value = reader
    connection = SimpleNamespace(
        jdbc_url="jdbc:x://h/d",
        jdbc_properties={"user": "u", "password": "p", "driver": "d"},
        connector=SimpleNamespace(source_type=source_type, tls_hint=lambda error: None),
    )
    context = SimpleNamespace(
        spark=spark,
        config_paths={},
        global_config={},
        _ingestion_managers={"config/sources.yaml": SimpleNamespace(get=lambda name: connection)},
    )
    executor = IngestionExecutor(
        context, MagicMock(), MagicMock(), settings=SimpleNamespace(ingestion={})
    )

    def run(node, start="2026-01-01", end="2026-01-02"):
        reader.options.reset_mock()
        executor.execute("n", node, start, end, {})
        return reader.options.call_args.kwargs

    return run


class TestTableWindow:
    def test_the_window_is_a_predicate_with_the_end_day_whole(self):
        opts = _harness()({"source": "s", "table": "orders", "incremental": {"column": "order_ts"}})
        assert opts["dbtable"] == (
            "(SELECT * FROM orders WHERE order_ts >= '2026-01-01' AND order_ts < '2026-01-03') q"
        )

    def test_it_is_added_to_the_declared_where_and_columns(self):
        opts = _harness()(
            {
                "source": "s",
                "table": "orders",
                "columns": ["id", "order_ts"],
                "where": "status = 'paid' OR status = 'shipped'",
                "incremental": {"column": "order_ts"},
            }
        )
        assert opts["dbtable"] == (
            "(SELECT id, order_ts FROM orders WHERE (status = 'paid' OR status = 'shipped') "
            "AND order_ts >= '2026-01-01' AND order_ts < '2026-01-03') q"
        )

    def test_without_incremental_the_table_is_read_whole_as_before(self):
        assert _harness()({"source": "s", "table": "orders"})["dbtable"] == "orders"

    def test_a_run_without_dates_reads_everything(self):
        run = _harness()
        node = {"source": "s", "table": "orders", "incremental": {"column": "order_ts"}}
        assert run(node, start=None, end=None)["dbtable"] == "orders"


class TestQueryWindow:
    def test_the_declared_query_becomes_the_inner_select(self):
        opts = _harness()(
            {
                "source": "s",
                "query": "SELECT id, order_ts FROM orders WHERE total > 0",
                "incremental": {"column": "order_ts"},
            }
        )
        assert opts["query"] == (
            "SELECT * FROM (SELECT id, order_ts FROM orders WHERE total > 0) q "
            "WHERE order_ts >= '2026-01-01' AND order_ts < '2026-01-03'"
        )


class TestDialect:
    def test_oracle_gets_date_literals(self):
        opts = _harness("oracle")(
            {"source": "s", "table": "orders", "incremental": {"column": "d"}}
        )
        assert "d >= DATE '2026-01-01' AND d < DATE '2026-01-03'" in opts["dbtable"]

    @pytest.mark.parametrize("source_type", ["sqlserver", "postgres", "mysql", "mariadb"])
    def test_the_others_take_an_iso_string(self, source_type):
        opts = _harness(source_type)(
            {"source": "s", "table": "orders", "incremental": {"column": "d"}}
        )
        assert "d >= '2026-01-01' AND d < '2026-01-03'" in opts["dbtable"]


class TestOracleAlias:
    """Oracle refuses ``AS`` before a table alias (ORA-00933): no statement may carry it."""

    @pytest.mark.parametrize(
        "node",
        [
            {"source": "s", "table": "orders", "columns": ["id"]},
            {"source": "s", "table": "orders", "where": "id > 0"},
            {"source": "s", "table": "orders", "incremental": {"column": "d"}},
            {"source": "s", "query": "SELECT id, d FROM orders", "incremental": {"column": "d"}},
        ],
    )
    def test_the_alias_has_no_as(self, node):
        opts = _harness("oracle")(node)
        statement = opts.get("dbtable") or opts.get("query")
        assert ") AS q" not in statement
        assert ") q" in statement


class TestRefusals:
    @pytest.mark.parametrize("column", ["d; DROP TABLE x", "d OR 1=1", "", "a b", "d--"])
    def test_a_column_that_is_not_an_identifier_is_refused(self, column):
        with pytest.raises(ValueError, match="plain column name"):
            _harness()({"source": "s", "table": "orders", "incremental": {"column": column}})

    @pytest.mark.parametrize("end", ["2026-01-02' OR '1'='1", "tomorrow", "2026-13-40"])
    def test_a_bad_date_never_reaches_the_statement(self, end):
        node = {"source": "s", "table": "orders", "incremental": {"column": "d"}}
        with pytest.raises(ValueError, match="Invalid window"):
            _harness()(node, end=end)


class TestPreflight:
    def test_a_bad_incremental_column_is_an_error_before_the_run(self):
        report = PreflightReport("p")
        _check_ingestion_node(
            report, "n", {"source": "s", "table": "t", "incremental": {"column": "a b"}}
        )
        assert any("plain column name" in e for e in report.errors)

    def test_a_good_one_is_accepted(self):
        report = PreflightReport("p")
        _check_ingestion_node(
            report, "n", {"source": "s", "table": "t", "incremental": {"column": "meta.ts"}}
        )
        assert not report.errors


class TestWindowedOverwriteWarning:
    INPUTS = {"raw.sales.events": {"incremental": {"column": "day"}}}

    def _warnings(self, output):
        report = PreflightReport("p")
        node = {"input": ["raw.sales.events"], "output": ["out.sales.daily"]}
        _check_windowed_overwrite(report, "n", node, self.INPUTS, {"out.sales.daily": output})
        return report.warnings

    def test_a_windowed_read_into_a_partitioned_overwrite_is_warned(self):
        (warning,) = self._warnings({"format": "parquet", "partition": ["day"]})
        assert "WHOLE dataset" in warning and "partition_overwrite" in warning

    def test_an_ingest_with_incremental_is_a_windowed_read_too(self):
        report = PreflightReport("p")
        node = {"incremental": {"column": "d"}, "output": ["out.sales.daily"]}
        _check_windowed_overwrite(
            report, "n", node, {}, {"out.sales.daily": {"format": "parquet", "partition": ["d"]}}
        )
        assert len(report.warnings) == 1

    @pytest.mark.parametrize(
        "output",
        [
            {"format": "parquet", "partition": ["day"], "partition_overwrite": "dynamic"},
            {"format": "delta", "partition": ["day"], "overwrite_strategy": "replaceWhere"},
            {"format": "delta", "partition": ["day"], "write_mode": "merge"},
            {"format": "parquet", "partition": ["day"], "write_mode": "append"},
            {"format": "parquet"},
        ],
    )
    def test_a_choice_made_by_the_author_is_not_second_guessed(self, output):
        assert self._warnings(output) == []

    def test_a_read_without_a_window_is_not_warned(self):
        report = PreflightReport("p")
        node = {"input": ["raw.sales.events"], "output": ["out.sales.daily"]}
        _check_windowed_overwrite(
            report,
            "n",
            node,
            {"raw.sales.events": {"format": "csv"}},
            {"out.sales.daily": {"format": "parquet", "partition": ["day"]}},
        )
        assert report.warnings == []
