"""Regression test: a hung node must not block execute_nodes_parallel from
returning.

Before the fix, `execute_nodes_parallel` used `with ThreadPoolExecutor(...) as
executor:`, whose `__exit__` calls `shutdown(wait=True)` — blocking the whole
call until every submitted future finishes, including one the coordinator has
already given up on and marked failed after a per-node timeout. Since Python
cannot forcibly stop a running thread, a genuinely hung node function used to
hang the entire pipeline call indefinitely.
"""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

from ducta.core.execution.runner import NodeExecutor


def _node_executor_with_fake_coordinator(sleep_seconds: float) -> NodeExecutor:
    ne = NodeExecutor.__new__(NodeExecutor)
    ne.max_workers = 2

    release_event = threading.Event()

    def fake_coordinate(executor, **kwargs):
        # Simulate the real coordinator's behavior when a node times out:
        # it submits work to the pool, later decides (via its own timeout
        # bookkeeping) to give up and return — while the submitted future
        # keeps running in the background, exactly like a truly hung node.
        executor.submit(time.sleep, sleep_seconds)
        release_event.set()
        return

    ne._coordinator = MagicMock()
    ne._coordinator.coordinate.side_effect = fake_coordinate
    ne._coordinator.cleanup.return_value = None
    ne._coordinator.cancel_all.return_value = None
    ne._initialize_execution_state = MagicMock(return_value=MagicMock())
    ne._release_event = release_event
    return ne


class TestExecuteNodesParallelDoesNotBlockOnHungNode:
    def test_returns_promptly_despite_a_still_running_background_task(self):
        # The dummy "hung node" sleeps far longer than we're willing to wait
        # for execute_nodes_parallel() to return.
        ne = _node_executor_with_fake_coordinator(sleep_seconds=5.0)

        start = time.perf_counter()
        ne.execute_nodes_parallel(
            execution_order=["n1"],
            node_configs={"n1": {}},
            dag={"n1": set()},
            start_date="2026-01-01",
            end_date="2026-01-01",
            ml_info={},
        )
        elapsed = time.perf_counter() - start

        # Must return almost immediately, not wait anywhere near the 5s the
        # background task takes — a `with ThreadPoolExecutor(...)` context
        # manager's implicit `shutdown(wait=True)` would have blocked here.
        assert elapsed < 2.0
