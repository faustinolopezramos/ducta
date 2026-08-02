from unittest.mock import MagicMock

import pytest
from loguru import logger

from ducta.setting.exceptions import ConfigValidationError, PipelineValidationError
from ducta.setting.validators import (
    ConfigValidator,
    CrossValidator,
    FormatPolicy,
    HybridValidator,
    MLValidator,
    PipelineValidator,
    SpecializedValidator,
    StreamingValidator,
)


class TestConfigValidator:
    def test_validate_required_keys_passes(self):
        ConfigValidator.validate_required_keys({"a": 1, "b": 2}, ["a", "b"])

    def test_validate_required_keys_fails(self):
        with pytest.raises(ConfigValidationError, match="Missing required keys"):
            ConfigValidator.validate_required_keys({"a": 1}, ["a", "b"])

    def test_validate_type_passes(self):
        ConfigValidator.validate_type({"a": 1}, dict)

    def test_validate_type_fails(self):
        with pytest.raises(ConfigValidationError, match="must be of type"):
            ConfigValidator.validate_type("string", dict)


class TestPipelineValidator:
    def test_validate_pipeline_nodes_passes(self):
        pipelines = {"p1": {"nodes": ["n1", "n2"]}}
        nodes = {"n1": {}, "n2": {}}
        PipelineValidator.validate_pipeline_nodes(pipelines, nodes)

    def test_validate_pipeline_nodes_missing(self):
        pipelines = {"p1": {"nodes": ["n1", "n2"]}}
        nodes = {"n1": {}}
        with pytest.raises(PipelineValidationError, match="Missing nodes"):
            PipelineValidator.validate_pipeline_nodes(pipelines, nodes)

    def test_validate_pipeline_nodes_empty(self):
        pipelines = {"p1": {"nodes": ["n1"]}}
        nodes = {"n1": None}
        with pytest.raises(PipelineValidationError, match="empty content"):
            PipelineValidator.validate_pipeline_nodes(pipelines, nodes)

    def test_validate_pipeline_dependency_graph_no_import_error(self):
        pipelines = {"p1": {"nodes": []}}
        PipelineValidator.validate_pipeline_dependency_graph(pipelines)

    def test_validate_pipeline_dependency_graph_with_nodes(self):
        pipelines = {"p1": {"nodes": ["n1"]}}
        nodes = {"n1": {}}
        PipelineValidator.validate_pipeline_dependency_graph(pipelines, nodes)


class TestFormatPolicy:
    def test_default_supported_inputs(self):
        policy = FormatPolicy()
        assert policy.is_supported_input("kafka") is True
        assert policy.is_supported_input("parquet") is False
        assert policy.is_supported_input(None) is False
        assert policy.is_supported_input("") is False

    def test_default_supported_outputs(self):
        policy = FormatPolicy()
        assert policy.is_supported_output("kafka") is True
        assert policy.is_supported_output("delta") is True
        assert policy.is_supported_output("parquet") is True
        assert policy.is_supported_output("oracle") is False

    def test_are_compatible(self):
        policy = FormatPolicy()
        assert policy.are_compatible("parquet", "file_stream") is True
        assert policy.are_compatible("kafka", "kafka") is True
        assert policy.are_compatible("parquet", "kafka") is False
        assert policy.are_compatible(None, "file_stream") is False

    def test_overrides(self):
        overrides = {
            "supported_inputs": ["custom_input"],
            "supported_outputs": ["custom_output"],
            "compatibility_map": {"custom": ["custom"]},
            "checkpoint_required_inputs": ["custom_cp"],
        }
        policy = FormatPolicy(overrides)
        assert policy.is_supported_input("custom_input") is True
        assert policy.is_supported_input("kafka") is False
        assert policy.is_supported_output("custom_output") is True
        assert policy.are_compatible("custom", "custom") is True

    def test_get_supported_formats(self):
        policy = FormatPolicy()
        assert "kafka" in policy.get_supported_input_formats()
        assert "kafka" in policy.get_supported_output_formats()


class TestSpecializedValidator:
    def test_assert_node_exists_passes(self):
        SpecializedValidator._assert_node_exists("n1", "p1", {"n1": {}})

    def test_assert_node_exists_fails(self):
        with pytest.raises(ConfigValidationError, match="not defined"):
            SpecializedValidator._assert_node_exists("n1", "p1", {})

    def test_raise_or_warn_strict(self):
        with pytest.raises(ConfigValidationError, match="test error"):
            SpecializedValidator._raise_or_warn("test error", strict=True)

    def test_raise_or_warn_non_strict(self):
        SpecializedValidator._raise_or_warn("test warning", strict=False)

    def test_validate_required_fields_passes(self):
        v = SpecializedValidator()
        v.REQUIRED_NODE_FIELDS = []
        v._validate_required_fields({"a": 1}, "node1")

    def test_validate_required_fields_missing(self):
        v = SpecializedValidator()
        v.REQUIRED_NODE_FIELDS = ["req_field"]
        with pytest.raises(ConfigValidationError, match="missing required fields"):
            v._validate_required_fields({}, "node1")

    def test_validate_model_type_no_model(self):
        v = SpecializedValidator()
        v.SUPPORTED_MODEL_TYPES = ["spark_ml"]
        v._validate_model_type({}, "node1")

    def test_validate_model_type_unsupported(self):
        v = SpecializedValidator()
        v.SUPPORTED_MODEL_TYPES = ["spark_ml"]
        with pytest.raises(ConfigValidationError, match="unsupported model type"):
            v._validate_model_type({"model": {"type": "pytorch"}}, "node1")

    def test_validate_model_type_supported(self):
        v = SpecializedValidator()
        v.SUPPORTED_MODEL_TYPES = ["spark_ml"]
        v._validate_model_type({"model": {"type": "spark_ml"}}, "node1")

    def test_validate_hyperparams_invalid(self):
        v = SpecializedValidator()
        with pytest.raises(ConfigValidationError, match="invalid hyperparams"):
            v._validate_hyperparams({"hyperparams": "not_dict"}, "node1")

    def test_validate_metrics_invalid(self):
        v = SpecializedValidator()
        with pytest.raises(ConfigValidationError, match="invalid metrics"):
            v._validate_metrics({"metrics": "not_list"}, "node1")


class TestMLValidator:
    def test_validate_ml_pipeline_config(self):
        v = MLValidator()
        pipelines = {"p1": {"nodes": ["n1"]}}
        nodes = {"n1": {"model": {"type": "spark_ml"}, "input": ["ds1"], "output": ["ds_out"]}}
        v.validate_ml_pipeline_config(pipelines, nodes, strict=False)

    def test_validate_ml_pipeline_config_missing_node(self):
        v = MLValidator()
        pipelines = {"p1": {"nodes": ["n1"]}}
        with pytest.raises(ConfigValidationError, match="not defined"):
            v.validate_ml_pipeline_config(pipelines, {}, strict=True)

    def test_validate_pipeline_compatibility_no_warnings(self):
        v = MLValidator()
        batch = {"nodes": ["n1"]}
        ml = {"nodes": ["n2"]}
        warnings = v.validate_pipeline_compatibility(batch, ml, {"n1": {}, "n2": {"model": {}}})
        assert warnings == []

    def test_validate_pipeline_compatibility_with_warnings(self):
        v = MLValidator()
        batch = {"nodes": ["n1"]}
        ml = {"nodes": ["n1"]}
        nodes = {"n1": {"model": {"type": "spark_ml"}, "output": {"format": "oracle"}}}
        warnings = v.validate_pipeline_compatibility(batch, ml, nodes)
        assert any("model" in w for w in warnings)

    def test_validate_spark_ml_config_empty(self):
        v = MLValidator()
        v._validate_spark_ml_config({}, strict=False)

    def test_validate_spark_ml_config_present(self):
        v = MLValidator()
        v._validate_spark_ml_config(
            {
                "spark.ml.pipeline.cacheStorageLevel": "MEMORY_ONLY",
                "spark.ml.feature.pipeline.enabled": "true",
            },
            strict=True,
        )

    def test_validate_spark_ml_config_missing_non_strict(self):
        v = MLValidator()
        v._validate_spark_ml_config({"some_config": "val"}, strict=False)

    def test_validate_spark_ml_config_missing_strict(self):
        v = MLValidator()
        with pytest.raises(ConfigValidationError, match="Missing required Spark ML config"):
            v._validate_spark_ml_config({"some_config": "val"}, strict=True)


class TestStreamingValidator:
    def test_validate_pipeline_config_empty(self):
        v = StreamingValidator()
        v.validate_streaming_pipeline_config({"name": "p1", "spark_config": {}}, strict=False)

    def test_validate_pipeline_config_legacy_spark(self):
        v = StreamingValidator()
        with pytest.raises(ConfigValidationError, match="legacy Spark Streaming"):
            v.validate_streaming_pipeline_config(
                {"spark_config": {"spark.streaming.xxx": "val"}}, strict=True
            )

    def test_validate_pipeline_with_nodes(self):
        v = StreamingValidator()
        v.validate_streaming_pipeline_with_nodes(
            {"name": "p1", "nodes": ["n1"]},
            {"n1": {"input": {"format": "kafka"}, "output": {"format": "delta"}}},
            strict=False,
        )

    def test_validate_pipeline_with_nodes_missing(self):
        v = StreamingValidator()
        with pytest.raises(ConfigValidationError, match="not defined"):
            v.validate_streaming_pipeline_with_nodes(
                {"name": "p1", "nodes": ["n1"]}, {}, strict=True
            )

    def test_validate_node_formats_unsupported_input(self):
        v = StreamingValidator()
        with pytest.raises(ConfigValidationError, match="unsupported streaming input"):
            v._validate_node_formats(
                {"input": {"format": "oracle"}, "output": {}}, "n1", strict=True
            )

    def test_validate_node_formats_unsupported_output(self):
        v = StreamingValidator()
        with pytest.raises(ConfigValidationError, match="unsupported streaming output"):
            v._validate_node_formats(
                {"input": {}, "output": {"format": "oracle"}}, "n1", strict=True
            )

    def test_validate_node_formats_passes(self):
        v = StreamingValidator()
        v._validate_node_formats(
            {"input": {"format": "kafka"}, "output": {"format": "delta"}}, "n1", strict=True
        )

    def test_validate_pipeline_compatibility(self):
        v = StreamingValidator()
        batch = {"nodes": ["n1"]}
        streaming = {"nodes": ["n1"]}
        nodes = {"n1": {"output": {"format": "oracle"}}}
        warnings = v.validate_pipeline_compatibility(batch, streaming, nodes)
        assert len(warnings) >= 1


class TestCrossValidator:
    def test_get_node_type_ml(self):
        assert CrossValidator._get_node_type({"model": {}}) == "ml"

    def test_get_node_type_streaming(self):
        assert CrossValidator._get_node_type({"input": {"format": "kafka"}}) == "streaming"

    def test_get_node_type_batch(self):
        assert CrossValidator._get_node_type({}) == "batch"

    def test_check_ml_node_dependency_non_streaming_dep(self):
        errors = []
        CrossValidator._check_ml_node_dependency(
            "ml_node", "batch_node", {"output": {"format": "csv"}}, errors
        )
        assert errors == []

    def test_check_ml_node_dependency_streaming_invalid(self):
        errors = []
        CrossValidator._check_ml_node_dependency(
            "ml_node",
            "str_node",
            {"input": {"format": "kafka"}, "output": {"format": "csv"}},
            errors,
        )
        assert len(errors) >= 1

    def test_check_ml_node_dependency_streaming_valid(self):
        errors = []
        CrossValidator._check_ml_node_dependency(
            "ml_node",
            "str_node",
            {"input": {"format": "kafka"}, "output": {"format": "delta"}},
            errors,
        )
        assert errors == []

    def test_check_streaming_node_dependency_invalid(self):
        errors = []
        CrossValidator._check_streaming_node_dependency(
            "str_node", "ml_node", {"model": {"type": "pytorch"}}, errors
        )
        assert len(errors) >= 1

    def test_check_streaming_node_dependency_valid(self):
        errors = []
        CrossValidator._check_streaming_node_dependency(
            "str_node", "ml_node", {"model": {"type": "spark_ml"}}, errors
        )
        assert errors == []

    def test_validate_hybrid_dependencies_passes(self):
        CrossValidator.validate_hybrid_dependencies({"n1": {"model": {}}})

    def test_validate_hybrid_dependencies_fails(self):
        nodes = {
            "ml_node": {"model": {}, "dependencies": ["str_node"]},
            "str_node": {"input": {"format": "kafka"}, "output": {"format": "csv"}},
        }
        with pytest.raises(ConfigValidationError):
            CrossValidator.validate_hybrid_dependencies(nodes)


class TestHybridValidator:
    def test_validate_context_no_pipelines(self):
        ctx = MagicMock()
        ctx.nodes_config = {}
        ctx.get_pipelines_by_type.return_value = {}
        HybridValidator.validate_context(ctx)

    def test_validate_context_passes(self):
        ctx = MagicMock()
        ctx.nodes_config = {
            "n1": {"input": {"format": "kafka"}},
            "n2": {"model": {}},
        }
        ctx.get_pipelines_by_type.return_value = {}
        streaming_ctx = MagicMock()
        streaming_ctx._is_compatible_node.side_effect = lambda c: bool(c.get("input"))
        ml_ctx = MagicMock()
        ml_ctx._is_compatible_node.side_effect = lambda c: "model" in c
        HybridValidator.validate_context(ctx, streaming_ctx, ml_ctx)
