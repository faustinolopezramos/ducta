"""Unit tests for ducta.mlrun.cache.TwoLevelCache."""

from __future__ import annotations

import threading
import time

import ducta.mlrun.cache as cache_module
from ducta.mlrun.cache import CacheKeyBuilder, TwoLevelCache


class TestL2LoaderFailureIsLogged:
    def test_loader_exception_returns_default_and_logs_warning(self, monkeypatch):
        warnings = []
        monkeypatch.setattr(cache_module.logger, "warning", lambda *a, **k: warnings.append((a, k)))

        def failing_loader(key):
            raise RuntimeError("backend unreachable")

        cache = TwoLevelCache(l2_loader=failing_loader)
        result = cache.get("missing-key", default="fallback")

        assert result == "fallback"
        # A real L2 failure must be distinguishable in logs from a plain miss.
        assert len(warnings) == 1

    def test_normal_miss_without_loader_returns_default(self):
        cache = TwoLevelCache()
        assert cache.get("missing-key", default="fallback") == "fallback"

    def test_l2_hit_populates_l1(self):
        calls = []

        def loader(key):
            calls.append(key)
            return f"value-for-{key}"

        cache = TwoLevelCache(l2_loader=loader)
        assert cache.get("k") == "value-for-k"
        assert cache.get("k") == "value-for-k"
        assert calls == ["k"]  # second get() served from L1, loader not called again


class TestInFlightGatePollsPastTimeoutInsteadOfGivingUp:
    """Regression: a thread waiting on someone else's in-flight L2 load used
    to call in_flight_event.wait(timeout=5.0) once and, whether it timed out
    or was signaled, immediately return self._l1.get(key, default) — a
    loader slower than the single wait handed every waiter `default` even
    though the load was moments from succeeding."""

    def test_waiting_thread_gets_the_loaded_value_after_multiple_poll_intervals(self):
        load_started = threading.Event()

        def slow_loader(key):
            load_started.set()
            time.sleep(0.15)
            return f"value-for-{key}"

        cache = TwoLevelCache(l2_loader=slow_loader)
        # Small poll interval (well under the loader's sleep) so the waiter
        # must poll more than once; ceiling stays comfortably above it.
        cache._IN_FLIGHT_POLL_INTERVAL = 0.05
        cache._IN_FLIGHT_MAX_WAIT = 1.0

        results = {}

        def loader_thread():
            results["loader"] = cache.get("k", default="MISSED")

        def waiter_thread():
            load_started.wait(timeout=2.0)
            time.sleep(0.01)  # let the loader thread finish registering the gate
            results["waiter"] = cache.get("k", default="MISSED")

        t1 = threading.Thread(target=loader_thread)
        t2 = threading.Thread(target=waiter_thread)
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        assert results["loader"] == "value-for-k"
        assert results["waiter"] == "value-for-k"

    def test_gives_up_after_max_wait_if_loader_never_signals(self, monkeypatch):
        warnings = []
        monkeypatch.setattr(cache_module.logger, "warning", lambda *a, **k: warnings.append((a, k)))

        cache = TwoLevelCache(l2_loader=lambda key: "unused")
        cache._IN_FLIGHT_POLL_INTERVAL = 0.02
        cache._IN_FLIGHT_MAX_WAIT = 0.1

        # Simulate "someone else is loading" without ever signaling — the
        # waiter must still return `default` instead of blocking forever.
        stuck_event = threading.Event()
        cache._in_flight["k"] = stuck_event

        result = cache.get("k", default="fallback")

        assert result == "fallback"
        assert len(warnings) == 1


class TestCacheKeyBuilderNoCollision:
    def test_separator_inside_a_part_does_not_collide_with_split_parts(self):
        builder = CacheKeyBuilder()
        assert builder.custom_key("json", "a:b") != builder.custom_key("json", "a", "b")

    def test_backslash_inside_a_part_does_not_collide(self):
        builder = CacheKeyBuilder()
        assert builder.custom_key("a\\:b") != builder.custom_key("a", "b")

    def test_normal_keys_unaffected(self):
        builder = CacheKeyBuilder()
        assert builder.custom_key("json", "data/sales.parquet") == "mlops:json:data/sales.parquet"
