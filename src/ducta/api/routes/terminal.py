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
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger

from ducta.api.config import Settings, get_settings
from ducta.api.dependencies import authenticate_websocket

ws_router = APIRouter(tags=["Terminal"])


def _resolve_shell(settings: Settings) -> str:
    return settings.terminal_shell or os.environ.get("SHELL") or "/bin/bash"


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

    # 2. POSIX-only (stdlib pty). Checked before accepting/authenticating the
    # socket — it depends only on the server platform, not on the caller, so
    # moving it ahead of the origin/auth checks below changes no security
    # property, only ordering.
    try:
        import fcntl
        import pty
        import struct
        import termios
    except ImportError:
        await websocket.close(code=1011, reason="Terminal not supported on this platform")
        return

    # 1a/1b/3. Origin check, rate limit, and auth — same shared handshake used
    # by the execution log-streaming WebSocket (see dependencies.authenticate_websocket).
    # CORS never sees a WebSocket handshake, so the origin check is the only thing
    # standing between a page on any site the user happens to be visiting and this
    # endpoint. The loopback check further down does not help there: that page's
    # connection *is* loopback.
    user = await authenticate_websocket(websocket, settings, permission="execution.write")
    if user is None:
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

    # A dedicated single-thread executor, not the loop's default one. The read
    # below blocks until the shell produces output — which for an idle terminal
    # is indefinitely — and `run_in_executor(None, ...)` would park that thread
    # in the interpreter-wide default pool that FastAPI also uses to run every
    # `def` (non-async) endpoint. A handful of idle terminals would then starve
    # unrelated request handling. One thread per session, released on cleanup.
    pty_reader = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"pty-{pid}")

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
                data = await loop.run_in_executor(pty_reader, _safe_read, master_fd)
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
        #
        # Signal the whole process *group*, not just the shell. `pty.fork()` makes
        # the child a session leader, so anything it started — a build, a `tail -f`,
        # a background job — is in that group and outlives a bare `kill(pid)`,
        # orphaned and still holding the host's CPU and file descriptors after the
        # browser tab is long gone.
        try:
            os.killpg(os.getpgid(pid), 9)
        except (OSError, ProcessLookupError):
            # No process group (or it is already gone) — fall back to the shell.
            try:
                os.kill(pid, 9)
            except OSError:
                pass
        try:
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
        # After the fd is closed the pending read has returned, so the worker is
        # idle and this does not block. wait=False keeps a wedged read from
        # holding the event loop even so.
        pty_reader.shutdown(wait=False)
        try:
            await websocket.send_text(json.dumps({"type": "exit"}))
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass
        logger.info("Web terminal session closed for user {id}", id=user.id)
