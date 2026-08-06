"""Regression test: a genuine exception from coordinate() must survive
cleanup()'s own exception, not be silently replaced by it.

Before the fix, `finally: self._coordinator.cleanup(...)` ran unconditionally;
if `coordinate()` raised a real bug (not a normal node failure — those return
from coordinate() without raising) and `cleanup()` also raised (e.g. its
generic "Pipeline execution failed due to node failures" RuntimeError when
execution_state.is_failed() happens to also be true), Python's finally-block
semantics discarded the original exception/traceback and propagated cleanup's
generic one instead.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ducta.core.execution.runner import NodeExecutor


def _node_executor_with_fake_coordinator(coordinate_error, cleanup_error) -> NodeExecutor:
    ne = NodeExecutor.__new__(NodeExecutor)
    ne.max_workers = 1
    ne._coordinator = MagicMock()
    ne._coordinator.coordinate.side_effect = coordinate_error
    ne._coordinator.cleanup.side_effect = cleanup_error
    ne._coordinator.cancel_all.return_value = None
    ne._initialize_execution_state = MagicMock(return_value=MagicMock())
    return ne


class TestOriginalExceptionSurvivesCleanupFailure:
    def test_coordinate_exception_wins_over_cleanup_exception(self):
        ne = _node_executor_with_fake_coordinator(
            coordinate_error=ValueError("real bug in coordinate()"),
            cleanup_error=RuntimeError("Pipeline execution failed due to node failures"),
        )

        with pytest.raises(ValueError, match="real bug in coordinate"):
            ne.execute_nodes_parallel(
                execution_order=["n1"],
                node_configs={"n1": {}},
                dag={"n1": set()},
                start_date="2026-01-01",
                end_date="2026-01-01",
                ml_info={},
            )

    def test_cleanup_exception_propagates_when_coordinate_did_not_raise(self):
        ne = _node_executor_with_fake_coordinator(
            coordinate_error=None,
            cleanup_error=RuntimeError("Pipeline execution failed due to node failures"),
        )

        with pytest.raises(RuntimeError, match="failed due to node failures"):
            ne.execute_nodes_parallel(
                execution_order=["n1"],
                node_configs={"n1": {}},
                dag={"n1": set()},
                start_date="2026-01-01",
                end_date="2026-01-01",
                ml_info={},
            )
