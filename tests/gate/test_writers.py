from unittest.mock import MagicMock, call

import pytest

from ducta.gate.exceptions import (
    ConfigurationError,
    DataValidationError,
    WriteOperationError,
)
from ducta.gate.writers import (
    BaseSparkWriter,
    CSVWriter,
    DeltaWriter,
    JSONWriter,
    ORCWriter,
    ParquetWriter,
    normalize_partition_config,
)

# ── normalize_partition_config ───────────────────────────────────────────────


class TestNormalizePartitionConfig:
    def test_no_partition(self):
        result = normalize_partition_config({})
        assert result == {}

    def test_partition_key(self):
        result = normalize_partition_config({"partition": "col1"})
        assert result["partition"] == "col1"
        assert result["partition_col"] == "col1"
        assert result["partition_columns"] == ["col1"]

    def test_partition_col_key(self):
        result = normalize_partition_config({"partition_col": "col1"})
        assert result["partition_col"] == "col1"
        assert result["partition_columns"] == ["col1"]

    def test_partition_columns_key(self):
        result = normalize_partition_config({"partition_columns": ["c1", "c2"]})
        assert result["partition"] == ["c1", "c2"]
        assert result["partition_columns"] == ["c1", "c2"]

    def test_single_element_list(self):
        result = normalize_partition_config({"partition": ["c1"]})
        assert result["partition_col"] == "c1"

    def test_does_not_mutate_original(self):
        original = {"partition": "col1"}
        result = normalize_partition_config(original)
        assert original == {"partition": "col1"}
        assert result is not original


# ── BaseSparkWriter: write mode, overwriteSchema, replaceWhere ───────────────


class _ConcreteWriter(BaseSparkWriter):
    FORMAT = "test"


def _writer(cls=_ConcreteWriter):
    return cls({"spark": MagicMock()})


class TestWriteConfiguration:
    def test_determine_write_mode_valid(self):
        w = _writer()
        assert w._determine_write_mode({"write_mode": "append"}) == "append"
        assert w._determine_write_mode({"write_mode": "overwrite"}) == "overwrite"
        assert w._determine_write_mode({"write_mode": "ignore"}) == "ignore"
        assert w._determine_write_mode({"write_mode": "error"}) == "error"

    def test_determine_write_mode_invalid(self):
        # Regression: an invalid write_mode used to silently fall back to
        # 'overwrite' — the most destructive mode available — instead of
        # failing. A config typo must never translate into data loss.
        with pytest.raises(ConfigurationError, match="Invalid write_mode"):
            _writer()._determine_write_mode({"write_mode": "invalid"})

    def test_determine_write_mode_default(self):
        assert _writer()._determine_write_mode({}) == "overwrite"

    def test_merge_is_only_for_delta(self):
        with pytest.raises(ConfigurationError, match="only for format 'delta'"):
            _writer()._determine_write_mode({"write_mode": "merge"})

    @pytest.mark.parametrize(
        "cls, fmt, expected",
        [
            (DeltaWriter, "delta", True),
            (ParquetWriter, "parquet", False),
            (CSVWriter, "csv", False),
        ],
    )
    def test_overwrite_schema_defaults_on_for_delta_only(self, cls, fmt, expected):
        writer = MagicMock()
        _writer(cls)._apply_overwrite_and_replacewhere(writer, {}, "overwrite")
        applied = call("overwriteSchema", "true") in writer.option.call_args_list
        assert applied is expected

    @pytest.mark.parametrize(
        "cls, supported", [(DeltaWriter, True), (ParquetWriter, True), (CSVWriter, False)]
    )
    def test_overwrite_schema_can_be_asked_for_only_where_supported(self, cls, supported):
        writer = MagicMock()
        _writer(cls)._apply_overwrite_and_replacewhere(
            writer, {"overwrite_schema": True}, "overwrite"
        )
        applied = call("overwriteSchema", "true") in writer.option.call_args_list
        assert applied is supported


class TestReplaceWhere:
    CONFIG = {
        "overwrite_strategy": "replaceWhere",
        "partition_col": "event_date",
        "start_date": "2024-01-01",
        "end_date": "2024-01-31",
    }

    def _apply(self, config, cls=DeltaWriter):
        writer = MagicMock()
        writer.option.return_value = writer
        _writer(cls)._apply_replace_where_strategy(writer, config)
        return writer

    def test_predicate_quotes_the_column(self):
        writer = self._apply(self.CONFIG)
        writer.option.assert_any_call(
            "replaceWhere", "`event_date` BETWEEN '2024-01-01' AND '2024-01-31'"
        )

    def test_a_hostile_column_name_stays_one_identifier(self):
        writer = self._apply({**self.CONFIG, "partition_col": "d` OR 1=1 --"})
        predicate = next(
            c.args[1] for c in writer.option.call_args_list if c.args[0] == "replaceWhere"
        )
        assert predicate.startswith("`d`` OR 1=1 --` BETWEEN")

    def test_custom_predicate_is_used_as_written(self):
        writer = self._apply({"overwrite_strategy": "replaceWhere", "replace_predicate": "x = 1"})
        writer.option.assert_any_call("replaceWhere", "x = 1")

    def test_missing_pieces_are_named(self):
        with pytest.raises(ConfigurationError, match="start_date, end_date"):
            self._apply({"overwrite_strategy": "replaceWhere", "partition_col": "d"})

    def test_bad_date_format_is_refused(self):
        with pytest.raises(ConfigurationError, match="Invalid date format"):
            self._apply({**self.CONFIG, "start_date": "01/01/2024"})

    def test_only_delta_supports_it(self):
        with pytest.raises(ConfigurationError, match="only for Delta"):
            self._apply(self.CONFIG, cls=ParquetWriter)


class TestProgressReporting:
    def test_reporter_is_told_where_the_output_goes(self):
        reporter = MagicMock()
        writer = BaseSparkWriter({"spark": MagicMock(), "progress_reporter": reporter})
        writer._print_write_separator("/out")
        reporter.report_saving.assert_called_once_with("/out")

    def test_a_failing_reporter_does_not_break_the_write(self):
        reporter = MagicMock()
        reporter.report_saving.side_effect = RuntimeError("terminal gone")
        writer = BaseSparkWriter({"spark": MagicMock(), "progress_reporter": reporter})
        writer._print_write_separator("/out")  # must not raise


# ── BaseSparkWriter ──────────────────────────────────────────────────────────


class TestBaseSparkWriter:
    def test_write_empty_destination(self, spark_dataframe):
        context = {"spark": MagicMock()}
        writer = BaseSparkWriter(context)
        with pytest.raises(ConfigurationError, match="cannot be empty"):
            writer.write(spark_dataframe, "", {})

    def test_write_success(self, spark_dataframe):
        context = {"spark": MagicMock()}
        writer = DeltaWriter(context)
        writer._configure_spark_writer = MagicMock(return_value=spark_dataframe.write)
        writer.write(spark_dataframe, "/path", {})
        spark_dataframe.write.save.assert_called_with("/path")

    def test_write_exception(self, spark_dataframe):
        context = {"spark": MagicMock()}
        writer = DeltaWriter(context)
        writer._configure_spark_writer = MagicMock(side_effect=WriteOperationError("fail"))
        with pytest.raises(WriteOperationError):
            writer.write(spark_dataframe, "/path", {})


class TestOptionValuesAreNotLogged:
    """A writer option can carry a key or a token (``fs.azure.account.key…``). DEBUG goes to
    ``logs/ducta.log`` with no redaction, so the log names the option and never its value."""

    SECRET = "S3cr3t-Value-0123456789"

    def test_the_value_of_an_extra_option_never_reaches_the_log(self):
        from unittest.mock import patch

        df = MagicMock()
        df.isEmpty.return_value = False
        df.columns = ["a"]
        df.write.format.return_value.mode.return_value = df.write
        df.write.option.return_value = df.write
        writer = _writer(ParquetWriter)
        with patch("ducta.gate.writers.logger") as log:
            writer._configure_spark_writer(
                df, {"write_mode": "append", "options": {"fs.azure.account.key.acc": self.SECRET}}
            )
        df.write.option.assert_any_call("fs.azure.account.key.acc", self.SECRET)  # still applied
        logged = " ".join(str(a) for c in log.mock_calls for a in (*c.args, *c.kwargs.values()))
        assert self.SECRET not in logged
        assert "fs.azure.account.key.acc" in logged


class TestReplaceWhereIsAPlainPredicate:
    BAD = "reflect('java.lang.System', 'getenv', 'HOME') = 'x'"

    def test_a_replace_predicate_that_calls_the_jvm_is_refused(self):
        from ducta.gate.writers import DeltaWriter

        writer = MagicMock()
        with pytest.raises(ConfigurationError, match="replace_predicate"):
            DeltaWriter({})._apply_replace_where_strategy(writer, {"replace_predicate": self.BAD})
        writer.option.assert_not_called()

    def test_a_replacewhere_option_cannot_replace_the_checked_predicate(self):
        from ducta.gate.writers import vetted_write_options

        with pytest.raises(ConfigurationError, match="options.replaceWhere"):
            vetted_write_options({"replaceWhere": self.BAD})
        with pytest.raises(ConfigurationError, match="options.REPLACEWHERE"):
            vetted_write_options({"REPLACEWHERE": self.BAD})
        assert vetted_write_options({"replaceWhere": "dt = '2024-01-01'", "x": 1}) == {
            "replaceWhere": "dt = '2024-01-01'",
            "x": 1,
        }

    def test_the_predicate_ducta_builds_passes_its_own_check(self):
        from ducta.gate.sql import replace_where_clause
        from ducta.gate.writers import vetted_write_options

        clause = replace_where_clause("meta.event_date", "2024-01-01", "2024-01-31")
        assert vetted_write_options({"replaceWhere": clause})["replaceWhere"] == clause


class TestMergeNamesAreQuoted:
    def test_a_column_with_a_backtick_cannot_end_its_quoting(self):
        from ducta.gate.writers import _quote

        assert _quote("a`b") == "`a``b`"
        assert _quote("order id") == "`order id`"
