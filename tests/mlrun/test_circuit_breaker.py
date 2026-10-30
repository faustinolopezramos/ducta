"""The retry and circuit-breaker rules MLOps storage relies on (ducta.mlrun.resilience).

`LocalStorageBackend` retries each read and write (`with_instance_retry`) and
stops calling a failing disk for a while (`CircuitBreaker`). `test_resilience.py`
covers where the retry config comes from; this covers what the rules do.
No test sleeps: `time.sleep` and `time.time` are replaced.
"""

from __future__ import annotations

import dataclasses

import pandas as pd
import pytest

from ducta.mlrun import resilience
from ducta.mlrun.exceptions import StorageBackendError
from ducta.mlrun.resilience import (
    STORAGE_RETRY_CONFIG,
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerOpenError,
    CircuitState,
    RetryConfig,
    RetryExhaustedError,
    calculate_delay,
    retry_call,
    should_retry,
)
from ducta.mlrun.storage import LocalStorageBackend


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    c = _Clock()
    monkeypatch.setattr(resilience.time, "time", c.time)
    monkeypatch.setattr(resilience.time, "sleep", c.sleep)
    return c


def _breaker(**config) -> CircuitBreaker:
    defaults = dict(failure_threshold=3, success_threshold=2, timeout=30.0, half_open_max_calls=2)
    return CircuitBreaker("disk", CircuitBreakerConfig(**{**defaults, **config}))


class TestCircuitBreaker:
    def test_it_opens_after_the_threshold_and_refuses_calls(self, clock):
        breaker = _breaker()
        for _ in range(2):
            breaker.record_failure(OSError("disk"))
        assert breaker.state is CircuitState.CLOSED

        breaker.record_failure(OSError("disk"))

        assert breaker.state is CircuitState.OPEN and not breaker.is_available
        clock.now += 10
        with pytest.raises(CircuitBreakerOpenError) as raised:
            breaker.check()
        assert raised.value.reset_time == pytest.approx(20.0)

    def test_a_success_while_closed_forgets_earlier_failures(self, clock):
        breaker = _breaker()
        breaker.record_failure()
        breaker.record_failure()
        breaker.record_success()
        breaker.record_failure()
        breaker.record_failure()

        assert breaker.state is CircuitState.CLOSED

    def test_after_the_timeout_it_lets_calls_through_to_test_recovery(self, clock):
        breaker = _breaker()
        for _ in range(3):
            breaker.record_failure()

        clock.now += 30

        assert breaker.state is CircuitState.HALF_OPEN
        breaker.check()  # allowed

    def test_enough_successes_while_testing_close_it(self, clock):
        breaker = _breaker()
        for _ in range(3):
            breaker.record_failure()
        clock.now += 30
        breaker.check()
        breaker.record_success()
        assert breaker.state is CircuitState.HALF_OPEN

        breaker.record_success()

        assert breaker.state is CircuitState.CLOSED

    def test_one_failure_while_testing_opens_it_again(self, clock):
        breaker = _breaker()
        for _ in range(3):
            breaker.record_failure()
        clock.now += 30
        breaker.check()

        breaker.record_failure(OSError("still down"))

        assert breaker.state is CircuitState.OPEN

    def test_while_testing_only_a_few_calls_go_through(self, clock):
        breaker = _breaker(half_open_max_calls=2)
        for _ in range(3):
            breaker.record_failure()
        clock.now += 30

        breaker.check()
        breaker.check()
        with pytest.raises(CircuitBreakerOpenError):
            breaker.check()
        assert breaker.state is CircuitState.OPEN

    def test_reset_closes_it(self, clock):
        breaker = _breaker()
        for _ in range(3):
            breaker.record_failure()

        breaker.reset()

        assert breaker.state is CircuitState.CLOSED
        breaker.check()


class TestShouldRetry:
    CONFIG = RetryConfig(
        retryable_exceptions=(OSError,), non_retryable_exceptions=(FileNotFoundError,)
    )

    def test_non_retryable_wins_over_retryable(self):
        # FileNotFoundError is an OSError: the explicit exclusion decides.
        assert should_retry(OSError("io"), self.CONFIG) is True
        assert should_retry(FileNotFoundError("gone"), self.CONFIG) is False

    def test_a_wrapped_error_is_judged_by_its_cause(self):
        try:
            try:
                raise OSError("disk")
            except OSError as inner:
                raise RuntimeError("write failed") from inner
        except RuntimeError as wrapped:
            assert should_retry(wrapped, self.CONFIG) is True

        assert should_retry(StorageBackendError("write", "p", OSError("disk")), self.CONFIG)
        assert should_retry(ValueError("bad"), self.CONFIG) is False


class TestRetryCall:
    CONFIG = RetryConfig(max_attempts=3, initial_delay=0.5, max_delay=1.5, jitter=False)

    def test_delays_grow_exponentially_up_to_the_cap(self):
        assert [calculate_delay(i, self.CONFIG) for i in range(4)] == [0.5, 1.0, 1.5, 1.5]

    def test_a_transient_error_is_retried_until_it_succeeds(self, clock):
        calls, retries = [], []

        def flaky():
            calls.append(1)
            if len(calls) < 3:
                raise OSError("busy")
            return "ok"

        result = retry_call(self.CONFIG, "write", flaky, on_retry=lambda e, n: retries.append(n))

        assert result == "ok"
        assert len(calls) == 3
        assert retries == [1, 2]
        assert clock.slept == [0.5, 1.0]

    def test_exhausted_retries_name_the_operation_and_keep_the_last_error(self, clock):
        def broken():
            raise OSError("disk full")

        with pytest.raises(RetryExhaustedError) as raised:
            retry_call(self.CONFIG, "write", broken)

        assert (raised.value.operation, raised.value.attempts) == ("write", 3)
        assert isinstance(raised.value.__cause__, OSError)

    def test_a_non_retryable_error_is_raised_as_is_at_once(self, clock):
        calls = []

        def refuses():
            calls.append(1)
            raise ValueError("bad input")

        with pytest.raises(ValueError, match="bad input"):
            retry_call(self.CONFIG, "write", refuses)
        assert calls == [1] and clock.slept == []

    def test_a_failing_retry_callback_does_not_stop_the_retries(self, clock):
        calls = []

        def flaky():
            calls.append(1)
            if len(calls) < 2:
                raise OSError("busy")
            return "ok"

        def noisy(exc, attempt):
            raise RuntimeError("callback bug")

        assert retry_call(self.CONFIG, "write", flaky, on_retry=noisy) == "ok"


class TestStorageBackend:
    """The two together, as `LocalStorageBackend` uses them."""

    @pytest.fixture
    def storage(self, tmp_path, clock):
        # The storage config (what is never retried) with fewer, shorter attempts.
        config = dataclasses.replace(
            STORAGE_RETRY_CONFIG, max_attempts=2, initial_delay=0.1, jitter=False
        )
        backend = LocalStorageBackend(str(tmp_path), retry_config=config)
        backend._circuit_breaker = _breaker(failure_threshold=4)
        return backend

    def test_a_failing_disk_opens_the_breaker_and_later_calls_fail_fast(self, storage, monkeypatch):
        writes = []

        def broken_write(self, path, **kwargs):
            writes.append(path)
            raise OSError("I/O error")

        monkeypatch.setattr(pd.DataFrame, "to_parquet", broken_write)
        df = pd.DataFrame({"a": [1]})

        for _ in range(2):  # 2 calls x 2 attempts = 4 failures
            with pytest.raises(RetryExhaustedError):
                storage.write_dataframe(df, "runs/metrics")
        attempted = len(writes)

        with pytest.raises(CircuitBreakerOpenError):
            storage.write_dataframe(df, "runs/metrics")
        assert len(writes) == attempted  # the disk was not touched again
        assert storage._stats["errors"] == 4

    def test_reading_a_file_that_does_not_exist_is_not_a_disk_failure(self, storage, clock):
        for _ in range(10):
            with pytest.raises(FileNotFoundError):
                storage.read_dataframe("registry/index")

        assert storage._circuit_breaker.state is CircuitState.CLOSED
        assert clock.slept == []  # and it is never retried

    def test_a_round_trip_works_and_keeps_the_breaker_closed(self, storage):
        df = pd.DataFrame({"a": [1, 2]})

        storage.write_dataframe(df, "runs/metrics")

        pd.testing.assert_frame_equal(storage.read_dataframe("runs/metrics"), df)
        assert storage._circuit_breaker.state is CircuitState.CLOSED
