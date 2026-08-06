"""Regression: HybridExecutor's batch phase must account for every node.

A node that never executed used to be simply absent from `results`, so the
`batch_failures` check in `_execute_unified_hybrid_pipeline` never saw it: it
neither blocked the streaming phase nor appeared in the errors, even though the
data the streaming phase was about to consume had never been produced.

The batch phase now runs through the same engine as a plain batch pipeline
(NodeExecutor.execute_nodes_parallel) rather than a hand-written sequential
loop, so the outcome is read back off the run trace. The invariant is unchanged:
every node in the execution order gets an entry, and anything that is not a
completion stops the streaming phase.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from ducta.core.executors.hybrid import HybridExecutor


def _hybrid_executor(trace, gate_blocked=None) -> HybridExecutor:
    """A HybridExecutor whose batch engine produced *trace*."""
    executor = HybridExecutor.__new__(HybridExecutor)
    executor.unified_state = MagicMock()
    executor.node_executor = MagicMock()
    executor.node_executor.gate_blocked = gate_blocked or {}
    executor.context = MagicMock()
    executor.context._run_node_details = trace
    return executor


class TestBatchPhaseAccountsForEveryNode:
    def test_a_node_with_no_trace_entry_is_recorded_as_skipped(self):
        # The run aborted before "b" ever started: it must still appear.
        executor = _hybrid_executor(trace=[{"name": "a", "status": "success"}])

        results = executor._execute_batch_phase(
            ["a", "b"], {"a": {}, "b": {"dependencies": ["a"]}}, "2026-01-01", "2026-01-01", {}
        )

        assert set(results) == {"a", "b"}
        assert results["a"]["status"] == "completed"
        assert results["b"]["status"] == "skipped"
        assert "aborted" in results["b"]["reason"]

    def test_a_skipped_node_is_not_reported_as_completed(self):
        executor = _hybrid_executor(trace=[{"name": "a", "status": "success"}])

        results = executor._execute_batch_phase(
            ["a", "b"], {"a": {}, "b": {"dependencies": ["a"]}}, "2026-01-01", "2026-01-01", {}
        )

        not_completed = [node for node, r in results.items() if r["status"] != "completed"]
        assert not_completed == ["b"]

    def test_an_upstream_skip_is_carried_through_with_its_reason(self):
        executor = _hybrid_executor(
            trace=[
                {"name": "a", "status": "success"},
                {"name": "b", "status": "skipped", "error": "skipped: missing inputs"},
            ]
        )

        results = executor._execute_batch_phase(
            ["a", "b"], {"a": {}, "b": {"dependencies": ["a"]}}, "2026-01-01", "2026-01-01", {}
        )

        assert results["b"]["status"] == "skipped"
        assert "missing inputs" in results["b"]["reason"]

    def test_a_failed_node_is_recorded_and_fails_the_unified_state(self):
        executor = _hybrid_executor(
            trace=[{"name": "a", "status": "failed", "error": "column not found"}]
        )

        results = executor._execute_batch_phase(["a"], {"a": {}}, "2026-01-01", "2026-01-01", {})

        assert results["a"]["status"] == "failed"
        assert "column not found" in results["a"]["error"]
        # Failing the node in the unified state is what stops streaming queries
        # that declared a dependency on it.
        executor.unified_state.fail_node_execution.assert_called_once()

    def test_a_gate_blocked_node_is_distinguished_from_a_plain_failure(self):
        executor = _hybrid_executor(
            trace=[{"name": "a", "status": "gate_blocked"}],
            gate_blocked={"a": "quality gate blocked: score 0.4"},
        )

        results = executor._execute_batch_phase(["a"], {"a": {}}, "2026-01-01", "2026-01-01", {})

        assert results["a"]["status"] == "gate_blocked"
        assert "score 0.4" in results["a"]["error"]

    def test_a_clean_run_completes_every_node_in_the_unified_state(self):
        executor = _hybrid_executor(
            trace=[{"name": "a", "status": "success"}, {"name": "b", "status": "success"}]
        )

        results = executor._execute_batch_phase(
            ["a", "b"], {"a": {}, "b": {"dependencies": ["a"]}}, "2026-01-01", "2026-01-01", {}
        )

        assert all(r["status"] == "completed" for r in results.values())
        assert executor.unified_state.complete_node_execution.call_count == 2


class TestBatchPhaseUsesTheRealEngine:
    def test_nodes_run_through_execute_nodes_parallel(self):
        # The point of the unification: hybrid no longer reimplements batch, so
        # it inherits parallelism, per-node retry, gate cascades and tracing.
        executor = _hybrid_executor(trace=[{"name": "a", "status": "success"}])

        executor._execute_batch_phase(["a"], {"a": {}}, "2026-01-01", "2026-01-01", {})

        executor.node_executor.execute_nodes_parallel.assert_called_once()
        executor.node_executor.execute_single_node.assert_not_called()
