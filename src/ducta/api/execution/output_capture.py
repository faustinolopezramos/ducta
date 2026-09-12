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

import json
import os
import re
import sys
import threading
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from ducta.api.execution.manager import ExecutionManager


node_status_re = re.compile(r"^\[node_status\] node_id=(\S+) status=(\S+)$")
_ansi_re = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def strip_ansi(value: str) -> str:
    """Remove ANSI escape sequences from *value*."""
    return _ansi_re.sub("", value)


def looks_like_loguru_serialized(line: str) -> bool:
    """Return True if *line* is a loguru JSON-serialised log record."""
    if not line.strip().startswith("{"):
        return False
    try:
        payload = json.loads(line)
    except Exception:  # noqa: BLE001
        return False
    return isinstance(payload, dict) and isinstance(payload.get("record"), dict)


def infer_process_output_level(line: str) -> str:
    """Infer a log level string from a plain-text process output line."""
    upper = line.upper()
    if (
        "TRACEBACK" in upper
        or "EXCEPTION" in upper
        or " ERROR " in upper
        or upper.startswith("ERROR")
    ):
        return "ERROR"
    if " WARNING " in upper or " WARN " in upper or upper.startswith(("WARNING", "WARN")):
        return "WARNING"
    if " SUCCESS " in upper or upper.startswith("SUCCESS") or line.lstrip().startswith("✓"):
        return "SUCCESS"
    if " DEBUG " in upper or upper.startswith("DEBUG"):
        return "DEBUG"
    return "INFO"


def format_cli_log_line(timestamp: datetime, level: str, message: str) -> str:
    """Format a log line for CLI display inside the execution log stream."""
    display_message = message
    node_match = node_status_re.match(display_message)
    if node_match:
        display_message = f" node_id={node_match.group(1)} status={node_match.group(2)}"

    prefix = "\x1b[1;96mducta:\x1b[0m "
    time_tag = f"\x1b[2m[{timestamp:%H:%M:%S}]\x1b[0m "

    level_styles = {
        "DEBUG": "\x1b[2;37m",
        "INFO": "\x1b[1;94m",
        "WARNING": "\x1b[1;93m",
        "ERROR": "\x1b[1;91m",
        "SUCCESS": "\x1b[1;92m",
        "CRITICAL": "\x1b[1;97;41m",
    }
    level_tag = f"{level_styles.get(level.upper(), '')}{level.upper(): <8}\x1b[0m "

    return f"{prefix}{time_tag}{level_tag}{display_message}"


class ProcessOutputCapture:
    """Capture process stdout/stderr, including Rich and JVM output, into execution logs."""

    def __init__(self, execution_id: str, manager: "ExecutionManager") -> None:
        self.execution_id = execution_id
        self.manager = manager
        self._stdout_fd: Optional[int] = None
        self._stderr_fd: Optional[int] = None
        self._pipe_r: Optional[int] = None
        self._pipe_w: Optional[int] = None
        self._reader: Optional[threading.Thread] = None

    def __enter__(self) -> "ProcessOutputCapture":
        sys.stdout.flush()
        sys.stderr.flush()
        self._stdout_fd = os.dup(1)
        self._stderr_fd = os.dup(2)
        self._pipe_r, self._pipe_w = os.pipe()
        self._reader = threading.Thread(target=self._read_loop, name="ducta-output-capture")
        self._reader.daemon = True
        self._reader.start()

        os.dup2(self._pipe_w, 1)
        os.dup2(self._pipe_w, 2)
        os.close(self._pipe_w)
        self._pipe_w = None
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        sys.stdout.flush()
        sys.stderr.flush()

        if self._stdout_fd is not None:
            os.dup2(self._stdout_fd, 1)
        if self._stderr_fd is not None:
            os.dup2(self._stderr_fd, 2)

        if self._reader is not None:
            self._reader.join(timeout=2)

        for fd in (self._stdout_fd, self._stderr_fd, self._pipe_r):
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass

    def _read_loop(self) -> None:
        if self._pipe_r is None or self._stdout_fd is None:
            return

        pending = ""
        while True:
            try:
                chunk = os.read(self._pipe_r, 4096)
            except OSError:
                break
            if not chunk:
                break

            try:
                os.write(self._stdout_fd, chunk)
            except OSError:
                pass

            pending += chunk.decode(errors="replace")
            lines = pending.splitlines(keepends=True)
            if lines and not lines[-1].endswith(("\n", "\r")):
                pending = lines.pop()
            else:
                pending = ""
            for line in lines:
                self._append_line(line.rstrip("\r\n"))

        if pending:
            self._append_line(pending.rstrip("\r\n"))

    def _append_line(self, line: str) -> None:
        clean = strip_ansi(line)
        if looks_like_loguru_serialized(clean):
            return

        # `clean` (ANSI-stripped) was only ever used to classify the line —
        # the raw line, ANSI codes and all, was what actually got persisted
        # to logs.jsonl/returned by the API, leaking terminal escape
        # sequences into any consumer that isn't itself a terminal.
        self.manager._append_process_output(
            self.execution_id,
            clean,
            level=infer_process_output_level(clean),
        )
