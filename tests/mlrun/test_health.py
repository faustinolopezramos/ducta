"""Unit tests for ducta.mlrun.health.HealthCheck (persistent executor reuse)."""

from __future__ import annotations

import time

from ducta.mlrun.health import HealthCheck, HealthCheckResult, HealthMonitor, HealthStatus


class _InstantCheck(HealthCheck):
    def __init__(self):
        super().__init__("instant", timeout=1.0)

    def check(self) -> HealthCheckResult:
        return HealthCheckResult(
            name=self.name, status=HealthStatus.HEALTHY, message="ok", duration_ms=0.0
        )


class _SlowCheck(HealthCheck):
    """A check whose worker function sleeps longer than the timeout."""

    def __init__(self, sleep_seconds: float, timeout: float = 0.1):
        super().__init__("slow", timeout=timeout)
        self.sleep_seconds = sleep_seconds

    def check(self) -> HealthCheckResult:
        time.sleep(self.sleep_seconds)
        return HealthCheckResult(
            name=self.name, status=HealthStatus.HEALTHY, message="ok", duration_ms=0.0
        )


class TestPersistentExecutorReuse:
    def test_same_executor_reused_across_calls(self):
        check = _InstantCheck()
        first_executor = check._executor
        check.execute()
        check.execute()
        assert check._executor is first_executor
        check.close()

    def test_execute_returns_result_on_success(self):
        check = _InstantCheck()
        result = check.execute()
        assert result.status == HealthStatus.HEALTHY
        check.close()

    def test_timeout_reports_unhealthy_and_reuses_executor_on_next_call(self):
        # A check that hangs past its timeout: the executor is not discarded
        # (Python can't kill the thread anyway) — it's reused, and a second
        # call correctly reports unhealthy again rather than spawning a
        # brand-new executor/thread per call.
        check = _SlowCheck(sleep_seconds=0.3, timeout=0.05)
        executor_before = check._executor

        result1 = check.execute()
        assert result1.status == HealthStatus.UNHEALTHY

        result2 = check.execute()
        assert result2.status == HealthStatus.UNHEALTHY
        assert check._executor is executor_before
        check.close()


class TestHealthMonitorClosesChecksOnRemoval:
    def test_remove_check_closes_its_executor(self):
        monitor = HealthMonitor()
        check = _InstantCheck()
        monitor.add_check(check)
        assert monitor.remove_check("instant") is True
        assert check._executor._shutdown is True

    def test_remove_unknown_check_returns_false(self):
        monitor = HealthMonitor()
        assert monitor.remove_check("does-not-exist") is False
