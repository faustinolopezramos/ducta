"""
Copyright (C) 2024-2026 Faustino Lopez Ramos

This file is part of ducta.

Licensed under the Apache License, Version 2.0 (the "License"); you may not
use this file except in compliance with the License. You may obtain a copy
of the License at

    https://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
License for the specific language governing permissions and limitations
under the License.

SPDX-License-Identifier: Apache-2.0

Origin checking for WebSocket handshakes.

``CORSMiddleware`` only sees the ASGI ``http`` scope, so it never inspects a
WebSocket upgrade. That is not a gap in Starlette — the same-origin policy
simply does not apply to WebSockets: a browser will happily open one to any
host, cross-origin, and no CORS header can stop it. Whatever protects an HTTP
route therefore protects nothing on ``/ws``.

That matters most for the endpoints that are deliberately reachable without a
token. The log stream exposes pipeline output and, with auth disabled, admits any
loopback peer — which a page in the user's own browser is. The project already
reached this conclusion once, for CORS: *"binding to loopback is no defence
here: the browser is on the loopback host."* The reasoning holds identically
here; only the channel is different.

``RequestGuardMiddleware`` closes the two holes the Origin check alone left open:

* **DNS rebinding.** A page on ``attacker.example`` can make its own name resolve
  to 127.0.0.1. Its requests are then same-origin *to the browser*, carry
  ``Host: attacker.example`` and a matching ``Origin`` — which the Origin == Host
  rule accepted. Checking ``Host`` against the names this server really answers
  to is what makes that rule safe.
* **Cross-site requests without a body.** CORS only stops a page *reading* a
  response; a form-encoded ``POST`` to a route without a JSON body still runs
  (``git pull``, ``cancel``, ``retry``…). State-changing methods carrying a
  foreign ``Origin`` are refused before they reach a route.
"""

from __future__ import annotations

from typing import Any, List, Optional
from urllib.parse import urlsplit

from loguru import logger  # type: ignore

__all__ = [
    "RequestGuardMiddleware",
    "allowed_host_patterns",
    "is_allowed_host",
    "is_allowed_origin",
    "is_allowed_websocket_origin",
    "websocket_origin_allowed",
]

#: Names that always reach this machine itself, whatever the server is bound to.
LOOPBACK_NAMES = ("localhost", "127.0.0.1", "::1")

#: Bind addresses meaning "every interface": they name no host a client would type.
_WILDCARD_BINDS = frozenset({"0.0.0.0", "::", ""})

#: Methods a cross-site page must not be able to trigger.
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _normalize(origin: str) -> str:
    """Reduce an origin to ``scheme://host:port`` for comparison."""
    parts = urlsplit(origin.strip())
    if not parts.scheme or not parts.netloc:
        return origin.strip().rstrip("/").lower()
    return f"{parts.scheme}://{parts.netloc}".lower()


def is_allowed_origin(
    origin: Optional[str],
    host_header: Optional[str],
    allowed_origins: Any,
) -> bool:
    """Whether a request (or WebSocket handshake) carrying *origin* may proceed.

    Three cases, in order:

    * **No ``Origin``** → allowed. Browsers always send one on a WebSocket
      handshake, so its absence means a non-browser client (a CLI, a test, a
      service). Those are not what this guards against, and rejecting them
      would break every scripted consumer.
    * **Same origin as the request's own ``Host``** → allowed. The packaged UI
      is served by this very app (see ``main.py``'s SPA mount), so it is
      deliberately *not* in ``cors_origins`` — checking only the allow-list
      would reject the application's own front end in production.
    * **Anything else** → must appear in the CORS allow-list.

    A literal ``"*"`` in the allow-list permits any origin, matching what the
    HTTP side would do — though ``register_middleware`` already refuses that
    combination with credentials.
    """
    if not origin:
        return True

    normalized = _normalize(origin)

    if host_header:
        # `Host` carries no scheme, so compare on host:port and accept either.
        host = host_header.strip().lower()
        if normalized in (f"http://{host}", f"https://{host}"):
            return True

    allowed = list(allowed_origins or [])
    if "*" in allowed:
        return True

    return any(_normalize(candidate) == normalized for candidate in allowed)


#: The name this check had before it guarded plain HTTP requests too.
is_allowed_websocket_origin = is_allowed_origin


def host_name(host_header: Optional[str]) -> Optional[str]:
    """The name in a ``Host`` header, lower-cased and without the port; None if malformed."""
    value = (host_header or "").strip().lower()
    if not value:
        return None
    if value.startswith("["):  # [::1]:8000
        end = value.find("]")
        if end == -1:
            return None
        rest = value[end + 1 :]
        if rest and not (rest.startswith(":") and rest[1:].isdigit()):
            return None
        return value[1:end] or None
    name, sep, port = value.rpartition(":")
    if sep and port.isdigit():
        value = name
    if not value or ":" in value or "/" in value or " " in value:
        return None
    return value


def allowed_host_patterns(settings: Any) -> Optional[List[str]]:
    """The Host names ``settings`` answer to, or None when no Host is checked.

    Loopback names always pass. A server bound to every interface without
    ``ALLOWED_HOSTS`` cannot know the names it is reached by, so it checks none
    (and says so at startup — see ``warn_if_hosts_unchecked``).
    """
    configured = [h.strip().lower() for h in getattr(settings, "allowed_hosts", []) or []]
    if "*" in configured:
        return None
    bind = str(getattr(settings, "host", "") or "").strip().lower().strip("[]")
    if bind in _WILDCARD_BINDS:
        if not configured:
            return None
        return [*LOOPBACK_NAMES, *configured]
    return [*LOOPBACK_NAMES, bind, *configured]


def is_allowed_host(host_header: Optional[str], patterns: Optional[List[str]]) -> bool:
    """Whether a request for ``host_header`` is one this server answers."""
    if patterns is None:
        return True
    name = host_name(host_header)
    if name is None:
        return False
    for pattern in patterns:
        if name == pattern:
            return True
        if pattern.startswith("*.") and name.endswith(pattern[1:]):
            return True
    return False


class RequestGuardMiddleware:
    """Refuse requests for a foreign ``Host``, and state changes from a foreign ``Origin``.

    Pure ASGI, so it sees WebSocket handshakes too (``@app.middleware("http")``
    would not). Settings are read per request — ``get_settings`` is cached — so a
    test that swaps them sees the new values.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        kind = scope.get("type")
        if kind not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        from ducta_server.config import get_settings

        settings = get_settings()
        headers = {
            k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers") or []
        }
        host_header = headers.get("host")

        if not is_allowed_host(host_header, allowed_host_patterns(settings)):
            logger.warning(
                "Refused a request for host {host!r}: not localhost and not in ALLOWED_HOSTS.",
                host=host_header,
            )
            await self._refuse(kind, scope, receive, send, 400, "Invalid host header")
            return

        method = str(scope.get("method", "")).upper()
        if kind == "http" and method in _UNSAFE_METHODS:
            origin = headers.get("origin")
            if origin and not is_allowed_origin(
                origin, host_header, getattr(settings, "cors_origins", [])
            ):
                logger.warning(
                    "Refused {method} {path} from origin {origin!r}. Add it to CORS_ORIGINS "
                    "if this is a legitimate client.",
                    method=method,
                    path=scope.get("path"),
                    origin=origin,
                )
                await self._refuse(kind, scope, receive, send, 403, "Origin not allowed")
                return

        await self.app(scope, receive, send)

    @staticmethod
    async def _refuse(
        kind: str, scope: Any, receive: Any, send: Any, status: int, reason: str
    ) -> None:
        if kind == "websocket":
            # Close before accept: the handshake fails and no handler runs.
            await send({"type": "websocket.close", "code": 1008, "reason": reason})
            return
        from starlette.responses import JSONResponse  # type: ignore

        await JSONResponse({"detail": reason}, status_code=status)(scope, receive, send)


async def websocket_origin_allowed(websocket: Any, settings: Any) -> bool:
    """Check a live WebSocket's ``Origin``, closing it when refused.

    Returns True when the handshake may continue. On refusal the socket is
    closed with 1008 (policy violation) *before* ``accept()``, so a rejected
    caller never reaches the handler body.
    """
    origin = websocket.headers.get("origin")
    host_header = websocket.headers.get("host")

    if is_allowed_origin(origin, host_header, getattr(settings, "cors_origins", [])):
        return True

    logger.warning(
        "Rejected WebSocket handshake from disallowed origin {origin!r} "
        "(host={host!r}). Add it to CORS_ORIGINS if this is a legitimate client.",
        origin=origin,
        host=host_header,
    )
    await websocket.close(code=1008, reason="Origin not allowed")
    return False
