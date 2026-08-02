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
    SparkWriterMixin,
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


# ── SparkWriterMixin ─────────────────────────────────────────────────────────


class _ConcreteWriter(SparkWriterMixin):
    FORMAT = "test"


class TestSparkWriterMixin:
    def test_get_format(self):
        w = _ConcreteWriter()
        assert w._get_format() == "test"

    def test_determine_write_mode_valid(self):
        w = _ConcreteWriter()
        assert w._determine_write_mode({"write_mode": "append"}) == "append"
        assert w._determine_write_mode({"write_mode": "overwrite"}) == "overwrite"
        assert w._determine_write_mode({"write_mode": "ignore"}) == "ignore"
        assert w._determine_write_mode({"write_mode": "error"}) == "error"

    def test_determine_write_mode_invalid(self):
        # Regression: an invalid write_mode used to silently fall back to
        # 'overwrite' — the most destructive mode available — instead of
        # failing. A config typo must never translate into data loss.
        w = _ConcreteWriter()
        with pytest.raises(ConfigurationError, match="Invalid write_mode"):
            w._determine_write_mode({"write_mode": "invalid"})

    def test_determine_write_mode_default(self):
        w = _ConcreteWriter()
        assert w._determine_write_mode({}) == "overwrite"

    def test_supports_overwrite_schema_delta(self):
        w = DeltaWriter.__new__(DeltaWriter)
        w.FORMAT = "delta"
        assert w._supports_overwrite_schema() is True

    def test_supports_overwrite_schema_parquet(self):
        w = ParquetWriter.__new__(ParquetWriter)
        w.FORMAT = "parquet"
        assert w._supports_overwrite_schema() is True

    def test_supports_overwrite_schema_other(self):
        w = _ConcreteWriter()
        assert w._supports_overwrite_schema() is False


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
