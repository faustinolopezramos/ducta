"""`DatabaseUserStore` must degrade gracefully when persistence is disabled.

When no DATABASE_URL is configured, `get_session_factory()` returns None and
every `@require_session`-wrapped method should skip the DB round-trip and
return its declared default rather than raising — this is the "skip and
return default" decorator path added in PR6.
"""

from __future__ import annotations

import asyncio

from ducta.api.auth.service import AuthService
from ducta.api.db.stores import user_store as user_store_module
from ducta.api.db.stores.user_store import DatabaseUserStore


def _make_store() -> DatabaseUserStore:
    return DatabaseUserStore(auth_service=AuthService(secret_key="test-secret"))


class TestNoPersistence:
    def test_get_by_id_returns_none_without_raising(self, monkeypatch):
        monkeypatch.setattr(user_store_module, "get_session_factory", lambda: None)
        store = _make_store()
        assert asyncio.run(store.get_by_id("admin")) is None

    def test_get_by_username_returns_none_without_raising(self, monkeypatch):
        monkeypatch.setattr(user_store_module, "get_session_factory", lambda: None)
        store = _make_store()
        assert asyncio.run(store.get_by_username("admin")) is None

    def test_authenticate_returns_none_without_raising(self, monkeypatch):
        monkeypatch.setattr(user_store_module, "get_session_factory", lambda: None)
        store = _make_store()
        assert asyncio.run(store.authenticate("admin", "whatever")) is None

    def test_authenticate_still_probes_dummy_hash_for_constant_time(self, monkeypatch):
        """Even with persistence disabled, authenticate() must still invoke
        verify_password so failed-auth timing doesn't leak whether the DB
        would have been consulted."""
        monkeypatch.setattr(user_store_module, "get_session_factory", lambda: None)
        store = _make_store()
        calls = []
        monkeypatch.setattr(
            store._svc,
            "verify_password",
            lambda plain, hashed: calls.append((plain, hashed)) or False,
        )
        result = asyncio.run(store.authenticate("nobody", "irrelevant"))
        assert result is None
        assert len(calls) == 1
