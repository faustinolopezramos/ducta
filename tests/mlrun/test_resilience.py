"""Unit tests for ducta.mlrun.resilience (retry_call / with_instance_retry).

with_instance_retry replaced @with_retry(config=STORAGE_RETRY_CONFIG, ...) on
LocalStorageBackend/DatabricksStorageBackend, which fixed a single config at
class-definition time — no matter what retry_config an instance was built
with, every instance shared the exact same retry behavior. These pin that
per-instance behavior is actually per-instance.
"""

from __future__ import annotations

import pytest

from ducta.mlrun.resilience import RetryConfig, retry_call, with_instance_retry


class TestRetryCallResolvesConfigAtCallTime:
    def test_max_attempts_from_config(self):
        calls = {"n": 0}

        def boom():
            calls["n"] += 1
            raise OSError("boom")

        with pytest.raises(Exception):
            retry_call(RetryConfig(max_attempts=1, initial_delay=0), "op", boom)
        assert calls["n"] == 1

        calls["n"] = 0
        with pytest.raises(Exception):
            retry_call(RetryConfig(max_attempts=4, initial_delay=0), "op", boom)
        assert calls["n"] == 4

    def test_none_config_falls_back_to_default(self):
        calls = {"n": 0}

        def boom():
            calls["n"] += 1
            raise OSError("boom")

        with pytest.raises(Exception):
            retry_call(None, "op", boom)
        assert calls["n"] > 0  # DEFAULT_RETRY_CONFIG.max_attempts


class TestWithInstanceRetryIsPerInstance:
    """Two instances of the same class, each with a different _retry_config,
    must retry a different number of times — the exact regression
    @with_retry(config=MODULE_CONSTANT) could never exhibit."""

    class _Backend:
        def __init__(self, retry_config):
            self._retry_config = retry_config
            self.calls = 0

        @with_instance_retry(operation_name="flaky")
        def flaky(self):
            self.calls += 1
            raise OSError("boom")

    def test_different_instances_retry_different_amounts(self):
        b1 = self._Backend(RetryConfig(max_attempts=1, initial_delay=0))
        b3 = self._Backend(RetryConfig(max_attempts=3, initial_delay=0))

        with pytest.raises(Exception):
            b1.flaky()
        with pytest.raises(Exception):
            b3.flaky()

        assert b1.calls == 1
        assert b3.calls == 3

    def test_missing_retry_config_attribute_uses_default(self):
        class NoConfigBackend:
            def __init__(self):
                self.calls = 0

            @with_instance_retry(operation_name="flaky")
            def flaky(self):
                self.calls += 1
                raise OSError("boom")

        b = NoConfigBackend()
        with pytest.raises(Exception):
            b.flaky()
        assert b.calls > 0
