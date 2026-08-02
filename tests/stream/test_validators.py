"""Unit tests for ducta.stream.validators.StreamingValidator: topological_sort
and output-config validation."""

from __future__ import annotations

import pytest

from ducta.stream.exceptions import StreamingValidationError
from ducta.stream.validators import StreamingValidator


@pytest.fixture
def validator():
    return StreamingValidator()


class TestValidateStreamingOutputConfig:
    def test_valid_console_output_passes(self, validator):
        validator.validate_streaming_node_config(
            {
                "name": "n1",
                "input": {"format": "file_stream", "path": "/tmp/in"},
                "output": {"format": "console"},
            }
        )

    def test_reserved_trigger_key_under_output_is_rejected(self, validator):
        # Regression: trigger/outputMode/checkpointLocation/queryName belong
        # under streaming.*, not output.* — StreamingQueryManager already sets
        # them on the write_stream before the writer runs, so allowing them
        # here would apply them a second time and can trip a confusing Spark
        # "multiple streaming triggers" error instead of a clear config error.
        with pytest.raises(StreamingValidationError, match="trigger"):
            validator.validate_streaming_node_config(
                {
                    "name": "n1",
                    "input": {"format": "file_stream", "path": "/tmp/in"},
                    "output": {"format": "console", "trigger": {"once": True}},
                }
            )

    def test_reserved_query_name_key_under_output_is_rejected(self, validator):
        with pytest.raises(StreamingValidationError, match="queryName"):
            validator.validate_streaming_node_config(
                {
                    "name": "n1",
                    "input": {"format": "file_stream", "path": "/tmp/in"},
                    "output": {"format": "console", "queryName": "my_query"},
                }
            )


class TestValidateStreamingConfig:
    def test_streaming_watermark_valid_passes(self, validator):
        validator.validate_streaming_node_config(
            {
                "name": "n1",
                "input": {"format": "file_stream", "path": "/tmp/in"},
                "output": {"format": "console"},
                "streaming": {"watermark": {"column": "event_time", "delay": "10 seconds"}},
            }
        )

    def test_streaming_watermark_missing_column_rejected(self, validator):
        # Regression: docs/streaming.rst documents watermark under
        # streaming.watermark; it must be validated there too, not just under
        # the legacy input.watermark location.
        with pytest.raises(StreamingValidationError, match="streaming.watermark.column"):
            validator.validate_streaming_node_config(
                {
                    "name": "n1",
                    "input": {"format": "file_stream", "path": "/tmp/in"},
                    "output": {"format": "console"},
                    "streaming": {"watermark": {"delay": "10 seconds"}},
                }
            )

    def test_input_watermark_still_validated(self, validator):
        # Legacy location keeps working and keeps its own field prefix.
        with pytest.raises(StreamingValidationError, match="input.watermark.column"):
            validator.validate_streaming_node_config(
                {
                    "name": "n1",
                    "input": {
                        "format": "file_stream",
                        "path": "/tmp/in",
                        "watermark": {"delay": "10 seconds"},
                    },
                    "output": {"format": "console"},
                }
            )

    def test_trigger_without_type_defaults_to_processing_time(self, validator):
        # Regression: TriggerScheduler already defaults a missing trigger.type
        # to processing_time; the validator must not be stricter than the
        # runtime it's meant to gate.
        validator.validate_streaming_node_config(
            {
                "name": "n1",
                "input": {"format": "file_stream", "path": "/tmp/in"},
                "output": {"format": "console"},
                "streaming": {"trigger": {"interval": "30 seconds"}},
            }
        )

    def test_trigger_without_type_or_interval_still_requires_interval(self, validator):
        # Defaulting the type doesn't waive the interval requirement that
        # comes with it. A non-empty trigger dict (so it isn't skipped as
        # "no trigger configured") without type or interval must still fail.
        with pytest.raises(StreamingValidationError, match="requires 'interval'"):
            validator.validate_streaming_node_config(
                {
                    "name": "n1",
                    "input": {"format": "file_stream", "path": "/tmp/in"},
                    "output": {"format": "console"},
                    "streaming": {"trigger": {"unrelated": True}},
                }
            )


class TestTopologicalSort:
    def test_orders_by_depends_on(self, validator):
        nodes = {"a": {}, "b": {"depends_on": ["a"]}, "c": {"depends_on": ["b"]}}
        order = validator.topological_sort(nodes)
        assert order.index("a") < order.index("b") < order.index("c")

    def test_independent_nodes_all_present(self, validator):
        nodes = {"a": {}, "b": {}, "c": {}}
        assert set(validator.topological_sort(nodes)) == {"a", "b", "c"}

    def test_cycle_raises(self, validator):
        nodes = {"a": {"depends_on": ["b"]}, "b": {"depends_on": ["a"]}}
        with pytest.raises(StreamingValidationError, match="Circular dependency"):
            validator.topological_sort(nodes)

    def test_undefined_dependency_raises(self, validator):
        nodes = {"a": {"depends_on": ["ghost"]}}
        with pytest.raises(StreamingValidationError, match="undefined node"):
            validator.topological_sort(nodes)
