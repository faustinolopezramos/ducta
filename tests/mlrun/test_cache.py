"""Unit tests for ducta.mlrun.cache.TwoLevelCache."""

from __future__ import annotations

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
