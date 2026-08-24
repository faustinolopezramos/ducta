"""Regression: MLContextBuilder.prepare_node_ml_info returned the *same*
ml_info object (including the same nested hyperparams dict) for every
non-ML node, instead of copying like the ML branch already does. Nodes run
concurrently on a ThreadPoolExecutor, so one node mutating "its" hyperparams
in place could silently leak into every other node sharing that object —
the same class of bug already fixed at the MLflowNodeExecutor layer in
test_mlflow_ml_info_isolation.py, but this is the source of the shared
object those tests didn't reach.
"""

from __future__ import annotations

from ducta.core.execution.ml_builder import MLContextBuilder


class _FakeContext:
    def __init__(self):
        self.nodes_config: dict = {}


def _builder():
    return MLContextBuilder(_FakeContext(), mlops_context=None, is_ml_layer=False)


class TestPrepareNodeMlInfoNonMlBranchIsolation:
    def test_returns_a_copy_not_the_same_object(self):
        shared = {"hyperparams": {"lr": 0.1}}

        result = _builder().prepare_node_ml_info("node_a", shared)

        assert result is not shared
        assert result["hyperparams"] is not shared["hyperparams"]
        assert result == shared

    def test_mutating_one_nodes_hyperparams_does_not_leak_into_another(self):
        builder = _builder()
        shared = {"hyperparams": {"lr": 0.1}}

        result_a = builder.prepare_node_ml_info("node_a", shared)
        result_b = builder.prepare_node_ml_info("node_b", shared)

        result_a["hyperparams"]["lr"] = 999  # a node mutating its dict in place

        assert result_b["hyperparams"]["lr"] == 0.1
        assert shared["hyperparams"]["lr"] == 0.1

    def test_non_dict_hyperparams_is_left_as_is(self):
        shared = {"hyperparams": None}

        result = _builder().prepare_node_ml_info("node_a", shared)

        assert result["hyperparams"] is None

    def test_missing_hyperparams_key_is_left_as_is(self):
        shared = {"model_version": "1"}

        result = _builder().prepare_node_ml_info("node_a", shared)

        assert "hyperparams" not in result
