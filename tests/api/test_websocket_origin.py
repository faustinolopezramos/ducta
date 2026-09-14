"""WebSocket handshakes must check `Origin`; CORS cannot do it for them.

`CORSMiddleware` only intercepts the ASGI ``http`` scope, and the same-origin
policy does not apply to WebSockets at all — a browser will open one to any
host, cross-origin, and no CORS header stops it. So every HTTP-side protection
in this app is absent on ``/ws``.

The consequence was concrete: with ``terminal_enabled=true`` and auth disabled
(the default), the terminal admitted any loopback peer — and a page in the
user's own browser is a loopback peer. Any site they visited could open a shell.
The project had already reached this exact conclusion for CORS ("binding to
loopback is no defence here: the browser is on the loopback host"); it just
hadn't been applied to this channel.

Follows the mock-WebSocket pattern from `test_rate_limit.py`: build a MagicMock
socket, patch `get_settings` on the route module, and drive the handler with
`asyncio.run`. Nothing in this suite uses `TestClient.websocket_connect`.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import WebSocketDisconnect

from ducta.api.middleware.origin import is_allowed_websocket_origin

VITE_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


def _settings(**overrides):
    defaults = dict(
        terminal_enabled=True,
        auth_enabled=False,
        rate_limit_enabled=False,
        terminal_shell="/bin/sh",
        cors_origins=list(VITE_ORIGINS),
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _ws(origin=None, host="127.0.0.1:8000", client_host="127.0.0.1"):
    ws = MagicMock()
    ws.close = AsyncMock()
    ws.accept = AsyncMock()
    ws.client = SimpleNamespace(host=client_host)
    headers = {"host": host}
    if origin is not None:
        headers["origin"] = origin
    ws.headers = headers
    return ws


class TestTheOriginRule:
    """The predicate, in isolation."""

    def test_an_allow_listed_origin_passes(self):
        assert is_allowed_websocket_origin("http://localhost:5173", "127.0.0.1:8000", VITE_ORIGINS)

    def test_a_foreign_origin_is_refused(self):
        assert not is_allowed_websocket_origin(
            "http://evil.example", "127.0.0.1:8000", VITE_ORIGINS
        )

    def test_the_apps_own_origin_passes_without_being_allow_listed(self):
        # The packaged UI is served by this app and is deliberately absent from
        # cors_origins. Checking only the allow-list would reject it.
        assert is_allowed_websocket_origin("http://127.0.0.1:8000", "127.0.0.1:8000", VITE_ORIGINS)

    def test_same_origin_over_https_passes(self):
        assert is_allowed_websocket_origin("https://ducta.internal", "ducta.internal", [])

    def test_a_missing_origin_passes(self):
        # Browsers always send Origin on a WS handshake; its absence means a
        # CLI or a test, which is not the threat here.
        assert is_allowed_websocket_origin(None, "127.0.0.1:8000", VITE_ORIGINS)

    def test_a_wildcard_allow_list_permits_anything(self):
        assert is_allowed_websocket_origin("http://evil.example", "127.0.0.1:8000", ["*"])

    def test_matching_ignores_trailing_slash_and_case(self):
        assert is_allowed_websocket_origin("HTTP://LocalHost:5173/", "127.0.0.1:8000", VITE_ORIGINS)

    def test_a_lookalike_host_is_refused(self):
        # localhost:5173 is allowed; localhost.evil.example is not.
        assert not is_allowed_websocket_origin(
            "http://localhost.evil.example:5173", "127.0.0.1:8000", VITE_ORIGINS
        )

    def test_a_different_port_on_an_allowed_host_is_refused(self):
        assert not is_allowed_websocket_origin(
            "http://localhost:9999", "127.0.0.1:8000", VITE_ORIGINS
        )


class TestLogStreamWebSocket:
    """The log stream had no tests of any kind."""

    def test_a_foreign_origin_is_closed_before_accept(self, monkeypatch):
        from ducta.api.routes import execution as execution_module

        ws = _ws(origin="http://evil.example")
        settings = _settings()

        asyncio.run(
            execution_module.stream_logs_ws(
                websocket=ws,
                execution_id="exec-1",
                exec_manager=MagicMock(),
                settings=settings,
            )
        )

        ws.accept.assert_not_awaited()
        ws.close.assert_awaited_once()
        assert ws.close.call_args.kwargs["code"] == 1008

    @pytest.mark.parametrize("origin", [None, "http://localhost:5173", "http://127.0.0.1:8000"])
    def test_permitted_origins_reach_the_handler(self, origin):
        from ducta.api.routes import execution as execution_module

        ws = _ws(origin=origin)
        ws.receive_text = AsyncMock(side_effect=WebSocketDisconnect())
        manager = MagicMock()

        async def _no_logs(*_a, **_k):
            return
            yield  # pragma: no cover — makes this an async generator

        manager.stream_logs = _no_logs

        asyncio.run(
            execution_module.stream_logs_ws(
                websocket=ws,
                execution_id="exec-1",
                exec_manager=manager,
                settings=_settings(),
            )
        )

        # Getting as far as accept() is the proof: Origin did not refuse it.
        ws.accept.assert_awaited_once()
