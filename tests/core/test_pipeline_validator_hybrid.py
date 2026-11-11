"""``PipelineValidator.validate_hybrid_pipeline``: the check a hybrid run makes before it starts.

The node configs have the shapes the project compiler produces (see
``demo_ducta/projects/hybrid``): a batch node names catalog datasets
(``output: [key]``), a streaming node carries its connector inline.
"""

from __future__ import annotations

from typing import Any, Dict

from ducta.core.pipeline_validator import PipelineValidator
from ducta.setting.validators import FormatPolicy


def _batch(output: Any = None, **extra: Any) -> Dict[str, Any]:
    return {"input": {"raw": "seed.raw"}, "output": output or ["silver.x"], **extra}


def _stream(
    in_format: str = "file_stream",
    out: Any = None,
    checkpoint: bool = True,
    **extra: Any,
) -> Dict[str, Any]:
    cfg: Dict[str, Any] = {
        "type": "streaming",
        "input": {"format": in_format, "options": {"path": "landing/events"}},
        "output": out if out is not None else {"format": "delta", "path": "lake/gold/x"},
        **extra,
    }
    if checkpoint:
        cfg["streaming"] = {"checkpoint_location": "chk/x"}
    return cfg


def _validate(nodes: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    return PipelineValidator.validate_hybrid_pipeline({"nodes": list(nodes)}, nodes)


class TestClassification:
    def test_streaming_by_type_flag_or_input_format(self):
        nodes = {
            "b": _batch(),
            "by_type": _stream(),
            "by_flag": {"streaming": True, **_stream(), "type": ""},
            "by_format": {**_stream(), "type": ""},
        }
        result = _validate(nodes)
        assert result["batch_nodes"] == ["b"]
        assert result["streaming_nodes"] == ["by_type", "by_flag", "by_format"]

    def test_a_batch_input_map_with_a_format_parameter_stays_batch(self):
        """``{param: dataset}`` may name a parameter ``format``; its value is a dataset key."""
        result = _validate({"b": _batch(input={"format": "bronze.formats"})})
        assert result["batch_nodes"] == ["b"]
        assert result["is_valid"]

    def test_a_valid_hybrid_pipeline(self):
        nodes = {
            "clean": _batch(output={"format": "delta", "path": "lake/silver/x"}),
            "enrich": _stream(in_format="delta_stream", depends_on=["clean"]),
        }
        result = _validate(nodes)
        assert result["is_valid"], result["errors"]
        assert result["cross_dependencies"] == [
            {
                "streaming_node": "enrich",
                "batch_dependencies": ["clean"],
                "type": "streaming_depends_on_batch",
            }
        ]
        assert [i["severity"] for i in result["format_compatibility"]] == ["info"]


class TestCrossDependencies:
    def test_a_batch_node_cannot_wait_for_a_stream(self):
        nodes = {"s": _stream(), "b": _batch(depends_on=["s"])}
        result = _validate(nodes)
        assert not result["is_valid"]
        assert any("cannot depend on streaming nodes" in e for e in result["errors"])

    def test_the_batch_dependency_of_a_stream_must_declare_an_output(self):
        nodes = {"b": {"input": {"raw": "seed.raw"}}, "s": _stream(depends_on=["b"])}
        result = _validate(nodes)
        assert not result["is_valid"]
        assert any("must declare an output" in e for e in result["errors"])

    def test_a_catalog_output_counts_as_an_output(self):
        nodes = {"b": _batch(output=["silver.x"]), "s": _stream(depends_on=["b"])}
        assert _validate(nodes)["is_valid"]


class TestFormatCompatibility:
    def test_incompatible_formats_are_an_error(self):
        nodes = {
            "b": _batch(output={"format": "kafka", "options": {"topic": "t"}}),
            "s": _stream(in_format="file_stream", depends_on=["b"]),
        }
        result = _validate(nodes)
        assert not result["is_valid"]
        assert any("Incompatible formats" in e for e in result["errors"])
        # The whole issue stays under format_compatibility.
        assert result["format_compatibility"][0]["batch_format"] == "kafka"

    def test_format_names_are_case_insensitive(self):
        nodes = {
            "b": _batch(output={"format": "Parquet", "path": "landing/events"}),
            "s": _stream(in_format="FILE_STREAM", depends_on=["b"]),
        }
        nodes["s"]["input"]["format"] = "FILE_STREAM"
        issues = _validate(nodes)["format_compatibility"]
        assert [i["severity"] for i in issues] == ["info"]

    def test_a_file_stream_reading_another_path_is_a_warning(self):
        nodes = {
            "b": _batch(output={"format": "parquet", "path": "landing/other"}),
            "s": _stream(in_format="file_stream", depends_on=["b"]),
        }
        result = _validate(nodes)
        assert result["is_valid"]
        assert any("Path mismatch" in w for w in result["warnings"])


class TestResourceConflicts:
    def test_two_writers_of_one_path_or_topic_are_warned(self):
        nodes = {
            "b1": _batch(output={"format": "delta", "path": "lake/x"}),
            "b2": _batch(output={"format": "delta", "path": "lake/x"}),
            "k1": _batch(output={"format": "kafka", "options": {"topic": "t"}}),
            "k2": _batch(output={"format": "kafka", "options": {"topic": "t"}}),
            "s": _stream(
                in_format="kafka",
                out={"format": "delta", "path": "lake/x"},
            ),
        }
        nodes["s"]["input"]["options"] = {"topic": "t"}
        conflicts = _validate(nodes)["resource_conflicts"]
        assert any("batch nodes 'b1' and 'b2'" in c for c in conflicts)
        assert any("batch nodes 'k1' and 'k2'" in c for c in conflicts)
        assert any("streaming node 's' both write to 'lake/x'" in c for c in conflicts)
        assert any("streaming node 's' both use topic 't'" in c for c in conflicts)


class TestStreamingRequirements:
    def test_a_checkpointed_source_needs_a_checkpoint(self):
        result = _validate({"s": _stream(in_format="kafka", checkpoint=False)})
        assert any("must specify checkpoint_location" in e for e in result["errors"])

    def test_a_stream_needs_an_output_with_a_format(self):
        no_output = _validate({"s": _stream(out={})})
        assert any("must have output configuration" in e for e in no_output["errors"])
        no_format = _validate({"s": _stream(out={"path": "lake/x"})})
        assert any("must specify output format" in e for e in no_format["errors"])

    def test_an_unsupported_source_is_an_error(self):
        policy = FormatPolicy({"supported_inputs": ["kafka"]})
        nodes = {"s": _stream(in_format="kafka")}
        nodes["s"]["input"]["format"] = "rate"
        nodes["s"]["type"] = "streaming"
        result = PipelineValidator.validate_hybrid_pipeline({"nodes": ["s"]}, nodes, policy)
        assert any("invalid input format 'rate'" in e for e in result["errors"])


def test_an_unexpected_error_makes_the_pipeline_invalid():
    """The hybrid executor refuses to start on ``is_valid=False``: a crash must not pass."""
    result = PipelineValidator.validate_hybrid_pipeline({"nodes": [{"a": 1, "b": 2}]}, {})
    assert not result["is_valid"]
    assert result["errors"][0].startswith("Validation failed with error:")


def test_errors_and_warnings_are_messages():
    """A format issue was a dict among the strings: the run's error could not list them."""
    nodes = {
        "b": _batch(output={"format": "kafka", "path": "landing/other"}),
        "s": _stream(in_format="file_stream", depends_on=["b"]),
        "b2": _batch(output={"format": "parquet", "path": "landing/x"}),
        "s2": _stream(in_format="file_stream", depends_on=["b2"]),
    }
    result = _validate(nodes)
    assert result["errors"] and result["warnings"]
    assert all(isinstance(m, str) for m in result["errors"] + result["warnings"])


class TestHybridExecutorSaysWhy:
    """The run failed with "Hybrid pipeline validation failed" and nothing else."""

    def _executor(self, nodes):
        from unittest.mock import MagicMock

        from ducta.core.executors.hybrid import HybridExecutor

        executor = HybridExecutor.__new__(HybridExecutor)
        executor.node_executor = MagicMock()
        executor.streaming_manager = MagicMock(is_shut_down=False)
        executor.context = MagicMock(
            pipelines={"p": {"nodes": list(nodes)}},
            nodes_config=nodes,
            format_policy=FormatPolicy(),
        )
        return executor

    def test_the_error_lists_every_reason(self):
        nodes = {"s": _stream(in_format="kafka", checkpoint=False), "b": _batch(depends_on=["s"])}
        try:
            self._executor(nodes).execute("p")
        except ValueError as error:
            message = str(error)
        else:  # pragma: no cover - the assertion below reports it
            message = ""
        assert message.startswith("Hybrid pipeline 'p' is not valid:")
        assert "Batch node 'b' cannot depend on streaming nodes" in message
        assert "must specify checkpoint_location" in message
