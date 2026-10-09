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

The code editor's language server: whether one is available, and the
WebSocket that bridges the browser's JSON-RPC to it.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from loguru import logger

from ducta.api.config import Settings, get_settings
from ducta.api.dependencies import (
    WorkspaceManagerDep,
    authenticate_websocket,
    require_permission,
)
from ducta.api.services.language_server import LocalLanguageServerPool, PoolFull

#: Editing code is what the language server serves, so it asks the same permission.
LSP_PERMISSION = "pipeline.write"

router = APIRouter(prefix="/projects", tags=["Editor"])
ws_router = APIRouter(prefix="/ws", tags=["WebSocket"])

_pool: Optional[LocalLanguageServerPool] = None


def get_pool(settings: Settings) -> LocalLanguageServerPool:
    global _pool
    if _pool is None:
        _pool = LocalLanguageServerPool(settings.lsp_command, settings.lsp_max_processes)
    return _pool


@router.get(
    "/{project_id}/lsp",
    summary="Whether the code editor has a Python language server",
    dependencies=[Depends(require_permission("project.read"))],
)
async def lsp_status(
    project_id: str,
    manager: WorkspaceManagerDep,
    settings: Settings = Depends(get_settings),
) -> Dict[str, Any]:
    argv = get_pool(settings).available()
    root = manager.for_project(project_id).root
    return {
        "available": argv is not None,
        "command": Path(argv[0]).name if argv else None,
        "root": str(root),
        "hint": None
        if argv
        else "Install one where the API runs: pip install basedpyright " "(or set LSP_COMMAND).",
    }


def _project_root(websocket: WebSocket, project_id: str) -> Optional[Path]:
    """The project's directory, resolved the way HTTP routes resolve ``?source=``.

    Local sources only: a language server analyses — and may import — the code
    it is pointed at, so it never runs on a repository fetched for the occasion.
    """
    from ducta.api.source import SourceResolver
    from ducta.api.workspace.manager import WorkspaceManager

    raw = websocket.query_params.get("source") or os.environ.get("DUCTA_WORKSPACE")
    if not raw or SourceResolver.is_git_url(raw.strip()):
        return None
    try:
        path = SourceResolver.resolve(raw).path
        return WorkspaceManager(path).for_project(project_id).root
    except Exception:  # noqa: BLE001 — any failure is "no such project" to the socket
        return None


@ws_router.websocket("/projects/{project_id}/lsp")
async def lsp_socket(
    websocket: WebSocket,
    project_id: str,
    settings: Settings = Depends(get_settings),
) -> None:
    user = await authenticate_websocket(websocket, settings, permission=LSP_PERMISSION)
    if user is None:
        return
    root = _project_root(websocket, project_id)
    if root is None:
        await websocket.close(code=1008, reason="Unknown project or non-local source")
        return
    await websocket.accept()

    async def receive() -> Optional[str]:
        try:
            return await websocket.receive_text()
        except WebSocketDisconnect:
            return None

    async def send(text: str) -> None:
        await websocket.send_text(text)

    try:
        await get_pool(settings).bridge(root, receive, send)
    except FileNotFoundError as e:
        await websocket.close(code=1011, reason=str(e)[:120])
        return
    except PoolFull as e:
        await websocket.close(code=1013, reason=str(e)[:120])
        return
    except (WebSocketDisconnect, asyncio.CancelledError):
        return
    except Exception as e:  # noqa: BLE001
        logger.warning("language server bridge failed: {}", e)
    try:
        await websocket.close()
    except RuntimeError:
        pass


@ws_router.websocket("/projects/{project_id}/debug")
async def debug_socket(
    websocket: WebSocket,
    project_id: str,
    settings: Settings = Depends(get_settings),
) -> None:
    """The browser's debugger: Debug Adapter Protocol messages, one per frame,
    bridged to the debug run's own process (debugpy, on 127.0.0.1). The run is
    named by ``?execution=``; started with ``debug: true``, it waits for this.

    Local servers only (no accounts, or DEBUG=true) — a debugger can read and
    change anything in the process. One debugger at a time, as debugpy allows.
    """
    from ducta.api.services import debugger
    from ducta.api.services.language_server import frame, read_message

    user = await authenticate_websocket(websocket, settings, permission="pipeline.execute")
    if user is None:
        return
    if settings.auth_enabled and not settings.debug:
        await websocket.close(code=1008, reason="Debugging is for a local server")
        return
    if not debugger.available():
        await websocket.close(code=1011, reason="debugpy is not installed where the API runs")
        return
    if _project_root(websocket, project_id) is None:
        await websocket.close(code=1008, reason="Unknown project or non-local source")
        return
    # The run's own process listens on a port of its own; it takes a moment to start.
    manager = websocket.app.state.execution_manager
    execution_id = websocket.query_params.get("execution") or ""
    reader = writer = None
    for _ in range(120):
        try:
            port = manager.get_execution(execution_id).debug_port
        except Exception:  # noqa: BLE001
            await websocket.close(code=1008, reason="No such run")
            return
        if port:
            try:
                reader, writer = await asyncio.open_connection(debugger.HOST, port)
                break
            except OSError:
                pass
        await asyncio.sleep(0.5)
    if writer is None:
        await websocket.close(code=1013, reason="The debug run is not listening")
        return
    manager.mark_debug_attached(execution_id)
    await websocket.accept()

    async def to_debugpy() -> None:
        while True:
            try:
                text = await websocket.receive_text()
            except WebSocketDisconnect:
                return
            writer.write(frame(text.encode("utf-8")))
            await writer.drain()

    async def to_browser() -> None:
        while True:
            body = await read_message(reader)
            if body is None:
                return
            await websocket.send_text(body.decode("utf-8"))

    tasks = [asyncio.create_task(to_debugpy()), asyncio.create_task(to_browser())]
    try:
        _done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
    finally:
        writer.close()
        try:
            await websocket.close()
        except RuntimeError:
            pass
