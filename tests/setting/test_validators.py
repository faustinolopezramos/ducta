from unittest.mock import MagicMock

import pytest
from loguru import logger

from ducta.setting.exceptions import ConfigValidationError, PipelineValidationError
from ducta.setting.validators import (
    ConfigValidator,
    FormatPolicy,
    PipelineValidator,
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
