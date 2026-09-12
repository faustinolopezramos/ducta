"""Unit tests for StreamingQueryManager's trigger config and query lifecycle
(create_and_start_query / stop_query). Complements test_query_manager.py, which
covers only the static checkpoint-path helpers.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ducta.stream.exceptions import (
    StreamingConfigurationError,
    StreamingError,
    StreamingQueryError,
    StreamingTimeoutError,
)
from ducta.stream.query_manager import StreamingQueryManager, TransformationRegistry


class TestConfigureTrigger:
    def _qm(self, obj_context):
        return StreamingQueryManager(obj_context)

    def test_processing_time_default(self, obj_context):
        qm = self._qm(obj_context)
        trigger = qm._configure_trigger({})
        assert trigger == {"processingTime": "10 seconds"}

    def test_processing_time_explicit_interval(self, obj_context):
        qm = self._qm(obj_context)
        trigger = qm._configure_trigger({"type": "processing_time", "interval": "30 seconds"})
        assert trigger == {"processingTime": "30 seconds"}

    def test_once_trigger(self, obj_context):
        qm = self._qm(obj_context)
        assert qm._configure_trigger({"type": "once"}) == {"once": True}

    def test_available_now_trigger(self, obj_context):
        qm = self._qm(obj_context)
        assert qm._configure_trigger({"type": "available_now"}) == {"availableNow": True}

    def test_continuous_trigger(self, obj_context):
        qm = self._qm(obj_context)
        trigger = qm._configure_trigger({"type": "continuous", "interval": "2 seconds"})
        assert trigger == {"continuous": "2 seconds"}

    def test_invalid_trigger_type_raises(self, obj_context):
        qm = self._qm(obj_context)
        with pytest.raises(StreamingConfigurationError, match="Invalid trigger type"):
            qm._configure_trigger({"type": "bogus"})

    def test_interval_below_minimum_raises(self, obj_context):
        qm = self._qm(obj_context)
        with pytest.raises(StreamingConfigurationError, match="below minimum"):
            qm._configure_trigger({"type": "processing_time", "interval": "500 milliseconds"})

    def test_adaptive_without_history_uses_base_interval(self, obj_context):
        qm = self._qm(obj_context)
        trigger = qm._configure_trigger({"type": "adaptive"})
        assert trigger == {"processingTime": "5 seconds"}

    def test_adaptive_with_history_computes_interval(self, obj_context):
        progress_sink = MagicMock()
        progress_sink.avg_trigger_ms.return_value = 2000.0  # 2s avg -> 1.5x = 3s target
        qm = StreamingQueryManager(obj_context, progress_sink=progress_sink)
        trigger = qm._configure_trigger({"type": "adaptive"}, query_name="q1")
        assert trigger["processingTime"] == "3.000 seconds"

    def test_adaptive_clamps_to_ceiling(self, obj_context):
        obj_context.global_config["streaming_adaptive_max_interval_seconds"] = 10.0
        progress_sink = MagicMock()
        progress_sink.avg_trigger_ms.return_value = 100_000.0  # way above ceiling
        qm = StreamingQueryManager(obj_context, progress_sink=progress_sink)
        trigger = qm._configure_trigger({"type": "adaptive"}, query_name="q1")
        assert trigger["processingTime"] == "10.000 seconds"


class TestCreateAndStartQuery:
    def _make_manager(self, obj_context, tmp_path, streaming_dataframe, mock_streaming_query):
        obj_context.global_config["checkpoints_base"] = str(tmp_path)
        qm = StreamingQueryManager(obj_context)
        qm.validator.validate_streaming_node_config = MagicMock()
        qm.reader_factory = MagicMock()
        qm.reader_factory.get_reader.return_value.read_stream.return_value = streaming_dataframe
        query_instance = mock_streaming_query(name="n1", query_id="id-1")
        qm.writer_factory = MagicMock()
        qm.writer_factory.get_writer.return_value.write_stream.return_value = query_instance
        return qm, query_instance

    def _node_config(self, name="n1"):
        return {
            "name": name,
            "input": {"format": "file_stream", "path": "/tmp/in"},
            "output": {"format": "console"},
        }

    def test_happy_path_returns_query_and_tracks_it(
        self, obj_context, tmp_path, streaming_dataframe, mock_streaming_query
    ):
        qm, query_instance = self._make_manager(
            obj_context, tmp_path, streaming_dataframe, mock_streaming_query
        )
        result = qm.create_and_start_query(self._node_config(), "exec1", "pipe1")
        assert result is query_instance
        assert "pipe1:exec1:n1" in qm._active_queries

    def test_missing_input_config_raises(
        self, obj_context, tmp_path, streaming_dataframe, mock_streaming_query
    ):
        qm, _ = self._make_manager(obj_context, tmp_path, streaming_dataframe, mock_streaming_query)
        with pytest.raises(StreamingError):
            qm.create_and_start_query(
                {"name": "n1", "output": {"format": "console"}}, "exec1", "pipe1"
            )

    def test_missing_output_config_raises(
        self, obj_context, tmp_path, streaming_dataframe, mock_streaming_query
    ):
        qm, _ = self._make_manager(obj_context, tmp_path, streaming_dataframe, mock_streaming_query)
        with pytest.raises(StreamingError):
            qm.create_and_start_query(
                {"name": "n1", "input": {"format": "file_stream", "path": "/tmp/in"}},
                "exec1",
                "pipe1",
            )

    def test_duplicate_checkpoint_raises_on_second_call(
        self, obj_context, tmp_path, streaming_dataframe, mock_streaming_query
    ):
        qm, _ = self._make_manager(obj_context, tmp_path, streaming_dataframe, mock_streaming_query)
        node_config = self._node_config()
        qm.create_and_start_query(node_config, "exec1", "pipe1")
        with pytest.raises(StreamingError):
            qm.create_and_start_query(node_config, "exec1", "pipe1")

    def test_transformation_applied(
        self, obj_context, tmp_path, streaming_dataframe, mock_streaming_query
    ):
        qm, _ = self._make_manager(obj_context, tmp_path, streaming_dataframe, mock_streaming_query)
        # Register a transform that returns a recognizable DataFrame-like object.
        from pyspark.sql import DataFrame as SparkDataFrame

        transformed_df = MagicMock(spec=SparkDataFrame)
        transformed_df.writeStream = streaming_dataframe.writeStream

        def _transform(df):
            return transformed_df

        qm.transformation_registry.register("double_it", _transform)
        node_config = self._node_config()
        node_config["function"] = {"key": "double_it"}
        result = qm.create_and_start_query(node_config, "exec2", "pipe1")
        assert result is not None

    def test_transformation_wrong_return_type_raises(
        self, obj_context, tmp_path, streaming_dataframe, mock_streaming_query
    ):
        qm, _ = self._make_manager(obj_context, tmp_path, streaming_dataframe, mock_streaming_query)

        def _bad_transform(df):
            return "not-a-dataframe"

        qm.transformation_registry.register("bad", _bad_transform)
        node_config = self._node_config()
        node_config["function"] = {"key": "bad"}
        with pytest.raises(StreamingError):
            qm.create_and_start_query(node_config, "exec3", "pipe1")

    def test_unregistered_transformation_raises(
        self, obj_context, tmp_path, streaming_dataframe, mock_streaming_query
    ):
        qm, _ = self._make_manager(obj_context, tmp_path, streaming_dataframe, mock_streaming_query)
        node_config = self._node_config()
        node_config["function"] = {"key": "ghost"}
        with pytest.raises(StreamingError):
            qm.create_and_start_query(node_config, "exec4", "pipe1")


class TestWatermarkResolution:
    """Regression: docs/streaming.rst documents watermark under node.streaming.watermark,
    but the code used to only ever read node.input.watermark. Both locations must
    now work, with streaming.watermark (documented) taking precedence."""

    def _make_manager(self, obj_context, tmp_path, streaming_dataframe, mock_streaming_query):
        obj_context.global_config["checkpoints_base"] = str(tmp_path)
        qm = StreamingQueryManager(obj_context)
        qm.validator.validate_streaming_node_config = MagicMock()
        qm.reader_factory = MagicMock()
        qm.reader_factory.get_reader.return_value.read_stream.return_value = streaming_dataframe
        query_instance = mock_streaming_query(name="n1", query_id="id-1")
        qm.writer_factory = MagicMock()
        qm.writer_factory.get_writer.return_value.write_stream.return_value = query_instance
        return qm

    def test_legacy_input_watermark_still_applied(
        self, obj_context, tmp_path, streaming_dataframe, mock_streaming_query
    ):
        qm = self._make_manager(obj_context, tmp_path, streaming_dataframe, mock_streaming_query)
        node_config = {
            "name": "n1",
            "input": {
                "format": "file_stream",
                "path": "/tmp/in",
                "watermark": {"column": "event_time", "delay": "10 seconds"},
            },
            "output": {"format": "console"},
        }
        qm.create_and_start_query(node_config, "exec1", "pipe1")
        streaming_dataframe.withWatermark.assert_called_once_with("event_time", "10 seconds")

    def test_streaming_watermark_applied_when_input_watermark_absent(
        self, obj_context, tmp_path, streaming_dataframe, mock_streaming_query
    ):
        qm = self._make_manager(obj_context, tmp_path, streaming_dataframe, mock_streaming_query)
        node_config = {
            "name": "n1",
            "input": {"format": "file_stream", "path": "/tmp/in"},
            "output": {"format": "console"},
            "streaming": {"watermark": {"column": "event_time", "delay": "5 minutes"}},
        }
        qm.create_and_start_query(node_config, "exec1", "pipe1")
        streaming_dataframe.withWatermark.assert_called_once_with("event_time", "5 minutes")

    def test_streaming_watermark_takes_precedence_over_input_watermark(
        self, obj_context, tmp_path, streaming_dataframe, mock_streaming_query
    ):
        qm = self._make_manager(obj_context, tmp_path, streaming_dataframe, mock_streaming_query)
        node_config = {
            "name": "n1",
            "input": {
                "format": "file_stream",
                "path": "/tmp/in",
                "watermark": {"column": "event_time", "delay": "1 hour"},
            },
            "output": {"format": "console"},
            "streaming": {"watermark": {"column": "event_time", "delay": "5 minutes"}},
        }
        qm.create_and_start_query(node_config, "exec1", "pipe1")
        streaming_dataframe.withWatermark.assert_called_once_with("event_time", "5 minutes")


class TestStopQuery:
    def _qm(self, obj_context):
        return StreamingQueryManager(obj_context)

    def test_already_inactive_returns_true(self, obj_context, mock_streaming_query):
        qm = self._qm(obj_context)
        query = mock_streaming_query(active=False)
        assert qm.stop_query(query) is True

    def test_graceful_stop_success(self, obj_context, mock_streaming_query):
        qm = self._qm(obj_context)
        query = mock_streaming_query(active=True)
        assert qm.stop_query(query, graceful=True, timeout_seconds=5.0) is True
        assert query.isActive() is False

    def test_non_graceful_stop_does_not_wait(self, obj_context, mock_streaming_query):
        qm = self._qm(obj_context)
        query = mock_streaming_query(active=True)
        assert qm.stop_query(query, graceful=False) is True

    def test_timeout_raises_streaming_query_error_wrapping_timeout(self, obj_context):
        qm = self._qm(obj_context)

        class _StuckQuery:
            def isActive(self):
                return True

            def stop(self):
                pass  # never actually stops

            def awaitTermination(self, timeout=None):
                return False

        with pytest.raises(StreamingQueryError):
            qm.stop_query(_StuckQuery(), graceful=True, timeout_seconds=0.01)

    def test_stop_removes_from_active_queries(
        self, obj_context, tmp_path, streaming_dataframe, mock_streaming_query
    ):
        obj_context.global_config["checkpoints_base"] = str(tmp_path)
        qm = StreamingQueryManager(obj_context)
        qm.validator.validate_streaming_node_config = MagicMock()
        qm.reader_factory = MagicMock()
        qm.reader_factory.get_reader.return_value.read_stream.return_value = streaming_dataframe
        query_instance = mock_streaming_query(name="n1", query_id="id-1")
        qm.writer_factory = MagicMock()
        qm.writer_factory.get_writer.return_value.write_stream.return_value = query_instance

        node_config = {
            "name": "n1",
            "input": {"format": "file_stream", "path": "/tmp/in"},
            "output": {"format": "console"},
        }
        qm.create_and_start_query(node_config, "exec1", "pipe1")
        assert "pipe1:exec1:n1" in qm._active_queries

        qm.stop_query(query_instance)
        assert "pipe1:exec1:n1" not in qm._active_queries


class TestTransformationRegistryIsolation:
    def test_instances_are_isolated(self):
        r1 = TransformationRegistry()
        r2 = TransformationRegistry()
        r1.register("k", lambda df: df)
        assert r2.list_transformations() == []

    def test_register_requires_non_empty_key(self):
        r = TransformationRegistry()
        with pytest.raises(ValueError):
            r.register("", lambda df: df)

    def test_register_requires_callable(self):
        r = TransformationRegistry()
        with pytest.raises(TypeError):
            r.register("k", "not-callable")

    def test_unregister_returns_true_if_existed(self):
        r = TransformationRegistry()
        r.register("k", lambda df: df)
        assert r.unregister("k") is True
        assert r.unregister("k") is False

    def test_get_missing_raises_value_error(self):
        r = TransformationRegistry()
        with pytest.raises(ValueError, match="not registered"):
            r.get("missing")


class TestTransformationRegistryGlobalFallback:
    """_get_registered_transformation's docstring promises falling back to the
    process-wide (class-level) registry when a key isn't found locally — this
    verifies that fallback actually happens."""

    def test_falls_back_to_class_registry(self, obj_context):
        key = "global_only_fn_for_test"
        TransformationRegistry.class_register(key, lambda df: df)
        try:
            qm = StreamingQueryManager(obj_context)
            # Not registered on this instance's local registry...
            assert key not in qm.transformation_registry.list_transformations()
            # ...but still resolves via the global fallback.
            resolved = qm._get_registered_transformation(key)
            assert callable(resolved)
        finally:
            TransformationRegistry.class_unregister(key)

    def test_missing_everywhere_lists_both_registries_in_error(self, obj_context):
        qm = StreamingQueryManager(obj_context)
        qm.transformation_registry.register("local_fn", lambda df: df)
        TransformationRegistry.class_register("global_fn", lambda df: df)
        try:
            with pytest.raises(StreamingConfigurationError) as exc_info:
                qm._get_registered_transformation("missing_everywhere")
            message = str(exc_info.value)
            assert "local_fn" in message
            assert "global_fn" in message
        finally:
            TransformationRegistry.class_unregister("global_fn")
