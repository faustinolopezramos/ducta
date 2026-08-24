from unittest.mock import MagicMock, patch

import pytest

from ducta.gate.handoff import (
    _HandoffStore,
    clear,
    get_store,
    is_enabled,
    normalize_key,
    offer,
    take,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_context_dict(handoff_enabled=False):
    return {
        "global_settings": {"in_memory_handoff": handoff_enabled},
    }


class _ObjContext:
    def __init__(self, handoff_enabled=False):
        self.global_settings = {"in_memory_handoff": handoff_enabled}
        # Accept arbitrary attributes (no __slots__)
        self.__dict__ = self.__dict__  # ensure setattr works


# ── is_enabled ───────────────────────────────────────────────────────────────


class TestIsEnabled:
    def test_enabled_dict(self):
        assert is_enabled(_make_context_dict(True)) is True

    def test_disabled_dict(self):
        assert is_enabled(_make_context_dict(False)) is False

    def test_enabled_object(self):
        assert is_enabled(_ObjContext(True)) is True

    def test_disabled_object(self):
        assert is_enabled(_ObjContext(False)) is False

    def test_no_global_settings_dict(self):
        assert is_enabled({}) is False

    def test_no_global_settings_object(self):
        assert is_enabled(_ObjContext()) is False

    def test_missing_global_settings(self):
        ctx = {"other": 1}
        assert is_enabled(ctx) is False

    def test_none_context(self):
        assert is_enabled(None) is False

    def test_context_raises_on_access(self):
        class BadContext:
            def __getattr__(self, name):
                raise RuntimeError("boom")

        assert is_enabled(BadContext()) is False


# ── normalize_key ────────────────────────────────────────────────────────────


class TestNormalizeKey:
    def test_strips_trailing_slash(self):
        assert normalize_key("/path/to/file/") == "/path/to/file"

    def test_strips_trailing_backslash(self):
        assert normalize_key("/path/to/file\\") == "/path/to/file"

    def test_no_change(self):
        assert normalize_key("/path/to/file") == "/path/to/file"

    def test_empty_string(self):
        assert normalize_key("") == ""

    def test_none_becomes_string(self):
        assert normalize_key(None) == "None"


# ── _HandoffStore ────────────────────────────────────────────────────────────


class TestHandoffStore:
    def test_put_and_get(self):
        store = _HandoffStore()
        df = MagicMock()
        store.put("key1", df)
        assert store.get("key1") is df

    def test_get_missing(self):
        store = _HandoffStore()
        assert store.get("missing") is None

    def test_clear_unpersists(self):
        store = _HandoffStore()
        df = MagicMock()
        store.put("k1", df)
        store.clear()
        assert store.get("k1") is None
        df.unpersist.assert_called_once()

    def test_clear_empty(self):
        store = _HandoffStore()
        store.clear()

    def test_unpersist_exception(self):
        store = _HandoffStore()
        df = MagicMock()
        df.unpersist.side_effect = RuntimeError("fail")
        store.put("k1", df)
        store.clear()

    def test_unpersist_not_called_if_no_method(self):
        store = _HandoffStore()
        store.put("k1", object())
        store.clear()

    def test_thread_safety(self):
        import concurrent.futures

        store = _HandoffStore()
        n = 100
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
            fs = [ex.submit(store.put, str(i), i) for i in range(n)]
            concurrent.futures.wait(fs)
        for i in range(n):
            assert store.get(str(i)) == i

    def test_put_replaces_and_unpersists_previous(self):
        """Regression: put() used to overwrite a key without unpersisting
        the DataFrame it replaced — a pipeline writing to the same output
        path more than once in a run leaked a persisted Spark block per
        overwrite."""
        store = _HandoffStore()
        old_df = MagicMock()
        new_df = MagicMock()
        store.put("k1", old_df)
        store.put("k1", new_df)
        old_df.unpersist.assert_called_once()
        new_df.unpersist.assert_not_called()
        assert store.get("k1") is new_df

    def test_put_replace_unpersist_exception_does_not_raise(self):
        store = _HandoffStore()
        old_df = MagicMock()
        old_df.unpersist.side_effect = RuntimeError("fail")
        store.put("k1", old_df)
        store.put("k1", MagicMock())  # must not raise

    def test_put_same_object_twice_does_not_unpersist(self):
        store = _HandoffStore()
        df = MagicMock()
        store.put("k1", df)
        store.put("k1", df)
        df.unpersist.assert_not_called()


# ── get_store ────────────────────────────────────────────────────────────────


class TestGetStore:
    def test_dict_context_creates_store(self):
        ctx = _make_context_dict()
        store = get_store(ctx)
        assert isinstance(store, _HandoffStore)
        assert ctx["__Ducta_df_handoff__"] is store

    def test_dict_context_reuses_store(self):
        ctx = _make_context_dict()
        s1 = get_store(ctx)
        s2 = get_store(ctx)
        assert s1 is s2

    def test_object_context_creates_store(self):
        ctx = _ObjContext()
        store = get_store(ctx)
        assert isinstance(store, _HandoffStore)
        assert hasattr(ctx, "_Ducta_df_handoff")

    def test_object_context_reuses_store(self):
        ctx = _ObjContext()
        s1 = get_store(ctx)
        s2 = get_store(ctx)
        assert s1 is s2

    def test_object_context_rejects_attribute(self):
        class SlotsObj:
            __slots__ = ("global_settings",)

            def __init__(self):
                self.global_settings = {"in_memory_handoff": True}

        ctx = SlotsObj()
        store = get_store(ctx)
        assert store is None


# ── offer / take ─────────────────────────────────────────────────────────────


class TestOfferTake:
    def test_offer_stores_dataframe(self):
        ctx = _make_context_dict(handoff_enabled=True)
        df = MagicMock()
        df.persist = MagicMock()
        df.rdd = MagicMock()
        offer(ctx, "/path/to/data", df, "overwrite")
        assert take(ctx, "/path/to/data") is df
        df.persist.assert_called_once()

    def test_offer_disabled(self):
        ctx = _make_context_dict(handoff_enabled=False)
        df = MagicMock()
        df.persist = MagicMock()
        df.rdd = MagicMock()
        offer(ctx, "/path", df, "overwrite")
        assert take(ctx, "/path") is None
        df.persist.assert_not_called()

    def test_offer_append_mode_skips(self):
        ctx = _make_context_dict(handoff_enabled=True)
        df = MagicMock()
        df.persist = MagicMock()
        df.rdd = MagicMock()
        offer(ctx, "/path", df, "append")
        assert take(ctx, "/path") is None

    def test_offer_non_spark_df_skips(self):
        ctx = _make_context_dict(handoff_enabled=True)
        df = MagicMock()
        df.persist = MagicMock()
        del df.rdd  # no rdd attr → not a Spark DF
        offer(ctx, "/path", df, "overwrite")
        assert take(ctx, "/path") is None

    def test_take_no_store(self):
        class SlotsObj:
            __slots__ = ("global_settings",)

            def __init__(self):
                self.global_settings = {"in_memory_handoff": True}

        ctx = SlotsObj()
        assert take(ctx, "/path") is None

    def test_take_missing_path(self):
        ctx = _make_context_dict(handoff_enabled=True)
        assert take(ctx, "/nonexistent") is None


# ── clear ────────────────────────────────────────────────────────────────────


class TestClear:
    def test_clears_dict_context(self):
        ctx = _make_context_dict(handoff_enabled=True)
        df = MagicMock()
        store = get_store(ctx)
        store.put("k1", df)
        clear(ctx)
        assert store.get("k1") is None

    def test_clears_object_context(self):
        ctx = _ObjContext(handoff_enabled=True)
        df = MagicMock()
        store = get_store(ctx)
        store.put("k1", df)
        clear(ctx)
        assert store.get("k1") is None

    def test_clear_no_store_does_nothing(self):
        clear({})
        clear(object())
