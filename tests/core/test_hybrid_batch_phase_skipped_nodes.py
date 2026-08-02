"""Regression test: HybridExecutor._execute_batch_phase must record a node
that could not start, not silently drop it from `results`.

Before the fix, `if not self.unified_state.start_node_execution(node): continue`
wrote no entry to `results` for that node, so it was simply absent from
batch_results and from execution_result["errors"] — even though it never ran.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from ducta.core.executor import HybridExecutor


def _hybrid_executor(startable_nodes) -> HybridExecutor:
    executor = HybridExecutor.__new__(HybridExecutor)
    executor.unified_state = MagicMock()
    executor.unified_state.start_node_execution.side_effect = lambda n: n in startable_nodes
    executor.node_executor = MagicMock()
    return executor


class TestBatchPhaseRecordsUnstartableNodes:
    def test_unstartable_node_is_recorded_as_skipped(self):
        node_configs = {"a": {}, "b": {"dependencies": ["a"]}}
        executor = _hybrid_executor(startable_nodes={"a"})  # "b" can't start

        results = executor._execute_batch_phase(
            ["a", "b"], node_configs, "2026-01-01", "2026-01-01", {}
        )

        assert "b" in results
        assert results["b"]["status"] == "skipped"
        assert results["a"]["status"] == "completed"

    def test_skipped_node_counts_as_a_batch_failure(self):
        node_configs = {"a": {}, "b": {"dependencies": ["a"]}}
        executor = _hybrid_executor(startable_nodes={"a"})

        results = executor._execute_batch_phase(
            ["a", "b"], node_configs, "2026-01-01", "2026-01-01", {}
        )

        failures = [node for node, r in results.items() if r["status"] != "completed"]
        assert failures == ["b"]
