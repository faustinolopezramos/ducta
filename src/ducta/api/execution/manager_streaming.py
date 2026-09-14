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
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, List, Optional

from ducta.api.execution.error_recovery import get_error_log, try_get_error_log
from ducta.api.execution.manager_shared import _TERMINAL_STATUSES
from ducta.api.models.execution import ExecutionResponse, LogEntry


class _StreamingMixin:
    """Live status/log emission and the SSE log-streaming generator."""

    #: Max entries per WebSocket message — keeps a large catch-up batch (e.g.
    #: a fresh connection to a verbose, long-running execution) from becoming
    #: a single multi-MB frame; each chunk is its own `yield`, so the consumer
    #: (routes/execution.py's `async for`) sends and awaits one before the
    #: generator produces the next.
    _LOG_CHUNK_SIZE = 1000

    @staticmethod
    def _prepare_batches(entries: List[LogEntry], dropped: int) -> List[List[LogEntry]]:
        """Split *entries* into page-sized batches, prefixed with a gap-notice
        entry when *dropped* says the buffer already evicted earlier entries
        this consumer never saw."""
        batches: List[List[LogEntry]] = []
        if dropped > 0:
            batches.append(
                [
                    LogEntry(
                        timestamp=datetime.now(tz=timezone.utc),
                        level="WARNING",
                        message=f"[log_gap] {dropped} earlier log line(s) were dropped "
                        "(buffer overflow)",
                        extra={"type": "log_gap", "dropped": dropped},
                    )
                ]
            )
        chunk_size = _StreamingMixin._LOG_CHUNK_SIZE
        for i in range(0, len(entries), chunk_size):
            batches.append(entries[i : i + chunk_size])
        return batches

    def _emit(self, execution_id: str, entry: LogEntry) -> None:
        """Append a log entry and wake any `stream_logs` consumer waiting on it."""
        self._log_manager.append_log(execution_id, entry)
        self._notify_log(execution_id)

    def emit_execution_status(self, record: ExecutionResponse) -> None:
        """Push an execution-level status update through the live log channel."""
        extra: Dict[str, Any] = {
            "type": "execution_status",
            "status": record.status.value,
            "exit_code": record.exit_code,
            "duration_seconds": record.duration_seconds,
            "error_message": record.error_message,
            "finished_at": record.finished_at.isoformat() if record.finished_at else None,
        }
        error_log = try_get_error_log(record.id)
        if error_log is not None and error_log.errors:
            first = error_log.errors[0]
            extra["error_details"] = {
                "count": len(error_log.errors),
                "category": first["error"]["category"],
                "error_type": first["error"]["type"],
                "message": first["error"]["message"],
                "node_id": first["node_id"],
                "traceback_tail": first["error"]["traceback_lines"][-4:],
            }
        entry = LogEntry(
            timestamp=datetime.now(tz=timezone.utc),
            level="INFO",
            message=f"[execution_status] status={record.status.value}",
            extra=extra,
        )
        self._emit(record.id, entry)

    def emit_node_status(self, execution_id: str, node_id: str, status: str) -> None:
        entry = LogEntry(
            timestamp=datetime.now(tz=timezone.utc),
            level="INFO",
            message=f"[node_status] node_id={node_id} status={status}",
            extra={"type": "node_status", "node_id": node_id, "status": status},
        )
        self._emit(execution_id, entry)

    def _record_top_level_error(self, execution_id: str, exception: Exception) -> None:
        """Record a whole-pipeline failure into the execution's error log."""
        try:
            from ducta.api.execution.error_recovery import ErrorContext

            get_error_log(execution_id).log_error(
                exception, ErrorContext(execution_id=execution_id)
            )
        except Exception as exc:  # noqa: BLE001
            from loguru import logger  # type: ignore

            logger.debug(
                "Could not record top-level error for {id}: {exc}", id=execution_id, exc=exc
            )

    def _notify_log(self, execution_id: str) -> None:
        """Notificación thread-safe de nuevos logs disponibles para stream_logs."""
        event = self._log_events.get(execution_id)
        if event is not None and self._loop is not None:
            self._loop.call_soon_threadsafe(event.set)

    def _append_process_output(
        self, execution_id: str, message: str, *, level: str = "INFO"
    ) -> None:
        """Called by ProcessOutputCapture to route captured lines into the log buffer."""
        entry = LogEntry(
            timestamp=datetime.now(tz=timezone.utc),
            level=level,
            message=message,
            extra={"type": "process_output", "render": "cli"},
        )
        self._emit(execution_id, entry)

    async def stream_logs(
        self, execution_id: str, user_id: Optional[str] = None
    ) -> AsyncGenerator[List[LogEntry], None]:
        self._get_owned(execution_id, user_id)

        event = self._log_events.get(execution_id)
        pos = 0

        while True:
            entries, pos, dropped = self._log_manager.get_logs_from(execution_id, pos)
            for chunk in self._prepare_batches(entries, dropped):
                yield chunk

            record = self._store.peek(execution_id)
            if record is None:
                break
            if record.status in _TERMINAL_STATUSES:
                entries, pos, dropped = self._log_manager.get_logs_from(execution_id, pos)
                for chunk in self._prepare_batches(entries, dropped):
                    yield chunk
                break

            if event is not None:
                event.clear()
                entries, pos, dropped = self._log_manager.get_logs_from(execution_id, pos)
                if entries or dropped:
                    for chunk in self._prepare_batches(entries, dropped):
                        yield chunk
                    continue

                try:
                    await asyncio.wait_for(event.wait(), timeout=0.1)
                except asyncio.TimeoutError:
                    continue
            else:
                await asyncio.sleep(0.1)
