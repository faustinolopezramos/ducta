"""Tests for pipeline/node spec validation on write.

`PUT /projects/{id}/pipelines/{name}` wrote whatever JSON body it was given
straight into `pipelines.yaml`, and `PUT /nodes/{name}` did the same for
`nodes.yaml` — the routes caught a `ConfigValidationError` that nothing could
raise. These pin down what is now rejected, and just as importantly what must
still be accepted: an empty node list (a pipeline under construction) and
unknown keys (the YAML editor round-trip must be lossless).
"""

from __future__ import annotations

import pytest

from ducta.api.exceptions import ConfigValidationError
from ducta.api.models.spec import (
    NodeSpec,
    PipelineSpec,
    validate_node_spec,
    validate_pipeline_spec,
)


class TestPipelineSpecAcceptsLegitimateSpecs:
    def test_an_empty_node_list_is_allowed(self):
        """The UI creates a pipeline before it has any nodes."""
        validate_pipeline_spec("p", {"nodes": [], "type": "batch", "active": True})

    def test_each_runtime_type_is_allowed(self):
        for kind in ("batch", "ml", "streaming", "hybrid"):
            validate_pipeline_spec("p", {"type": kind, "nodes": ["a"]})

    def test_a_missing_type_defaults_rather_than_failing(self):
        validate_pipeline_spec("p", {"nodes": ["a"]})

    def test_node_entries_may_be_objects(self):
        """Hand-edited YAML carries `{key, module}` entries in some layouts."""
        validate_pipeline_spec("p", {"nodes": [{"key": "a", "module": "m"}]})


class TestPipelineSpecRejectsGarbage:
    def test_an_unknown_type_is_rejected(self):
        with pytest.raises(ConfigValidationError, match="Invalid pipeline type 'sql'"):
            validate_pipeline_spec("p", {"type": "sql", "nodes": ["a"]})

    def test_a_scalar_node_list_is_rejected(self):
        with pytest.raises(ConfigValidationError, match="nodes"):
            validate_pipeline_spec("p", {"type": "batch", "nodes": "a"})

    def test_a_non_mapping_spec_is_rejected(self):
        with pytest.raises(ConfigValidationError, match="must be a mapping"):
            validate_pipeline_spec("p", ["not", "a", "dict"])

    def test_a_scalar_depends_on_is_rejected(self):
        with pytest.raises(ConfigValidationError, match="depends_on"):
            validate_pipeline_spec("p", {"nodes": ["a"], "depends_on": 3})


class TestPipelineSpecRoundTripsUnknownKeys:
    def test_unknown_keys_survive_validation(self):
        spec = {"type": "batch", "nodes": ["a"], "team_owner": "data-platform"}
        validate_pipeline_spec("p", spec)
        assert PipelineSpec.model_validate(spec).model_dump()["team_owner"] == "data-platform"

    def test_the_original_dict_is_not_mutated(self):
        spec = {"nodes": ["a"]}
        validate_pipeline_spec("p", spec)
        assert spec == {"nodes": ["a"]}


class TestNodeSpecAcceptsLegitimateSpecs:
    def test_a_module_plus_function_is_allowed(self):
        validate_node_spec("n", {"module": "src.foo", "function": "run"})

    def test_a_fully_qualified_function_needs_no_module(self):
        validate_node_spec("n", {"function": "pkg.mod.run"})

    def test_a_streaming_function_object_is_allowed(self):
        validate_node_spec("n", {"function": {"key": "clean", "module": "pipelines.stream"}})

    def test_the_minimal_payload_the_ui_sends_is_allowed(self):
        validate_node_spec("n", {"module": "src.foo", "type": "batch"})

    def test_quality_blocks_are_allowed(self):
        validate_node_spec(
            "n",
            {
                "module": "m",
                "function": "run",
                "data_quality": {
                    "enabled": True,
                    "checks": {"not_null": {"enabled": True}},
                    "quality_gate": {"enabled": True, "behavior": "skip_downstream"},
                },
            },
        )


class TestNodeSpecRejectsGarbage:
    def test_an_unaddressable_function_is_rejected(self):
        with pytest.raises(ConfigValidationError, match="not addressable"):
            validate_node_spec("n", {"function": "run"})

    def test_retry_above_the_cap_is_rejected(self):
        with pytest.raises(ConfigValidationError, match="retry"):
            validate_node_spec("n", {"module": "m", "retry": 99})

    def test_a_negative_retry_is_rejected(self):
        with pytest.raises(ConfigValidationError, match="retry"):
            validate_node_spec("n", {"module": "m", "retry": -1})

    def test_an_unknown_ml_stage_is_rejected(self):
        with pytest.raises(ConfigValidationError, match="Invalid ml_stage"):
            validate_node_spec("n", {"module": "m", "ml_stage": "bogus"})

    def test_a_zero_timeout_is_rejected(self):
        with pytest.raises(ConfigValidationError, match="timeout"):
            validate_node_spec("n", {"module": "m", "timeout": 0})

    def test_a_non_mapping_spec_is_rejected(self):
        with pytest.raises(ConfigValidationError, match="must be a mapping"):
            validate_node_spec("n", ["nope"])


class TestNodeSpecRoundTripsUnknownKeys:
    def test_unknown_keys_survive_validation(self):
        spec = {"module": "m", "function": "run", "custom_hint": {"a": 1}}
        validate_node_spec("n", spec)
        assert NodeSpec.model_validate(spec).model_dump()["custom_hint"] == {"a": 1}
