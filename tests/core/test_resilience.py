"""Unit tests for ducta.core.resilience.RetryPolicy."""

from __future__ import annotations

import pytest

from ducta.core.resilience import RetryPolicy


class TestRetryPolicy:
    def test_returns_on_first_success(self):
        calls = []

        def f():
            calls.append(1)
            return "ok"

        assert RetryPolicy(max_retries=3, delay=0).execute(f) == "ok"
        assert len(calls) == 1

    def test_retries_then_succeeds(self):
        state = {"n": 0}

        def f():
            state["n"] += 1
            if state["n"] < 3:
                raise RuntimeError("transient")
            return "recovered"

        result = RetryPolicy(max_retries=5, delay=0).execute(f)
        assert result == "recovered"
        assert state["n"] == 3

    def test_raises_after_exhausting_retries(self):
        attempts = {"n": 0}

        def f():
            attempts["n"] += 1
            raise ValueError("always fails")

        policy = RetryPolicy(max_retries=2, delay=0)
        with pytest.raises(ValueError, match="always fails"):
            policy.execute(f)
        # max_retries + 1 total attempts
        assert attempts["n"] == 3

    def test_exponential_backoff_calculation(self):
        policy = RetryPolicy(max_retries=3, delay=2, backoff_factor=2.0)
        assert policy._calculate_backoff(0) == 2.0
        assert policy._calculate_backoff(1) == 4.0
        assert policy._calculate_backoff(2) == 8.0

    def test_passes_through_args(self):
        def add(a, b):
            return a + b

        assert RetryPolicy(delay=0).execute(add, 2, 3) == 5
