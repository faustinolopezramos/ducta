"""Regression: `execute_nodes_parallel`'s ThreadSafeExecutionState (and its
`gate_blocked` dict) was purely local and discarded once the call returned.
`skip_downstream` (the default gate behavior) lets the run complete without
raising, so nothing — not even the CLI — could tell a gate-blocked run apart
from a clean one afterward. `NodeExecutor.gate_blocked` now persists it.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from ducta.core.node_executor import NodeExecutor, ThreadSafeExecutionState


def _node_executor_with_fake_coordinator(execution_state) -> NodeExecutor:
    ne = NodeExecutor.__new__(NodeExecutor)
    ne.max_workers = 1
    ne.gate_blocked = {}
    ne._coordinator = MagicMock()
    ne._coordinator.coordinate.return_value = None
    ne._coordinator.cleanup.return_value = None
    ne._initialize_execution_state = MagicMock(return_value=execution_state)
    return ne


class TestGateBlockedPersistsAfterParallelRun:
    def test_gate_blocked_nodes_are_visible_after_the_run_completes(self):
        state = ThreadSafeExecutionState(execution_order=["n1"], node_configs={"n1": {}})
        state.mark_gate_blocked("n1", {"status": "gate_blocked", "error": "score too low"})
        ne = _node_executor_with_fake_coordinator(state)

        assert ne.gate_blocked == {}  # nothing yet before the run

        ne.execute_nodes_parallel(
            execution_order=["n1"],
            node_configs={"n1": {}},
            dag={"n1": set()},
            start_date="2026-01-01",
            end_date="2026-01-01",
            ml_info={},
        )

        assert "n1" in ne.gate_blocked
        assert ne.gate_blocked["n1"]["error"] == "score too low"

    def test_clean_run_leaves_gate_blocked_empty(self):
        state = ThreadSafeExecutionState(execution_order=["n1"], node_configs={"n1": {}})
        ne = _node_executor_with_fake_coordinator(state)

        ne.execute_nodes_parallel(
            execution_order=["n1"],
            node_configs={"n1": {}},
            dag={"n1": set()},
            start_date="2026-01-01",
            end_date="2026-01-01",
            ml_info={},
        )

        assert ne.gate_blocked == {}
