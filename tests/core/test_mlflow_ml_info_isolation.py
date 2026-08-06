"""Regression: MLflowNodeExecutor mutated an ml_info dict shared across threads.

`MLContextBuilder.prepare_node_ml_info` returns the *same* ml_info object for a
non-ML node rather than a copy. `MLflowNodeExecutor.execute_single_node` wrote
`mlflow_run_id`/`mlflow_tracker` straight into it, so with
`max_parallel_nodes > 1` every concurrently running node shared one dict and
overwrote the others' run_id — metrics were attributed to whichever node wrote
last.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from unittest.mock import MagicMock

from ducta.core.mlflow_node_executor import MLflowNodeExecutor


class _FakeTracker:
    """Hands out a distinct run_id per node, like the real step tracker."""

    def __init__(self):
        self.logged = []

    @contextmanager
    def start_node_step(self, node_name, parameters):
        yield f"run-{node_name}"

    def log_node_metric(self, *args, **kwargs):
        self.logged.append(("metric", args, kwargs))

    def log_node_param(self, *args, **kwargs):
        self.logged.append(("param", args, kwargs))


def _executor(observed, barrier=None):
    """An MLflowNodeExecutor whose parent execute_single_node just observes."""
    executor = MLflowNodeExecutor.__new__(MLflowNodeExecutor)
    executor.enable_mlflow = True
    executor.mlflow_tracker = _FakeTracker()
    executor.context = MagicMock()
    executor._get_node_config = lambda name: {"type": "batch"}

    def fake_parent(node_name, start_date, end_date, ml_info):
        if barrier is not None:
            # Force both nodes to be inside the tracked block simultaneously —
            # the exact interleaving that made them clobber each other.
            barrier.wait(timeout=5)
        observed.append((node_name, ml_info.get("mlflow_run_id"), id(ml_info)))

    import ducta.core.execution.runner as node_executor_module

    original = node_executor_module.NodeExecutor.execute_single_node
    node_executor_module.NodeExecutor.execute_single_node = staticmethod(fake_parent)
    return executor, original


def _restore(original):
    import ducta.core.execution.runner as node_executor_module

    node_executor_module.NodeExecutor.execute_single_node = original


class TestMlInfoIsolation:
    def test_callers_dict_is_not_mutated(self):
        observed: list = []
        executor, original = _executor(observed)
        shared = {"hyperparams": {}, "model_version": "1"}
        try:
            executor.execute_single_node("node_a", "2024-01-01", "2024-01-02", shared)
        finally:
            _restore(original)

        assert "mlflow_run_id" not in shared
        assert "mlflow_tracker" not in shared

    def test_the_node_still_receives_its_own_run_id(self):
        observed: list = []
        executor, original = _executor(observed)
        try:
            executor.execute_single_node("node_a", "2024-01-01", "2024-01-02", {"hyperparams": {}})
        finally:
            _restore(original)

        assert observed[0][0] == "node_a"
        assert observed[0][1] == "run-node_a"

    def test_concurrent_nodes_sharing_one_ml_info_keep_distinct_run_ids(self):
        observed: list = []
        barrier = threading.Barrier(2)
        executor, original = _executor(observed, barrier=barrier)
        # The single dict prepare_node_ml_info hands to every non-ML node.
        shared = {"hyperparams": {}, "model_version": "1"}

        def run(node_name):
            executor.execute_single_node(node_name, "2024-01-01", "2024-01-02", shared)

        try:
            threads = [
                threading.Thread(target=run, args=("node_a",)),
                threading.Thread(target=run, args=("node_b",)),
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        finally:
            _restore(original)

        by_node = {name: run_id for name, run_id, _ in observed}
        assert by_node == {"node_a": "run-node_a", "node_b": "run-node_b"}
        # Each node must have seen its *own* dict, not one shared object.
        assert len({dict_id for _, _, dict_id in observed}) == 2
        assert "mlflow_run_id" not in shared
