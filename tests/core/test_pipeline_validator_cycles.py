"""Regression test: PipelineValidator.validate_no_dag_cycles must catch cycles
created purely by dataset-inferred dependencies, not just explicit ones.

Before the fix, this validator only built its graph from explicit
`dependencies:` entries, while the real executor (DependencyResolver.
build_dependency_graph) merges explicit ∪ dataset-inferred edges. Two nodes
with no `dependencies:` field that reference each other's datasets via
input/output formed a cycle invisible to preflight, failing only once the
pipeline actually started.
"""

from __future__ import annotations

import pytest

from ducta.core.pipeline_validator import PipelineValidator


class TestInferredCycleDetection:
    def test_pure_inference_cycle_is_caught(self):
        node_configs = {
            "node_a": {"input": ["ds_b"], "output": ["ds_a"]},
            "node_b": {"input": ["ds_a"], "output": ["ds_b"]},
        }
        with pytest.raises(ValueError, match="Circular dependency"):
            PipelineValidator.validate_no_dag_cycles(["node_a", "node_b"], node_configs)

    def test_explicit_cycle_is_still_caught(self):
        node_configs = {
            "node_a": {"dependencies": ["node_b"]},
            "node_b": {"dependencies": ["node_a"]},
        }
        with pytest.raises(ValueError, match="Circular dependency"):
            PipelineValidator.validate_no_dag_cycles(["node_a", "node_b"], node_configs)

    def test_acyclic_inferred_graph_passes(self):
        node_configs = {
            "node_a": {"output": ["ds_a"]},
            "node_b": {"input": ["ds_a"], "output": ["ds_b"]},
        }
        PipelineValidator.validate_no_dag_cycles(["node_a", "node_b"], node_configs)  # no raise
