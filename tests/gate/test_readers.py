import sys
from unittest.mock import MagicMock, PropertyMock, call, patch

import pytest

from ducta.gate.exceptions import ConfigurationError, FormatNotSupportedError, ReadOperationError
from ducta.gate.readers import (
    AvroReader,
    CSVReader,
    DeltaReader,
    JSONReader,
    ORCReader,
    ParquetReader,
    PickleReader,
    QueryReader,
    SparkReaderBase,
    XMLReader,
)


class TestSparkReaderBase:
    def test_apply_partition_filter_no_filter(self, spark_dataframe):
        reader = SparkReaderBase({"spark": MagicMock()})
        result = reader._apply_partition_filter(spark_dataframe, {})
        assert result is spark_dataframe
        spark_dataframe.filter.assert_not_called()

    def test_apply_partition_filter_with_filter(self, spark_dataframe):
        reader = SparkReaderBase({"spark": MagicMock()})
        reader._apply_partition_filter(spark_dataframe, {"partition_filter": "date > '2024-01-01'"})
        spark_dataframe.filter.assert_called_once_with("date > '2024-01-01'")

    def test_apply_partition_filter_falls_back_to_where(self, spark_dataframe):
        reader = SparkReaderBase({"spark": MagicMock()})
        spark_dataframe.filter.side_effect = Exception("filter failed")
        reader._apply_partition_filter(spark_dataframe, {"partition_filter": "date > '2024-01-01'"})
        spark_dataframe.where.assert_called_once_with("date > '2024-01-01'")

    def test_apply_partition_filter_both_fail(self, spark_dataframe):
        reader = SparkReaderBase({"spark": MagicMock()})
        spark_dataframe.filter.side_effect = Exception("filter failed")
        spark_dataframe.where.side_effect = Exception("where failed")
        with pytest.raises(ReadOperationError, match="Both filter"):
            reader._apply_partition_filter(
                spark_dataframe, {"partition_filter": "date > '2024-01-01'"}
            )

    def test_spark_read_no_spark(self):
        reader = SparkReaderBase({"spark": None})
        with pytest.raises(ReadOperationError, match="Spark session"):
            reader._spark_read("parquet", "/path", {})

    def test_spark_read_success(self, spark_session, spark_dataframe):
        spark_session.read.options.return_value = spark_session.read
        spark_session.read.format.return_value = spark_session.read
        spark_session.read.load.return_value = spark_dataframe
        reader = SparkReaderBase({"spark": spark_session})
        result = reader._spark_read("parquet", "/path", {})
        assert result is spark_dataframe

    def test_spark_read_load_exception(self, spark_session):
        spark_session.read.options.return_value = spark_session.read
        spark_session.read.format.return_value = spark_session.read
        spark_session.read.load.side_effect = Exception("load failed")
        reader = SparkReaderBase({"spark": spark_session})
        with pytest.raises(ReadOperationError, match="load failed"):
            reader._spark_read("parquet", "/path", {})


class TestParquetReader:
    def test_read(self, spark_session, spark_dataframe):
        spark_session.read.options.return_value = spark_session.read
        spark_session.read.format.return_value = spark_session.read
        spark_session.read.load.return_value = spark_dataframe
        reader = ParquetReader({"spark": spark_session})
        result = reader.read("/path", {})
        assert result is spark_dataframe


class TestJSONReader:
    def test_read_with_default_encoding(self, spark_session, spark_dataframe):
        spark_session.read.options.return_value = spark_session.read
        spark_session.read.format.return_value = spark_session.read
        spark_session.read.load.return_value = spark_dataframe
        reader = JSONReader({"spark": spark_session})
        reader.read("/path", {})

    def test_read_custom_encoding(self, spark_session, spark_dataframe):
        spark_session.read.options.return_value = spark_session.read
        spark_session.read.format.return_value = spark_session.read
        spark_session.read.load.return_value = spark_dataframe
        reader = JSONReader({"spark": spark_session})
        reader.read("/path", {"options": {"encoding": "ISO-8859-1"}})


class TestCSVReader:
    def test_read_with_default_options(self, spark_session, spark_dataframe):
        spark_session.read.options.return_value = spark_session.read
        spark_session.read.format.return_value = spark_session.read
        spark_session.read.load.return_value = spark_dataframe
        reader = CSVReader({"spark": spark_session})
        reader.read("/path", {})

    def test_read_custom_options_override(self, spark_session, spark_dataframe):
        spark_session.read.options.return_value = spark_session.read
        spark_session.read.format.return_value = spark_session.read
        spark_session.read.load.return_value = spark_dataframe
        reader = CSVReader({"spark": spark_session})
        reader.read("/path", {"options": {"header": "false"}})


class TestDeltaReader:
    def test_read_no_spark(self):
        reader = DeltaReader({"spark": None})
        with pytest.raises(ReadOperationError, match="Spark session"):
            reader.read("/path", {})

    def test_read_default(self, spark_session, spark_dataframe):
        spark_session.read.options.return_value = spark_session.read
        spark_session.read.format.return_value = spark_session.read
        spark_session.read.load.return_value = spark_dataframe
        reader = DeltaReader({"spark": spark_session})
        result = reader.read("/path", {})
        assert result is spark_dataframe

    def test_read_with_version(self, spark_session, spark_dataframe):
        spark_session.read.options.return_value = spark_session.read
        spark_session.read.format.return_value = spark_session.read
        spark_session.read.load.return_value = spark_dataframe
        spark_session.read.option = MagicMock(return_value=spark_session.read)
        reader = DeltaReader({"spark": spark_session})
        reader.read("/path", {"versionAsOf": 5})
        spark_session.read.option.assert_called_with("versionAsOf", 5)

    def test_read_with_timestamp(self, spark_session, spark_dataframe):
        spark_session.read.options.return_value = spark_session.read
        spark_session.read.format.return_value = spark_session.read
        spark_session.read.load.return_value = spark_dataframe
        spark_session.read.option = MagicMock(return_value=spark_session.read)
        reader = DeltaReader({"spark": spark_session})
        reader.read("/path", {"timestampAsOf": "2024-01-01"})
        spark_session.read.option.assert_called_with("timestampAsOf", "2024-01-01")


class TestPickleReader:
    def test_read_without_allow_untrusted(self):
        reader = PickleReader({"spark": MagicMock()})
        with pytest.raises(ReadOperationError, match="allow_untrusted_pickle"):
            reader.read("/path", {})

    def test_read_local_pickle(self, temp_dir):
        import pickle as _pickle

        p = temp_dir / "data.pkl"
        data = {"a": 1, "b": 2}
        _pickle.dump(data, open(p, "wb"))
        reader = PickleReader({"spark": None})
        result = reader.read(str(p), {"allow_untrusted_pickle": True, "use_pandas": True})
        assert result == data

    def test_read_local_file_not_found(self):
        reader = PickleReader({"spark": None})
        with pytest.raises(ReadOperationError, match="not found"):
            reader.read("/nonexistent.pkl", {"allow_untrusted_pickle": True})

    def test_get_safe_max_records_default(self):
        reader = PickleReader({"spark": MagicMock()})
        assert reader._get_safe_max_records({}) == PickleReader.DEFAULT_MAX_RECORDS

    def test_get_safe_max_records_zero(self):
        reader = PickleReader({"spark": MagicMock()})
        assert reader._get_safe_max_records({"max_records": 0}) == 0

    def test_get_safe_max_records_below_absolute(self):
        reader = PickleReader({"spark": MagicMock()})
        result = reader._get_safe_max_records({"max_records": 500})
        assert result == 500

    def test_get_safe_max_records_exceeds_absolute(self):
        reader = PickleReader({"spark": MagicMock()})
        result = reader._get_safe_max_records({"max_records": 2_000_000})
        assert result == PickleReader.ABSOLUTE_MAX_RECORDS

    def test_get_safe_max_records_invalid(self):
        reader = PickleReader({"spark": MagicMock()})
        result = reader._get_safe_max_records({"max_records": "invalid"})
        assert result == PickleReader.DEFAULT_MAX_RECORDS


class TestAvroReader:
    def test_read(self, spark_session, spark_dataframe):
        spark_session.read.options.return_value = spark_session.read
        spark_session.read.format.return_value = spark_session.read
        spark_session.read.load.return_value = spark_dataframe
        reader = AvroReader({"spark": spark_session})
        reader.read("/path", {})
        spark_session.read.format.assert_called_with("avro")


class TestORCReader:
    def test_read(self, spark_session, spark_dataframe):
        spark_session.read.options.return_value = spark_session.read
        spark_session.read.format.return_value = spark_session.read
        spark_session.read.load.return_value = spark_dataframe
        reader = ORCReader({"spark": spark_session})
        reader.read("/path", {})
        spark_session.read.format.assert_called_with("orc")


class TestXMLReader:
    def test_read_no_spark(self):
        reader = XMLReader({"spark": None})
        with pytest.raises(ReadOperationError, match="Spark session"):
            reader.read("/path", {})

    def test_read_missing_package(self, spark_session):
        del spark_session._jvm.com.databricks.spark.xml
        reader = XMLReader({"spark": spark_session})
        with pytest.raises(ConfigurationError, match="XML reader requires"):
            reader.read("/path", {})

    def test_read_success(self, spark_session, spark_dataframe):
        spark_session.read.format.return_value = spark_session.read
        spark_session.read.option.return_value = spark_session.read
        spark_session.read.options.return_value = spark_session.read
        spark_session.read.load.return_value = spark_dataframe
        reader = XMLReader({"spark": spark_session})
        result = reader.read("/path", {"rowTag": "record"})
        assert result is spark_dataframe


class TestQueryReader:
    def test_read_no_spark(self):
        reader = QueryReader({"spark": None})
        with pytest.raises(ReadOperationError, match="Spark session"):
            reader.read("", {"query": "SELECT 1"})

    def test_read_no_query(self, spark_session):
        reader = QueryReader({"spark": spark_session})
        with pytest.raises(ReadOperationError, match="specified without SQL"):
            reader.read("", {})

    def test_read_empty_query(self, spark_session):
        reader = QueryReader({"spark": spark_session})
        with pytest.raises(ReadOperationError, match="empty"):
            reader.read("", {"query": ""})

    def test_read_success(self, spark_session):
        spark_session.sql.return_value = "result"
        reader = QueryReader({"spark": spark_session})
        result = reader.read("", {"query": "SELECT 1 AS col"})
        assert result == "result"

    def test_read_dangerous_query(self, spark_session):
        reader = QueryReader({"spark": spark_session})
        with pytest.raises(ReadOperationError):
            reader.read("", {"query": "DROP TABLE users"})

    def test_read_sql_exception(self, spark_session):
        spark_session.sql.side_effect = Exception("query failed")
        reader = QueryReader({"spark": spark_session})
        with pytest.raises(ReadOperationError, match="query failed"):
            reader.read("", {"query": "SELECT 1"})
