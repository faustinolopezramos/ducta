"""Unit tests for ducta.stream.writers: factory + concrete streaming writers."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ducta.stream.exceptions import StreamingError, StreamingFormatNotSupportedError
from ducta.stream.writers import (
    BaseStreamingWriter,
    ConsoleStreamingWriter,
    CSVStreamingWriter,
    DeltaStreamingWriter,
    JSONStreamingWriter,
    KafkaStreamingWriter,
    ParquetStreamingWriter,
    StreamingWriterFactory,
)


@pytest.fixture
def write_stream():
    ws = MagicMock()
    for method in ("format", "outputMode", "trigger", "option", "queryName", "partitionBy"):
        getattr(ws, method).return_value = ws
    ws.start.return_value = MagicMock(name="StreamingQuery")
    return ws


class TestBaseStreamingWriterHelpers:
    def test_validate_config_rejects_non_dict(self, dict_context):
        writer = ConsoleStreamingWriter(dict_context)
        with pytest.raises(StreamingError, match="must be a dictionary"):
            writer._validate_config("not-a-dict")

    def test_validate_config_missing_required_fields(self, dict_context):
        writer = ConsoleStreamingWriter(dict_context)
        with pytest.raises(StreamingError, match="Missing required fields"):
            writer._validate_config({}, required_fields=["path"])

    def test_apply_common_sets_output_mode_and_checkpoint(self, dict_context, write_stream):
        writer = ConsoleStreamingWriter(dict_context)
        config = {"outputMode": "append", "checkpointLocation": "/tmp/ck", "queryName": "q1"}
        result = writer._apply_common(write_stream, config)
        write_stream.outputMode.assert_called_with("append")
        write_stream.option.assert_any_call("checkpointLocation", "/tmp/ck")
        write_stream.queryName.assert_called_with("q1")
        assert result is write_stream

    def test_apply_common_trigger_dict(self, dict_context, write_stream):
        writer = ConsoleStreamingWriter(dict_context)
        writer._apply_common(write_stream, {"trigger": {"processingTime": "10 seconds"}})
        write_stream.trigger.assert_called_with(processingTime="10 seconds")

    def test_apply_common_trigger_string_fallback(self, dict_context, write_stream):
        writer = ConsoleStreamingWriter(dict_context)
        writer._apply_common(write_stream, {"trigger": "10 seconds"})
        write_stream.trigger.assert_called_with(processingTime="10 seconds")

    def test_apply_partitioning_list(self, dict_context, write_stream):
        writer = ParquetStreamingWriter(dict_context)
        writer._apply_partitioning(write_stream, {"partitionBy": ["a", "b"]})
        write_stream.partitionBy.assert_called_with("a", "b")

    def test_apply_partitioning_single_string(self, dict_context, write_stream):
        writer = ParquetStreamingWriter(dict_context)
        writer._apply_partitioning(write_stream, {"partitionBy": "a"})
        write_stream.partitionBy.assert_called_with("a")

    def test_apply_partitioning_absent_is_noop(self, dict_context, write_stream):
        writer = ParquetStreamingWriter(dict_context)
        writer._apply_partitioning(write_stream, {})
        write_stream.partitionBy.assert_not_called()


class TestConsoleStreamingWriter:
    def test_starts_with_defaults(self, dict_context, write_stream):
        writer = ConsoleStreamingWriter(dict_context)
        result = writer.write_stream(write_stream, {})
        write_stream.format.assert_called_with("console")
        write_stream.option.assert_any_call("numRows", "20")
        write_stream.option.assert_any_call("truncate", "false")
        assert result is write_stream.start.return_value

    def test_respects_user_numrows(self, dict_context, write_stream):
        writer = ConsoleStreamingWriter(dict_context)
        writer.write_stream(write_stream, {"options": {"numRows": "5"}})
        calls = [c.args for c in write_stream.option.call_args_list]
        assert ("numRows", "5") in calls


class TestDeltaStreamingWriter:
    def test_missing_path_raises(self, dict_context, write_stream):
        writer = DeltaStreamingWriter(dict_context)
        with pytest.raises(StreamingError, match="Missing required fields"):
            writer.write_stream(write_stream, {})

    def test_injects_delta_defaults(self, dict_context, write_stream):
        writer = DeltaStreamingWriter(dict_context)
        writer.write_stream(write_stream, {"path": "/tmp/t"})
        write_stream.format.assert_called_with("delta")
        write_stream.start.assert_called_with("/tmp/t")

    def test_respects_user_merge_schema(self, dict_context, write_stream):
        writer = DeltaStreamingWriter(dict_context)
        writer.write_stream(write_stream, {"path": "/tmp/t", "options": {"mergeSchema": "false"}})
        calls = [c.args for c in write_stream.option.call_args_list]
        assert ("mergeSchema", "false") in calls


class TestParquetStreamingWriter:
    def test_missing_path_raises(self, dict_context, write_stream):
        writer = ParquetStreamingWriter(dict_context)
        with pytest.raises(StreamingError, match="Missing required fields"):
            writer.write_stream(write_stream, {})

    def test_empty_path_raises(self, dict_context, write_stream):
        writer = ParquetStreamingWriter(dict_context)
        with pytest.raises(StreamingError, match="non-empty string"):
            writer.write_stream(write_stream, {"path": "   "})

    def test_success(self, dict_context, write_stream):
        writer = ParquetStreamingWriter(dict_context)
        writer.write_stream(write_stream, {"path": "/tmp/p"})
        write_stream.format.assert_called_with("parquet")
        write_stream.start.assert_called_with("/tmp/p")


class TestKafkaStreamingWriter:
    def test_missing_required_options_raises(self, dict_context, write_stream):
        writer = KafkaStreamingWriter(dict_context)
        with pytest.raises(StreamingError, match="Missing required Kafka options"):
            writer.write_stream(write_stream, {"options": {"topic": "t1"}})

    def test_success(self, dict_context, write_stream):
        writer = KafkaStreamingWriter(dict_context)
        writer.write_stream(
            write_stream,
            {"options": {"kafka.bootstrap.servers": "h:9092", "topic": "t1"}},
        )
        write_stream.format.assert_called_with("kafka")
        write_stream.start.assert_called_once_with()


class TestJSONAndCSVStreamingWriters:
    def test_json_success(self, dict_context, write_stream):
        writer = JSONStreamingWriter(dict_context)
        writer.write_stream(write_stream, {"path": "/tmp/j"})
        write_stream.format.assert_called_with("json")

    def test_csv_injects_header_default(self, dict_context, write_stream):
        writer = CSVStreamingWriter(dict_context)
        writer.write_stream(write_stream, {"path": "/tmp/c"})
        calls = [c.args for c in write_stream.option.call_args_list]
        assert ("header", "true") in calls

    def test_csv_respects_user_header(self, dict_context, write_stream):
        writer = CSVStreamingWriter(dict_context)
        writer.write_stream(write_stream, {"path": "/tmp/c", "options": {"header": "false"}})
        calls = [c.args for c in write_stream.option.call_args_list]
        assert ("header", "false") in calls


class TestStreamingWriterFactory:
    def test_lists_builtin_formats(self, dict_context):
        factory = StreamingWriterFactory(dict_context)
        formats = factory.list_supported_formats()
        for fmt in ("console", "delta", "parquet", "kafka", "json", "csv"):
            assert fmt in formats

    def test_get_writer_known_format(self, dict_context):
        factory = StreamingWriterFactory(dict_context)
        assert isinstance(factory.get_writer("delta"), DeltaStreamingWriter)

    def test_get_writer_case_insensitive(self, dict_context):
        factory = StreamingWriterFactory(dict_context)
        assert factory.get_writer("DELTA") is factory.get_writer("delta")

    def test_get_writer_lazy_caching(self, dict_context):
        factory = StreamingWriterFactory(dict_context)
        w1 = factory.get_writer("console")
        w2 = factory.get_writer("console")
        assert w1 is w2

    def test_get_writer_unsupported_format_raises(self, dict_context):
        factory = StreamingWriterFactory(dict_context)
        with pytest.raises(StreamingFormatNotSupportedError, match="not supported"):
            factory.get_writer("unsupported")

    def test_get_writer_empty_name_raises(self, dict_context):
        factory = StreamingWriterFactory(dict_context)
        with pytest.raises(StreamingError, match="non-empty string"):
            factory.get_writer("")

    def test_register_custom_writer_new_format(self, dict_context):
        class CustomWriter(BaseStreamingWriter):
            def write_stream(self, write_stream, config):
                return "custom"

        factory = StreamingWriterFactory(dict_context)
        factory.register_custom_writer("custom", CustomWriter)
        assert isinstance(factory.get_writer("custom"), CustomWriter)

    def test_register_custom_writer_rejects_non_subclass(self, dict_context):
        class NotAWriter:
            pass

        factory = StreamingWriterFactory(dict_context)
        with pytest.raises(StreamingError, match="must inherit"):
            factory.register_custom_writer("bad", NotAWriter)

    def test_register_custom_writer_invalidates_cache(self, dict_context):
        class WriterA(BaseStreamingWriter):
            def write_stream(self, write_stream, config):
                return "a"

        class WriterB(BaseStreamingWriter):
            def write_stream(self, write_stream, config):
                return "b"

        factory = StreamingWriterFactory(dict_context)
        factory.register_custom_writer("custom", WriterA)
        first = factory.get_writer("custom")
        factory.register_custom_writer("custom", WriterB)
        second = factory.get_writer("custom")
        assert isinstance(first, WriterA)
        assert isinstance(second, WriterB)
