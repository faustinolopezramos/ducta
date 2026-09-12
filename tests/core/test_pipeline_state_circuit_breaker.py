"""Unit tests for ducta.core.pipeline_state.CircuitBreaker.

This machine blocks pipeline execution while OPEN, but had no dedicated
tests exercising its CLOSED -> OPEN -> HALF_OPEN -> CLOSED/OPEN transitions.
"""

from __future__ import annotations

from datetime import timedelta

from ducta.core.pipeline_state import CircuitBreaker, CircuitBreakerState


class TestClosedState:
    def test_starts_closed_and_allows_execution(self):
        cb = CircuitBreaker(failure_threshold=3)
        assert cb.get_state() == CircuitBreakerState.CLOSED
        assert cb.can_execute() is True

    def test_failures_below_threshold_stay_closed(self):
        cb = CircuitBreaker(failure_threshold=3)
        assert cb.record_failure() is False
        assert cb.record_failure() is False
        assert cb.get_state() == CircuitBreakerState.CLOSED
        assert cb.can_execute() is True

    def test_success_resets_failure_count(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert cb.failure_count == 0
        assert cb.get_state() == CircuitBreakerState.CLOSED


class TestOpensOnThreshold:
    def test_reaching_threshold_opens_circuit(self):
        cb = CircuitBreaker(failure_threshold=2)
        assert cb.record_failure() is False
        assert cb.record_failure() is True
        assert cb.get_state() == CircuitBreakerState.OPEN

    def test_open_circuit_blocks_execution_before_timeout(self):
        cb = CircuitBreaker(failure_threshold=1, timeout=timedelta(minutes=5))
        cb.record_failure()
        assert cb.get_state() == CircuitBreakerState.OPEN
        assert cb.can_execute() is False


class TestHalfOpenTransition:
    def test_can_execute_transitions_to_half_open_after_timeout(self):
        cb = CircuitBreaker(failure_threshold=1, timeout=timedelta(seconds=0))
        cb.record_failure()
        assert cb.get_state() == CircuitBreakerState.OPEN

        allowed = cb.can_execute()

        assert allowed is True
        assert cb.get_state() == CircuitBreakerState.HALF_OPEN

    def test_half_open_respects_max_calls(self):
        cb = CircuitBreaker(
            failure_threshold=1, timeout=timedelta(seconds=0), half_open_max_calls=1
        )
        cb.record_failure()
        assert cb.can_execute() is True  # transitions to HALF_OPEN, consumes the 1 call
        assert cb.get_state() == CircuitBreakerState.HALF_OPEN
        assert cb.can_execute() is False  # no calls left

    def test_half_open_success_closes_circuit(self):
        cb = CircuitBreaker(
            failure_threshold=1, timeout=timedelta(seconds=0), half_open_max_calls=1
        )
        cb.record_failure()
        cb.can_execute()  # -> HALF_OPEN
        cb.record_success()
        assert cb.get_state() == CircuitBreakerState.CLOSED
        assert cb.failure_count == 0
        assert cb.success_count == 0

    def test_half_open_failure_reopens_circuit(self):
        cb = CircuitBreaker(failure_threshold=1, timeout=timedelta(seconds=0))
        cb.record_failure()
        cb.can_execute()  # -> HALF_OPEN
        assert cb.record_failure() is True
        assert cb.get_state() == CircuitBreakerState.OPEN
