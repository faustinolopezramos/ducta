"""Unit tests for the streaming-preview logic extracted out of routes/execution.py.

`read_delta_parquet_preview`/`read_streaming_data`/`read_streaming_data_external`
need a real Spark/Delta/pandas setup to exercise meaningfully end-to-end, so
coverage here focuses on the two pieces that are testable in isolation:
`json_safe`'s value coercion and `StreamingPreviewCache`'s TTL/caching behavior.
"""

from __future__ import annotations

import time
from datetime import date, datetime
from decimal import Decimal

from ducta.api.execution.streaming_preview import StreamingPreviewCache, json_safe


class TestJsonSafe:
    def test_passthrough_for_primitives(self):
        assert json_safe(None) is None
        assert json_safe("x") == "x"
        assert json_safe(True) is True
        assert json_safe(1) == 1
        assert json_safe(1.5) == 1.5

    def test_datetime_and_date_become_isoformat_strings(self):
        dt = datetime(2024, 1, 2, 3, 4, 5)
        d = date(2024, 1, 2)
        assert json_safe(dt) == dt.isoformat()
        assert json_safe(d) == d.isoformat()

    def test_decimal_becomes_float(self):
        result = json_safe(Decimal("3.14"))
        assert result == 3.14
        assert isinstance(result, float)

    def test_bytes_are_decoded(self):
        assert json_safe(b"hello") == "hello"

    def test_dict_and_list_recurse(self):
        value = {"a": Decimal("1"), "b": [Decimal("2"), {"c": b"z"}]}
        assert json_safe(value) == {"a": 1.0, "b": [2.0, {"c": "z"}]}

    def test_tuple_and_set_become_lists(self):
        assert json_safe((1, 2)) == [1, 2]
        assert json_safe({1}) == [1]

    def test_numpy_like_scalar_uses_item(self):
        class FakeScalar:
            def item(self):
                return 42

        assert json_safe(FakeScalar()) == 42

    def test_unrecognized_object_falls_back_to_str(self):
        class Opaque:
            def __str__(self):
                return "opaque-repr"

        assert json_safe(Opaque()) == "opaque-repr"


class TestStreamingPreviewCache:
    def test_computes_once_and_returns_cached_value_within_ttl(self):
        cache = StreamingPreviewCache(ttl_seconds=60.0)
        calls = []

        def compute():
            calls.append(1)
            return {"n": len(calls)}

        first = cache.get_or_compute("key", compute)
        second = cache.get_or_compute("key", compute)

        assert first == {"n": 1}
        assert second == {"n": 1}
        assert len(calls) == 1

    def test_recomputes_after_ttl_expires(self):
        cache = StreamingPreviewCache(ttl_seconds=0.05)
        calls = []

        def compute():
            calls.append(1)
            return {"n": len(calls)}

        cache.get_or_compute("key", compute)
        time.sleep(0.1)
        second = cache.get_or_compute("key", compute)

        assert second == {"n": 2}
        assert len(calls) == 2

    def test_different_keys_are_cached_independently(self):
        cache = StreamingPreviewCache(ttl_seconds=60.0)

        a = cache.get_or_compute("a", lambda: {"who": "a"})
        b = cache.get_or_compute("b", lambda: {"who": "b"})

        assert a == {"who": "a"}
        assert b == {"who": "b"}

    def test_stale_entries_older_than_sixty_seconds_are_pruned(self):
        cache = StreamingPreviewCache(ttl_seconds=1.0)
        cache._cache["stale"] = (time.time() - 61, {"old": True})

        cache.get_or_compute("fresh", lambda: {"n": 1})

        assert "stale" not in cache._cache
