"""Unit tests for ducta.stream.readers: factory + concrete streaming readers."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from ducta.stream.exceptions import StreamingError, StreamingFormatNotSupportedError
from ducta.stream.readers import (
    BaseStreamingReader,
    DeltaStreamingReader,
    FileStreamReader,
    KafkaStreamingReader,
    KinesisStreamingReader,
    StreamingReaderFactory,
)


class TestStreamingSparkMixinSpark:
    def test_dict_context_returns_spark(self, dict_context, spark_session):
        reader = FileStreamReader(dict_context)
        assert reader.spark is spark_session

    def test_object_context_returns_spark(self, obj_context, spark_session):
        reader = FileStreamReader(obj_context)
        assert reader.spark is spark_session

    def test_missing_context_raises(self):
        reader = FileStreamReader(None)
        with pytest.raises(StreamingError, match="Context is not set"):
            reader.spark

    def test_missing_spark_in_context_raises(self):
        reader = FileStreamReader({"spark": None})
        with pytest.raises(StreamingError, match="Spark session is not available"):
            reader.spark


class TestBaseStreamingReaderHelpers:
    def test_coerce_bool_from_bool(self):
        assert BaseStreamingReader._coerce_bool(True) is True
        assert BaseStreamingReader._coerce_bool(False) is False

    def test_coerce_bool_from_string(self):
        assert BaseStreamingReader._coerce_bool("true") is True
        assert BaseStreamingReader._coerce_bool("Yes") is True
        assert BaseStreamingReader._coerce_bool("0") is False
        assert BaseStreamingReader._coerce_bool("false") is False

    def test_backpressure_disabled_default_false(self, dict_context):
        reader = FileStreamReader(dict_context)
        assert reader._backpressure_disabled() is False

    def test_backpressure_disabled_reads_global_setting(self, dict_context):
        dict_context["global_config"]["streaming_disable_backpressure_defaults"] = True
        reader = FileStreamReader(dict_context)
        assert reader._backpressure_disabled() is True

    def test_merge_backpressure_defaults_injects_missing(self, dict_context):
        reader = KafkaStreamingReader(dict_context)
        merged = reader._merge_backpressure_defaults({}, "kafka")
        assert merged["maxOffsetsPerTrigger"] == 1_000_000

    def test_merge_backpressure_defaults_respects_user_value(self, dict_context):
        reader = KafkaStreamingReader(dict_context)
        merged = reader._merge_backpressure_defaults({"maxOffsetsPerTrigger": 5}, "kafka")
        assert merged["maxOffsetsPerTrigger"] == 5

    def test_merge_backpressure_defaults_disabled_globally(self, dict_context):
        dict_context["global_config"]["streaming_disable_backpressure_defaults"] = True
        reader = KafkaStreamingReader(dict_context)
        merged = reader._merge_backpressure_defaults({}, "kafka")
        assert "maxOffsetsPerTrigger" not in merged

    def test_apply_options_skips_none_values(self, dict_context, spark_session):
        reader = FileStreamReader(dict_context)
        writer = MagicMock()
        writer.option.return_value = writer
        reader._apply_options(writer, {"a": "1", "b": None})
        writer.option.assert_called_once_with("a", "1")


class TestKafkaStreamingReader:
    def _valid_config(self):
        return {"options": {"kafka.bootstrap.servers": "host:9092", "subscribe": "topic1"}}

    def test_missing_bootstrap_servers_raises(self, dict_context):
        reader = KafkaStreamingReader(dict_context)
        with pytest.raises(StreamingError, match="Missing required options"):
            reader.read_stream({"options": {"subscribe": "topic1"}})

    def test_missing_subscription_option_raises(self, dict_context):
        reader = KafkaStreamingReader(dict_context)
        with pytest.raises(StreamingError, match="Exactly one of"):
            reader.read_stream({"options": {"kafka.bootstrap.servers": "host:9092"}})

    def test_multiple_subscription_options_raises(self, dict_context):
        reader = KafkaStreamingReader(dict_context)
        config = {
            "options": {
                "kafka.bootstrap.servers": "host:9092",
                "subscribe": "t1",
                "assign": "t2",
            }
        }
        with pytest.raises(StreamingError, match="Exactly one of"):
            reader.read_stream(config)

    def test_success_builds_reader_chain(self, dict_context, spark_session):
        reader = KafkaStreamingReader(dict_context)
        result = reader.read_stream(self._valid_config())
        spark_session.readStream.format.assert_called_with("kafka")
        assert result is not None

    def test_missing_datasource_error_enriched(self, dict_context, spark_session):
        spark_session.readStream.load.side_effect = Exception("Failed to find data source: kafka")
        reader = KafkaStreamingReader(dict_context)
        with pytest.raises(StreamingError, match="spark.jars.packages"):
            reader.read_stream(self._valid_config())

    def test_parse_json_without_schema_warns_and_skips(self, dict_context, spark_session):
        config = dict(self._valid_config())
        config["parse_json"] = True
        reader = KafkaStreamingReader(dict_context)
        result = reader.read_stream(config)
        assert result is not None


class TestDeltaStreamingReader:
    def test_missing_path_raises(self, dict_context):
        reader = DeltaStreamingReader(dict_context)
        with pytest.raises(StreamingError, match="requires 'path'"):
            reader.read_stream({"auto_enable_cdf": False})

    def test_success_loads_path(self, dict_context, spark_session):
        reader = DeltaStreamingReader(dict_context)
        result = reader.read_stream({"path": "/tmp/table", "auto_enable_cdf": False})
        spark_session.readStream.format.assert_called_with("delta")
        spark_session.readStream.load.assert_called_with("/tmp/table")
        assert result is not None

    def test_delta_module_absent_skips_cdf_check(self, dict_context, spark_session):
        # `delta.tables` is mocked but DeltaTable is absent from it, so the
        # ImportError branch inside _ensure_cdf_enabled is exercised.
        reader = DeltaStreamingReader(dict_context)
        result = reader.read_stream({"path": "/tmp/table", "auto_enable_cdf": True})
        assert result is not None

    def test_ensure_cdf_enabled_escapes_backticks_in_path(
        self, dict_context, spark_session, monkeypatch
    ):
        """Regression: a path containing a backtick must not break out of the
        `ALTER TABLE delta.\\`{path}\\`` identifier and inject SQL."""
        fake_detail_row = {"properties": {"delta.enableChangeDataFeed": "false"}}
        fake_table = MagicMock()
        fake_table.detail.return_value.collect.return_value = [fake_detail_row]

        fake_delta_table_cls = MagicMock()
        fake_delta_table_cls.isDeltaTable.return_value = True
        fake_delta_table_cls.forPath.return_value = fake_table

        monkeypatch.setattr(
            sys.modules["delta.tables"], "DeltaTable", fake_delta_table_cls, raising=False
        )

        malicious_path = "/tmp/table`; DROP TABLE x; --"
        reader = DeltaStreamingReader(dict_context)
        reader.read_stream({"path": malicious_path, "auto_enable_cdf": True})

        assert spark_session.sql.call_args is not None
        executed_sql = spark_session.sql.call_args[0][0]
        # The lone backtick that would otherwise terminate the identifier early
        # must be doubled (escaped): the identifier must contain the fully
        # escaped path, and never the raw (unescaped) path.
        escaped_path = malicious_path.replace("`", "``")
        assert f"delta.`{escaped_path}`" in executed_sql
        assert f"delta.`{malicious_path}`" not in executed_sql

    def test_ensure_cdf_enabled_failure_logs_clear_context(
        self, dict_context, spark_session, monkeypatch
    ):
        """Regression: a failure enabling CDF (e.g. the ALTER TABLE call
        itself failing) logged a bare "Could not auto-enable CDF" warning —
        the stream still proceeds with CDF disabled and startingVersion
        unset, which can replay non-CDF history under CDF read semantics.
        The warning should say that explicitly, not just report the
        exception."""
        fake_detail_row = {"properties": {"delta.enableChangeDataFeed": "false"}}
        fake_table = MagicMock()
        fake_table.detail.return_value.collect.return_value = [fake_detail_row]

        fake_delta_table_cls = MagicMock()
        fake_delta_table_cls.isDeltaTable.return_value = True
        fake_delta_table_cls.forPath.return_value = fake_table

        monkeypatch.setattr(
            sys.modules["delta.tables"], "DeltaTable", fake_delta_table_cls, raising=False
        )
        spark_session.sql.side_effect = RuntimeError("ALTER TABLE failed")

        with patch("ducta.stream.readers.logger") as mock_logger:
            reader = DeltaStreamingReader(dict_context)
            reader.read_stream({"path": "/tmp/table", "auto_enable_cdf": True})

        warning_calls = [str(call) for call in mock_logger.warning.call_args_list]
        assert any("still disabled" in call for call in warning_calls)


class TestFileStreamReader:
    def test_missing_path_raises(self, dict_context):
        reader = FileStreamReader(dict_context)
        with pytest.raises(StreamingError, match="Missing required options"):
            reader.read_stream({})

    def test_success_with_path_in_options(self, dict_context, spark_session):
        reader = FileStreamReader(dict_context)
        result = reader.read_stream({"file_format": "json", "options": {"path": "/tmp/in"}})
        spark_session.readStream.format.assert_called_with("json")
        spark_session.readStream.load.assert_called_with("/tmp/in")
        assert result is not None

    def test_deprecated_top_level_path_still_works(self, dict_context, spark_session):
        reader = FileStreamReader(dict_context)
        result = reader.read_stream({"path": "/tmp/in", "options": {}})
        spark_session.readStream.load.assert_called_with("/tmp/in")
        assert result is not None

    def test_defaults_to_parquet_format(self, dict_context, spark_session):
        reader = FileStreamReader(dict_context)
        reader.read_stream({"options": {"path": "/tmp/in"}})
        spark_session.readStream.format.assert_called_with("parquet")


class TestKinesisStreamingReader:
    def test_missing_required_options_raises(self, dict_context):
        reader = KinesisStreamingReader(dict_context)
        with pytest.raises(StreamingError, match="Missing required options"):
            reader.read_stream({"options": {"streamName": "s1"}})

    def test_success(self, dict_context, spark_session):
        reader = KinesisStreamingReader(dict_context)
        result = reader.read_stream({"options": {"streamName": "s1", "region": "us-east-1"}})
        spark_session.readStream.format.assert_called_with("kinesis")
        assert result is not None

    def test_applies_backpressure_defaults(self, dict_context, spark_session, monkeypatch):
        # Regression: KinesisStreamingReader used to skip _merge_backpressure_defaults
        # entirely, unlike Kafka/Delta/File — a default added later for "kinesis"
        # in STREAMING_BACKPRESSURE_DEFAULTS would silently never apply.
        from ducta.stream import constants as stream_constants

        monkeypatch.setitem(
            stream_constants.STREAMING_BACKPRESSURE_DEFAULTS,
            "kinesis",
            {"maxRecordsPerFetch": 500},
        )
        reader = KinesisStreamingReader(dict_context)
        reader.read_stream({"options": {"streamName": "s1", "region": "us-east-1"}})
        spark_session.readStream.option.assert_any_call("maxRecordsPerFetch", "500")


class TestStreamingReaderFactory:
    def test_lists_builtin_formats(self, dict_context):
        factory = StreamingReaderFactory(dict_context)
        formats = factory.list_supported_formats()
        for fmt in ("kafka", "delta_stream", "file_stream", "kinesis"):
            assert fmt in formats

    def test_get_reader_known_format(self, dict_context):
        factory = StreamingReaderFactory(dict_context)
        reader = factory.get_reader("kafka")
        assert isinstance(reader, KafkaStreamingReader)

    def test_get_reader_case_insensitive(self, dict_context):
        factory = StreamingReaderFactory(dict_context)
        assert factory.get_reader("KAFKA") is factory.get_reader("kafka")

    def test_get_reader_lazy_caching(self, dict_context):
        factory = StreamingReaderFactory(dict_context)
        r1 = factory.get_reader("delta_stream")
        r2 = factory.get_reader("delta_stream")
        assert r1 is r2

    def test_get_reader_unsupported_format_raises(self, dict_context):
        factory = StreamingReaderFactory(dict_context)
        with pytest.raises(StreamingFormatNotSupportedError, match="not supported"):
            factory.get_reader("unsupported")

    def test_get_reader_empty_name_raises(self, dict_context):
        factory = StreamingReaderFactory(dict_context)
        with pytest.raises(StreamingError, match="non-empty string"):
            factory.get_reader("")

    def test_register_custom_reader_new_format(self, dict_context):
        class CustomReader(BaseStreamingReader):
            def read_stream(self, config):
                return "custom-result"

        factory = StreamingReaderFactory(dict_context)
        factory.register_custom_reader("custom", CustomReader)
        reader = factory.get_reader("custom")
        assert isinstance(reader, CustomReader)

    def test_register_custom_reader_rejects_non_subclass(self, dict_context):
        class NotAReader:
            pass

        factory = StreamingReaderFactory(dict_context)
        with pytest.raises(StreamingError, match="must inherit"):
            factory.register_custom_reader("bad", NotAReader)

    def test_register_custom_reader_invalidates_cache(self, dict_context):
        class ReaderA(BaseStreamingReader):
            def read_stream(self, config):
                return "a"

        class ReaderB(BaseStreamingReader):
            def read_stream(self, config):
                return "b"

        factory = StreamingReaderFactory(dict_context)
        factory.register_custom_reader("custom", ReaderA)
        first = factory.get_reader("custom")
        factory.register_custom_reader("custom", ReaderB)
        second = factory.get_reader("custom")
        assert isinstance(first, ReaderA)
        assert isinstance(second, ReaderB)

    def test_register_custom_reader_forwards_extra_args(self, dict_context):
        class ConfigurableReader(BaseStreamingReader):
            def __init__(self, context, marker):
                super().__init__(context)
                self.marker = marker

            def read_stream(self, config):
                return self.marker

        factory = StreamingReaderFactory(dict_context)
        factory.register_custom_reader("custom", ConfigurableReader, "hello")
        reader = factory.get_reader("custom")
        assert reader.marker == "hello"
