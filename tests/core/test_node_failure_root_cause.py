"""Regression: a node's real error never reached the caller.

`ParallelCoordinator` deliberately swallows each node's exception so independent
branches can finish. The pipeline-level failure was then raised as a bare
`RuntimeError("Pipeline execution failed due to node failures")` — the node
name, the exception type and the traceback existed only in the logs, so anything
catching this programmatically (the API's error field, `run_pipeline_chain`, the
run certificate) got a message that identified nothing.
"""

from __future__ import annotations

import pytest

from ducta.core.execution.coordinator import ParallelCoordinator
from ducta.core.execution.state import ThreadSafeExecutionState


class BespokeNodeError(RuntimeError):
    """Stands in for whatever a user's node function raises."""


def _state(nodes):
    node_configs = {name: {} for name in nodes}
    return ThreadSafeExecutionState(list(nodes), node_configs)


def _failure_info(error):
    return {
        "status": "failed",
        "error": str(error),
        "error_type": type(error).__name__,
        "start_time": 0.0,
        "end_time": 1.0,
        "config": {},
    }


class TestFirstFailureIsRetained:
    def test_state_records_the_first_failure_only(self):
        state = _state(["a", "b"])
        first = BespokeNodeError("column 'revenue' not found")
        second = ValueError("secondary")

        state.mark_failed("a", _failure_info(first), exception=first)
        state.mark_failed("b", _failure_info(second), exception=second)

        node_name, exception = state.get_first_failure()
        assert node_name == "a"
        assert exception is first

    def test_no_failure_reads_as_none(self):
        assert _state(["a"]).get_first_failure() is None

    def test_mark_failed_without_an_exception_still_flags_failure(self):
        state = _state(["a"])
        state.mark_failed("a", _failure_info(ValueError("x")))

        assert state.is_failed()
        assert state.get_first_failure() == ("a", None)


class TestBuiltFailureError:
    def test_error_names_the_node_and_the_original_exception(self):
        state = _state(["extract", "load"])
        original = BespokeNodeError("column 'revenue' not found")
        state.mark_failed("extract", _failure_info(original), exception=original)

        error = ParallelCoordinator._build_failure_error(state)

        assert isinstance(error, RuntimeError)
        assert "extract" in str(error)
        assert "BespokeNodeError" in str(error)
        assert "column 'revenue' not found" in str(error)

    def test_original_exception_is_chained_as_the_cause(self):
        state = _state(["extract"])
        original = BespokeNodeError("boom")
        state.mark_failed("extract", _failure_info(original), exception=original)

        error = ParallelCoordinator._build_failure_error(state)

        assert error.__cause__ is original

    def test_additional_failed_nodes_are_listed(self):
        state = _state(["a", "b"])
        first = BespokeNodeError("first")
        second = ValueError("second")
        state.mark_failed("a", _failure_info(first), exception=first)
        state.mark_failed("b", _failure_info(second), exception=second)

        message = str(ParallelCoordinator._build_failure_error(state))

        assert "a" in message
        assert "b" in message

    def test_falls_back_to_a_generic_error_when_nothing_was_recorded(self):
        state = _state(["a"])
        state.set_failed()

        error = ParallelCoordinator._build_failure_error(state)

        assert isinstance(error, RuntimeError)
        assert error.__cause__ is None

    def test_raising_it_preserves_the_original_traceback(self):
        state = _state(["extract"])
        try:
            raise BespokeNodeError("deep failure")
        except BespokeNodeError as exc:
            original = exc
            state.mark_failed("extract", _failure_info(exc), exception=exc)

        with pytest.raises(RuntimeError) as caught:
            raise ParallelCoordinator._build_failure_error(state)

        assert caught.value.__cause__ is original
        assert caught.value.__cause__.__traceback__ is not None
