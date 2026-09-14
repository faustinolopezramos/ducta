"""Regression tests for WebSocket rate limiting.

`RateLimitMiddleware` extends Starlette's `BaseHTTPMiddleware`, which only
intercepts the ASGI ``http`` scope. WebSocket connections
(``/ws/logs/{execution_id}``, ``/ws/terminal``) bypassed it entirely, so their
handshakes had no rate limiting at all even with ``rate_limit_enabled=True``.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from ducta.api.middleware.rate_limit import (
    SlidingWindowLimiter,
    get_websocket_client_key,
    get_websocket_connection_limiter,
)


def _settings(**overrides):
    defaults = dict(
        rate_limit_enabled=True,
        rate_limit_requests=100,
        rate_limit_window_seconds=60,
        rate_limit_max_keys=10_000,
        rate_limit_redis_url=None,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestGetWebsocketConnectionLimiter:
    def test_builds_an_in_memory_limiter_from_settings(self):
        settings = _settings(rate_limit_requests=5, rate_limit_window_seconds=30)
        limiter = get_websocket_connection_limiter(settings)
        assert isinstance(limiter, SlidingWindowLimiter)
        assert limiter.max_requests == 5
        assert limiter.window_seconds == 30

    def test_reuses_the_same_limiter_for_the_same_settings_object(self):
        settings = _settings()
        first = get_websocket_connection_limiter(settings)
        second = get_websocket_connection_limiter(settings)
        assert first is second

    def test_enforces_the_configured_limit(self):
        settings = _settings(rate_limit_requests=2, rate_limit_window_seconds=60)
        limiter = get_websocket_connection_limiter(settings)
        key = "ip:203.0.113.5"
        assert limiter.is_allowed(key) is True
        assert limiter.is_allowed(key) is True
        assert limiter.is_allowed(key) is False


class TestGetWebsocketClientKey:
    def _fake_ws(self, host, forwarded_for=None):
        ws = MagicMock()
        ws.client = SimpleNamespace(host=host)
        ws.headers = {"x-forwarded-for": forwarded_for} if forwarded_for else {}
        return ws

    def test_uses_direct_client_ip_by_default(self):
        ws = self._fake_ws("8.8.8.8")
        assert get_websocket_client_key(ws) == "ip:8.8.8.8"

    def test_honors_forwarded_header_from_loopback_proxy(self):
        ws = self._fake_ws("127.0.0.1", forwarded_for="198.51.100.9")
        assert get_websocket_client_key(ws) == "ip:198.51.100.9"

    def test_ignores_forwarded_header_from_untrusted_direct_peer(self):
        # 8.8.8.8 is a genuinely public (non-private, non-loopback) address,
        # unlike TEST-NET ranges (192.0.2.0/24 etc.), which Python's
        # `ipaddress` module itself classifies as `is_private`.
        ws = self._fake_ws("8.8.8.8", forwarded_for="198.51.100.9")
        assert get_websocket_client_key(ws) == "ip:8.8.8.8"
