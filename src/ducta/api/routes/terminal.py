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
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger

from ducta.api.config import Settings, get_settings
from ducta.api.dependencies import WebSocketAuthError, resolve_websocket_user
from ducta.api.middleware.origin import websocket_origin_allowed

ws_router = APIRouter(tags=["Terminal"])


def _resolve_shell(settings: Settings) -> str:
    return settings.terminal_shell or os.environ.get("SHELL") or "/bin/bash"


def _extract_token(websocket: WebSocket) -> Optional[str]:
    auth_header = websocket.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    return websocket.cookies.get("access_token")


def _is_loopback_client(websocket: WebSocket) -> bool:
    """Return True when the WebSocket peer is a loopback address."""
    import ipaddress

    if websocket.client is None:
        return False
    try:
        return ipaddress.ip_address(websocket.client.host).is_loopback
    except ValueError:
        return False


@ws_router.websocket("/terminal")
async def terminal_ws(websocket: WebSocket) -> None:
    settings = get_settings()

    # 1. Feature gate — fail closed.
    if not settings.terminal_enabled:
        await websocket.close(code=1008, reason="Terminal disabled")
        return

    # 1a. Origin — checked before anything else that could accept the socket.
    # CORS never sees a WebSocket handshake, so without this a page on any site
    # the user happens to be visiting can open this endpoint from their own
    # browser. The loopback check further down does not help there: that page's
    # connection *is* loopback.
    if not await websocket_origin_allowed(websocket, settings):
        return

    # 1b. Rate limit the handshake — `BaseHTTPMiddleware` (RateLimitMiddleware)
    # only intercepts the ASGI 'http' scope and never sees WebSocket connections.
    if settings.rate_limit_enabled:
        from ducta.api.middleware.rate_limit import (
            get_websocket_client_key,
            get_websocket_connection_limiter,
        )

        limiter = get_websocket_connection_limiter(settings)
        if not limiter.is_allowed(get_websocket_client_key(websocket)):
            await websocket.close(code=1013, reason="Rate limit exceeded")
            return

    # 2. POSIX-only (stdlib pty).
    try:
        import fcntl
        import pty
        import struct
        import termios
    except ImportError:
        await websocket.close(code=1011, reason="Terminal not supported on this platform")
        return

    # 3. Auth — same scheme as the logs WebSocket.
    token = _extract_token(websocket)
    try:
        user = await resolve_websocket_user(settings, token)
    except WebSocketAuthError as exc:
        await websocket.close(code=exc.code, reason=exc.reason)
        return
    if settings.auth_enabled and not user.has_permission("execution.write"):
        await websocket.close(code=1008, reason="Forbidden: insufficient permissions")
        return

    # When auth is disabled there is no per-user permission to enforce, so a remote
    # client could obtain a shell. Restrict the terminal to loopback in that mode so
    # enabling it for local development never exposes RCE over the network.
    if not settings.auth_enabled and not _is_loopback_client(websocket):
        logger.warning(
            "Rejected non-loopback terminal connection from {host} (auth disabled)",
            host=websocket.client.host if websocket.client else "unknown",
        )
        await websocket.close(
            code=1008, reason="Terminal restricted to localhost when auth disabled"
        )
        return

    shell = _resolve_shell(settings)
    if shutil.which(shell) is None and not os.path.exists(shell):
        await websocket.close(code=1011, reason=f"Shell not found: {shell}")
        return

    await websocket.accept()
    logger.warning("Web terminal session opened by user {id} (shell={sh})", id=user.id, sh=shell)

    # 4. Spawn the shell attached to a PTY.
    pid, master_fd = pty.fork()
    if pid == 0:  # child
        cwd = os.environ.get("DUCTA_WORKSPACE") or os.getcwd()
        try:
            os.chdir(cwd)
        except OSError:
            pass
        os.execvp(shell, [shell])
        os._exit(1)  # unreachable on success

    loop = asyncio.get_running_loop()
    stop = asyncio.Event()

    def _set_winsize(cols: int, rows: int) -> None:
        try:
            winsize = struct.pack("HHHH", rows, cols, 0, 0)
            fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)
        except OSError:
            pass

    async def pty_to_ws() -> None:
        """Forward PTY output to the client."""
        try:
            while not stop.is_set():
                data = await loop.run_in_executor(None, _safe_read, master_fd)
                if not data:
                    break
                await websocket.send_text(
                    json.dumps({"type": "output", "data": data.decode("utf-8", "replace")})
                )
        except Exception:  # noqa: BLE001
            pass
        finally:
            stop.set()

    def _safe_read(fd: int) -> bytes:
        try:
            return os.read(fd, 4096)
        except OSError:
            return b""

    reader_task = asyncio.create_task(pty_to_ws())

    try:
        while not stop.is_set():
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            mtype = msg.get("type")
            if mtype == "input":
                os.write(master_fd, str(msg.get("data", "")).encode("utf-8"))
            elif mtype == "resize":
                _set_winsize(int(msg.get("cols", 80)), int(msg.get("rows", 24)))
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        logger.warning("Terminal session error for user {id}: {exc}", id=user.id, exc=exc)
    finally:
        stop.set()
        # Kill the child first: closing the PTY slave makes the blocking os.read on
        # master_fd return EOF, so the reader thread unblocks before we close the fd
        # (avoids closing master_fd while a background read is still in flight).
        try:
            os.kill(pid, 9)
            os.waitpid(pid, 0)
        except (OSError, ChildProcessError):
            pass
        reader_task.cancel()
        try:
            await reader_task
        except asyncio.CancelledError:
            pass
        try:
            os.close(master_fd)
        except OSError:
            pass
        try:
            await websocket.send_text(json.dumps({"type": "exit"}))
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass
        logger.info("Web terminal session closed for user {id}", id=user.id)
