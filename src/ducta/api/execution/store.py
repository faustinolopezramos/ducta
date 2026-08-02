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

import threading
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from ducta.api.exceptions import ExecutionNotFoundError
from ducta.api.models.execution import ExecutionResponse, ExecutionStatus

_TERMINAL_STATUSES = frozenset(
    {ExecutionStatus.SUCCESS, ExecutionStatus.FAILED, ExecutionStatus.CANCELLED}
)


class ExecutionStore:
    """Thread-safe in-memory store for ExecutionResponse records."""

    def __init__(self, max_size: int = 500) -> None:
        self._executions: OrderedDict[str, ExecutionResponse] = OrderedDict()
        self._lock = threading.RLock()
        self.max_size = max_size

    # -- Write operations ------------------------------------------------------

    def add(self, record: ExecutionResponse) -> List[str]:
        """Add a new execution record, evicting oldest terminal record if at capacity.

        Returns the IDs evicted as a side effect, so the caller (which also
        owns the per-execution log buffers) can clean those up too — a
        record evicted here otherwise left its log buffer alive forever,
        since nothing else was pruning it.
        """
        with self._lock:
            self._executions[record.id] = record
            return self._evict_locked()

    def delete(self, execution_id: str) -> None:
        """Remove a record by ID (no-op when absent)."""
        with self._lock:
            self._executions.pop(execution_id, None)

    # -- Read operations -------------------------------------------------------

    def get(self, execution_id: str) -> ExecutionResponse:
        """Return the record or raise ExecutionNotFoundError."""
        with self._lock:
            if execution_id not in self._executions:
                raise ExecutionNotFoundError(
                    f"Execution '{execution_id}' not found",
                    detail={"id": execution_id},
                )
            return self._executions[execution_id]

    def peek(self, execution_id: str) -> Optional[ExecutionResponse]:
        """Return the record if present, else None (no exception raised)."""
        with self._lock:
            return self._executions.get(execution_id)

    def contains(self, execution_id: str) -> bool:
        with self._lock:
            return execution_id in self._executions

    def list_all(self) -> List[ExecutionResponse]:
        """Return all records sorted most-recent first."""
        _epoch = datetime.min.replace(tzinfo=timezone.utc)
        with self._lock:
            return sorted(
                self._executions.values(),
                key=lambda e: e.started_at or _epoch,
                reverse=True,
            )

    def list_paginated(self, skip: int = 0, limit: int = 50) -> tuple[List[ExecutionResponse], int]:
        """Return paginated records (most-recent first) and total count.

        Returns:
            Tuple of (paginated_records, total_count)
        """
        _epoch = datetime.min.replace(tzinfo=timezone.utc)
        with self._lock:
            all_records = sorted(
                self._executions.values(),
                key=lambda e: e.started_at or _epoch,
                reverse=True,
            )
            total = len(all_records)
            paginated = all_records[skip : skip + limit] if limit > 0 else all_records[skip:]
            return paginated, total

    # -- Maintenance -----------------------------------------------------------

    def prune_stale(self, retention_seconds: float) -> List[str]:
        """Remove terminal records older than *retention_seconds*.

        Returns the IDs removed.
        """
        cutoff = datetime.now(tz=timezone.utc) - timedelta(seconds=retention_seconds)
        with self._lock:
            stale = [
                eid
                for eid, rec in self._executions.items()
                if rec.status in _TERMINAL_STATUSES
                and rec.finished_at is not None
                and rec.finished_at < cutoff
            ]
            for eid in stale:
                self._executions.pop(eid, None)
            return stale

    def evict_old(self) -> List[str]:
        """Evict oldest terminal records when the store exceeds *max_size*.

        Returns the IDs evicted.
        """
        with self._lock:
            return self._evict_locked()

    # -- Internal --------------------------------------------------------------

    def _evict_locked(self) -> List[str]:
        """Must be called while holding self._lock."""
        removed: List[str] = []
        if len(self._executions) <= self.max_size:
            return removed
        # Evict terminal records oldest-first, *skipping* (not stopping at) any
        # non-terminal record along the way -- a single long-running execution
        # sitting near the front by insertion order must not block eviction of
        # newer terminal records behind it.
        for execution_id, record in list(self._executions.items()):
            if len(self._executions) <= self.max_size:
                break
            if record.status not in _TERMINAL_STATUSES:
                continue
            self._executions.pop(execution_id, None)
            removed.append(execution_id)
        return removed
