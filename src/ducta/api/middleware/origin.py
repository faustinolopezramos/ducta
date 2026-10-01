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
"""

from __future__ import annotations

from typing import Any, Optional
from urllib.parse import urlsplit

from loguru import logger  # type: ignore

__all__ = ["is_allowed_websocket_origin", "websocket_origin_allowed"]


def _normalize(origin: str) -> str:
    """Reduce an origin to ``scheme://host:port`` for comparison."""
    parts = urlsplit(origin.strip())
    if not parts.scheme or not parts.netloc:
        return origin.strip().rstrip("/").lower()
    return f"{parts.scheme}://{parts.netloc}".lower()


def is_allowed_websocket_origin(
    origin: Optional[str],
    host_header: Optional[str],
    allowed_origins: Any,
) -> bool:
    """Whether a WebSocket handshake carrying *origin* may proceed.

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


async def websocket_origin_allowed(websocket: Any, settings: Any) -> bool:
    """Check a live WebSocket's ``Origin``, closing it when refused.

    Returns True when the handshake may continue. On refusal the socket is
    closed with 1008 (policy violation) *before* ``accept()``, so a rejected
    caller never reaches the handler body.
    """
    origin = websocket.headers.get("origin")
    host_header = websocket.headers.get("host")

    if is_allowed_websocket_origin(origin, host_header, getattr(settings, "cors_origins", [])):
        return True

    logger.warning(
        "Rejected WebSocket handshake from disallowed origin {origin!r} "
        "(host={host!r}). Add it to CORS_ORIGINS if this is a legitimate client.",
        origin=origin,
        host=host_header,
    )
    await websocket.close(code=1008, reason="Origin not allowed")
    return False
