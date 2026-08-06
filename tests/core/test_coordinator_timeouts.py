"""`_fail_timed_out_nodes` must judge nodes by their outcome, not only the clock.

`_process_completed_nodes` breaks out of its `as_completed` loop as soon as new
nodes become ready, which leaves already-finished futures sitting in `running`
until the next pass. The timeout sweep walked `running` looking only at
`start_time`, so a node that had completed *inside* its budget could be recorded
as a timeout failure — and, because the first failure aborts the run, take the
whole pipeline with it.

Only the end-to-end slow-node case was covered before
(`test_engine_end_to_end.py::TestTimeouts`), which never produces a finished
future left in `running`.
"""

from __future__ import annotations

import time
from concurrent.futures import Future

import pytest

from ducta.core.execution.coordinator import ParallelCoordinator
from ducta.core.execution.state import ThreadSafeExecutionState
from tests.core.fakes import FakeContext


@pytest.fixture
def coordinator():
    context = FakeContext()
    return ParallelCoordinator(
        context=context,
        max_workers=2,
        node_timeout=10,
        is_ml_layer=False,
        execute_callback=lambda *a, **k: None,
        ml_builder=None,
    )


def _state(node_names):
    configs = {name: {"module": "m", "function": "f"} for name in node_names}
    return ThreadSafeExecutionState(list(node_names), configs)


def _register(state, node_name, future, *, started_ago):
    state.add_running_future(
        future,
        {"node_name": node_name, "start_time": time.time() - started_ago, "config": {}},
    )


class TestFinishedFuturesAreNotTimedOut:
    def test_a_completed_future_over_budget_is_left_alone(self, coordinator):
        # The regression: it finished, so its real result is what counts. The
        # next pass of the completion loop reads it.
        state = _state(["slow_but_done"])
        future: Future = Future()
        future.set_result(None)
        _register(state, "slow_but_done", future, started_ago=999)

        coordinator._fail_timed_out_nodes(state)

        assert not state.is_failed()
        assert state.check_running_future(future) is not None

    def test_a_completed_future_that_failed_is_left_to_the_normal_path(self, coordinator):
        # Its exception must be reported as itself, not relabelled "timeout".
        state = _state(["broken"])
        future: Future = Future()
        future.set_exception(RuntimeError("boom"))
        _register(state, "broken", future, started_ago=999)

        coordinator._fail_timed_out_nodes(state)

        assert not state.is_failed()

    def test_a_cancelled_future_is_left_alone(self, coordinator):
        state = _state(["gone"])
        future: Future = Future()
        future.cancel()
        _register(state, "gone", future, started_ago=999)

        coordinator._fail_timed_out_nodes(state)

        assert not state.is_failed()


class TestGenuineTimeoutsStillFail:
    def test_a_still_running_node_over_budget_fails_the_run(self, coordinator):
        state = _state(["hung"])
        future: Future = Future()
        future.set_running_or_notify_cancel()  # running, never completes
        _register(state, "hung", future, started_ago=999)

        coordinator._fail_timed_out_nodes(state)

        assert state.is_failed()
        node_name, exception = state.get_first_failure()
        assert node_name == "hung"
        assert type(exception).__name__ == "NodeTimeoutError"
        assert state.execution_results["hung"]["error_type"] == "TimeoutError"

    def test_a_running_node_inside_its_budget_is_untouched(self, coordinator):
        state = _state(["fine"])
        future: Future = Future()
        future.set_running_or_notify_cancel()
        _register(state, "fine", future, started_ago=1)

        coordinator._fail_timed_out_nodes(state)

        assert not state.is_failed()

    def test_only_the_hung_node_is_blamed(self, coordinator):
        state = _state(["done", "hung"])
        finished: Future = Future()
        finished.set_result(None)
        _register(state, "done", finished, started_ago=999)

        hung: Future = Future()
        hung.set_running_or_notify_cancel()
        _register(state, "hung", hung, started_ago=999)

        coordinator._fail_timed_out_nodes(state)

        assert state.get_first_failure()[0] == "hung"
        assert "done" not in state.execution_results
