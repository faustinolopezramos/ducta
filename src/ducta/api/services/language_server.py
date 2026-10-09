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

The code editor's Python language server: hover, go-to-definition,
completion and type diagnostics from a real LSP (basedpyright, pyright or
pylsp), bridged to the browser over a WebSocket.

The bridge is the only thing here that knows LSP framing (``Content-Length``
headers); the browser sends and receives plain JSON-RPC objects. One process
per open editor keeps request ids private to it. ``LanguageServerPool`` is the
seam for a server deployment (per-user limits, remote workers); the local
pool caps how many run at once.
"""

from __future__ import annotations

import asyncio
import json
import shlex
import shutil
from pathlib import Path
from typing import Awaitable, Callable, List, Optional, Protocol

from loguru import logger

#: Tried in order when no command is configured.
KNOWN_SERVERS = (
    ["basedpyright-langserver", "--stdio"],
    ["pyright-langserver", "--stdio"],
    ["pylsp"],
)


def server_command(configured: str = "") -> Optional[List[str]]:
    """The language-server command line, or None when there is none to run."""
    configured = (configured or "").strip()
    if configured.lower() == "off":
        return None
    if configured:
        argv = shlex.split(configured)
        return argv if argv and shutil.which(argv[0]) else None
    for argv in KNOWN_SERVERS:
        if shutil.which(argv[0]):
            return list(argv)
    return None


async def read_message(stream: asyncio.StreamReader) -> Optional[bytes]:
    """One LSP message body from *stream*; None at end of stream."""
    length = None
    while True:
        line = await stream.readline()
        if not line:
            return None
        line = line.strip()
        if not line:
            break
        name, _, value = line.decode("ascii", "replace").partition(":")
        if name.lower() == "content-length":
            length = int(value.strip())
    if length is None:
        return None
    return await stream.readexactly(length)


def frame(body: bytes) -> bytes:
    return f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body


class LanguageServerPool(Protocol):
    def available(self) -> Optional[List[str]]: ...

    async def bridge(
        self,
        root: Path,
        receive: Callable[[], Awaitable[Optional[str]]],
        send: Callable[[str], Awaitable[None]],
    ) -> None: ...


class PoolFull(RuntimeError):
    pass


class LocalLanguageServerPool:
    """Language servers as child processes of the API, at most *limit* at once."""

    def __init__(self, command: str = "", limit: int = 4) -> None:
        self._command = command
        self._slots = asyncio.Semaphore(limit)
        self._limit = limit

    def available(self) -> Optional[List[str]]:
        return server_command(self._command)

    async def bridge(
        self,
        root: Path,
        receive: Callable[[], Awaitable[Optional[str]]],
        send: Callable[[str], Awaitable[None]],
    ) -> None:
        """Pump JSON-RPC between the browser (*receive*/*send*) and a fresh server
        process rooted at *root*, until either side ends."""
        argv = self.available()
        if argv is None:
            raise FileNotFoundError("No Python language server is installed")
        if self._slots.locked():
            raise PoolFull(f"{self._limit} language servers are already running")
        async with self._slots:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                cwd=str(root),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            assert proc.stdin and proc.stdout

            async def to_server() -> None:
                while True:
                    text = await receive()
                    if text is None:
                        return
                    json.loads(text)  # only well-formed JSON reaches the process
                    proc.stdin.write(frame(text.encode("utf-8")))
                    await proc.stdin.drain()

            async def to_browser() -> None:
                while True:
                    body = await read_message(proc.stdout)
                    if body is None:
                        return
                    await send(body.decode("utf-8"))

            tasks = [asyncio.create_task(to_server()), asyncio.create_task(to_browser())]
            try:
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in pending:
                    task.cancel()
                for task in done:
                    if task.exception() and not isinstance(
                        task.exception(), asyncio.CancelledError
                    ):
                        logger.debug("language server bridge ended: {}", task.exception())
            finally:
                if proc.returncode is None:
                    proc.terminate()
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=3)
                    except asyncio.TimeoutError:
                        proc.kill()
