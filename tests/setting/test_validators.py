from unittest.mock import MagicMock

import pytest
from loguru import logger

from ducta.setting.exceptions import ConfigValidationError, PipelineValidationError
from ducta.setting.validators import (
    ConfigValidator,
    CrossValidator,
    FormatPolicy,
    PipelineValidator,
    SpecializedValidator,
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
