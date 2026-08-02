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

import logging
import threading
from collections import deque
from datetime import datetime
from itertools import islice
from typing import Callable, Deque, Optional

from loguru import logger as loguru_logger

from ducta.api.models.execution import LogEntry

_internal_logger = logging.getLogger("ducta.api.execution.buffering")

EntryObserver = Callable[[str, LogEntry], None]


class CircularLogBuffer:
    """A circular buffer for storing log entries with automatic overflow handling."""

    def __init__(self, max_size: int = 50_000):
        """Initialize buffer with maximum capacity.

        Args:
            max_size: Maximum number of log entries to keep. Default: 50,000 lines
        """
        self.max_size = max_size
        self._buffer: Deque[LogEntry] = deque(maxlen=max_size)
        self._lock = threading.RLock()
        # Monotonic count of entries ever appended; lets readers fetch
        # incrementally by absolute sequence even after circular eviction.
        self._total_appended = 0

    def append(self, entry: LogEntry) -> None:
        """Add a log entry. Oldest entries are automatically evicted if buffer is full."""
        with self._lock:
            self._buffer.append(entry)
            self._total_appended += 1

    def extend(self, entries: list[LogEntry]) -> None:
        """Add multiple log entries."""
        with self._lock:
            self._buffer.extend(entries)
            self._total_appended += len(entries)

    def get_all(self) -> list[LogEntry]:
        """Return all entries in chronological order."""
        with self._lock:
            return list(self._buffer)

    def get_after(self, timestamp: datetime) -> list[LogEntry]:
        """Return entries after a specific timestamp."""
        with self._lock:
            return [e for e in self._buffer if e.timestamp > timestamp]

    def get_from(self, seq: int) -> tuple[list[LogEntry], int]:
        """Return entries appended at or after absolute sequence *seq*.

        Returns ``(entries, next_seq)`` where *next_seq* is the sequence to pass
        on the next call. Unlike positional indexing into ``get_all()``, absolute
        sequences stay correct after circular eviction, and only the new tail is
        copied instead of the whole buffer.
        """
        with self._lock:
            oldest_seq = self._total_appended - len(self._buffer)
            start = max(seq, oldest_seq) - oldest_seq
            if start >= len(self._buffer):
                return [], self._total_appended
            entries = list(islice(self._buffer, start, None))
            return entries, self._total_appended

    def get_last(self, count: int) -> list[LogEntry]:
        """Return the last N entries."""
        if count <= 0:
            return []
        with self._lock:
            return list(self._buffer)[-count:]

    def clear(self) -> None:
        """Clear all entries."""
        with self._lock:
            self._buffer.clear()

    @property
    def size(self) -> int:
        """Return the number of entries currently in the buffer."""
        with self._lock:
            return len(self._buffer)

    @property
    def is_near_capacity(self) -> bool:
        """Return True if buffer is 80%+ full."""
        with self._lock:
            return len(self._buffer) > self.max_size * 0.8

    @property
    def capacity(self) -> int:
        """Return the maximum capacity."""
        return self.max_size


class BufferedLogManager:
    """Manages circular log buffers for all active executions."""

    def __init__(self, default_buffer_size: int = 50_000):
        """Initialize with default buffer size for new executions."""
        self.default_buffer_size = default_buffer_size
        self._buffers: dict[str, CircularLogBuffer] = {}
        self._lock = threading.RLock()
        self._entry_observer: Optional[EntryObserver] = None

    def set_entry_observer(self, observer: Optional[EntryObserver]) -> None:
        """Register a callback invoked with (execution_id, entry) on every append."""
        self._entry_observer = observer

    def create_buffer(self, execution_id: str) -> CircularLogBuffer:
        """Create a new circular buffer for an execution."""
        with self._lock:
            if execution_id not in self._buffers:
                self._buffers[execution_id] = CircularLogBuffer(self.default_buffer_size)
                loguru_logger.debug(
                    "Buffered logs: created buffer for {id} (capacity: {size})",
                    id=execution_id,
                    size=self.default_buffer_size,
                )
            return self._buffers[execution_id]

    def get_buffer(self, execution_id: str) -> CircularLogBuffer | None:
        """Get the buffer for an execution, or None if not found."""
        with self._lock:
            return self._buffers.get(execution_id)

    def append_log(self, execution_id: str, entry: LogEntry) -> bool:
        """Add log entry to execution's buffer. Return True if at near capacity."""
        buffer = self.get_buffer(execution_id)
        if buffer is None:
            return False

        buffer.append(entry)

        observer = self._entry_observer
        if observer is not None:
            try:
                observer(execution_id, entry)
            except Exception as exc:  # noqa: BLE001
                _internal_logger.warning(
                    "Buffered logs: entry observer failed for %s: %s",
                    execution_id,
                    exc,
                )

        if buffer.is_near_capacity and buffer.size % 10_000 == 0:
            _internal_logger.warning(
                "Buffered logs: execution %s approaching capacity (%d/%d)",
                execution_id,
                buffer.size,
                buffer.max_size,
            )

        return buffer.is_near_capacity

    def get_logs(self, execution_id: str) -> list[LogEntry]:
        """Get all logs for execution."""
        buffer = self.get_buffer(execution_id)
        return buffer.get_all() if buffer else []

    def get_logs_from(self, execution_id: str, seq: int) -> tuple[list[LogEntry], int]:
        """Incrementally fetch logs appended since absolute sequence *seq*."""
        buffer = self.get_buffer(execution_id)
        return buffer.get_from(seq) if buffer else ([], seq)

    def get_logs_after(self, execution_id: str, timestamp: datetime) -> list[LogEntry]:
        """Get logs for execution after a timestamp."""
        buffer = self.get_buffer(execution_id)
        return buffer.get_after(timestamp) if buffer else []

    def delete_buffer(self, execution_id: str) -> int:
        """Delete buffer for execution and return the number of logs deleted."""
        with self._lock:
            buffer = self._buffers.pop(execution_id, None)
        if buffer:
            size = buffer.size
            buffer.clear()
            loguru_logger.debug(
                "Buffered logs: deleted {count} entries for execution {id}",
                count=size,
                id=execution_id,
            )
            return size
        return 0

    def cleanup_all(self) -> None:
        """Clear all buffers (on shutdown)."""
        with self._lock:
            buffers = list(self._buffers.values())
            self._buffers.clear()
        for buffer in buffers:
            buffer.clear()
        loguru_logger.debug("Buffered logs: cleared all buffers")

    @property
    def total_logs(self) -> int:
        """Return total number of logs across all buffers."""
        with self._lock:
            return sum(b.size for b in self._buffers.values())

    @property
    def buffer_count(self) -> int:
        """Return number of active buffers."""
        with self._lock:
            return len(self._buffers)


# Singleton instance
_buffered_log_manager: BufferedLogManager | None = None


def get_buffered_log_manager(
    default_buffer_size: int = 50_000,
) -> BufferedLogManager:
    """Get or create the singleton BufferedLogManager."""
    global _buffered_log_manager
    if _buffered_log_manager is None:
        _buffered_log_manager = BufferedLogManager(default_buffer_size)
    return _buffered_log_manager
