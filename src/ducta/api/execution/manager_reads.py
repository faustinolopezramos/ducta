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

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from loguru import logger  # type: ignore

from ducta.api.exceptions import ExecutionNotFoundError
from ducta.api.execution.error_recovery import load_error_log_summary
from ducta.api.models.execution import ExecutionResponse, LogEntry
from ducta.api.utils.pagination import paginate


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 date/datetime string, returning None on empty/invalid.

    Accepts a trailing 'Z' and normalizes naive datetimes to UTC so comparisons
    against the timezone-aware ``started_at`` never raise.
    """
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        logger.warning("Ignoring invalid ISO timestamp filter: {value}", value=value)
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class _ReadsMixin:
    """Read paths: in-memory lookups, filtering/pagination, and durable DB/file fallback reads."""

    def _get_owned(self, execution_id: str, user_id: Optional[str]) -> ExecutionResponse:
        """Fetch an execution, enforcing ownership when *user_id* is provided."""
        execution = self._store.get(execution_id)
        if user_id and execution.user_id != user_id:
            raise ExecutionNotFoundError(f"Execution {execution_id} not found")
        return execution

    def get_execution(self, execution_id: str, user_id: Optional[str] = None) -> ExecutionResponse:
        return self._get_owned(execution_id, user_id)

    def get_execution_errors(
        self, execution_id: str, user_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Return the categorized error summary for an execution, or None."""
        self._get_owned(execution_id, user_id)
        return load_error_log_summary(execution_id)

    def list_executions(self, user_id: Optional[str] = None) -> List[ExecutionResponse]:
        all_executions = self._store.list_all()
        if user_id:
            return [e for e in all_executions if e.user_id == user_id]
        return all_executions

    def list_executions_paginated(
        self,
        skip: int = 0,
        limit: int = 50,
        user_id: Optional[str] = None,
        pipeline_name: Optional[str] = None,
        node_name: Optional[str] = None,
        status: Optional[str] = None,
        env: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        sweep_id: Optional[str] = None,
    ) -> tuple[List[ExecutionResponse], int]:
        all_executions = self.list_executions(user_id=user_id)
        if pipeline_name:
            all_executions = [e for e in all_executions if e.pipeline_name == pipeline_name]
        if node_name:
            all_executions = [e for e in all_executions if e.node_name == node_name]
        if status:
            all_executions = [e for e in all_executions if e.status.value == status]
        if env:
            all_executions = [e for e in all_executions if e.env == env]
        if sweep_id:
            all_executions = [e for e in all_executions if e.sweep_id == sweep_id]

        since_dt = _parse_iso(since)
        until_dt = _parse_iso(until)
        if since_dt is not None:
            all_executions = [
                e for e in all_executions if e.started_at and e.started_at >= since_dt
            ]
        if until_dt is not None:
            all_executions = [
                e for e in all_executions if e.started_at and e.started_at <= until_dt
            ]

        all_executions.sort(key=lambda e: e.started_at or e.finished_at or "", reverse=True)
        paginated, total = paginate(all_executions, skip, limit)
        return paginated, total

    def queue_status(self) -> Dict[str, Any]:
        """Return current queue depth and concurrency stats."""
        return self._execution_queue.get_stats()

    def get_logs(self, execution_id: str, user_id: Optional[str] = None) -> List[LogEntry]:
        """In-memory logs for a live execution. Raises if the run is not resident.

        The durable read is `load_logs`; this is the hot path used while a run
        is streaming, where the buffer is authoritative and always present.
        """
        self._get_owned(execution_id, user_id)
        return self._log_manager.get_logs(execution_id)

    # ── Durable reads ───────────────────────────────────────────────────────
    #
    # In-memory state is not the whole story, and it used to be treated as if it
    # were. `_store` holds at most `max_executions_in_memory` records and drops
    # terminal ones after `execution_retention_seconds`; the log buffers go with
    # them, and everything goes on a restart. Meanwhile every run was already
    # being written to `runs_dir` (and to the database, when configured) — the
    # `DatabaseExecutionStore.get_logs` reader existed and had no callers, and
    # nothing in the codebase ever opened a `logs.jsonl`.
    #
    # So a run older than the retention window returned 404 for its record and
    # an empty list for its logs while both sat intact on disk. These two
    # methods are the read path that was missing: memory first (authoritative
    # for live runs), then the database, then the files.

    async def load_execution(
        self, execution_id: str, user_id: Optional[str] = None
    ) -> ExecutionResponse:
        """Return an execution record from whichever layer still has it."""
        try:
            return self._get_owned(execution_id, user_id)
        except ExecutionNotFoundError:
            pass

        record = await self._load_persisted_record(execution_id)
        if record is None:
            raise ExecutionNotFoundError(f"Execution {execution_id} not found")
        # Ownership still applies to a record recovered from disk.
        if user_id and record.user_id != user_id:
            raise ExecutionNotFoundError(f"Execution {execution_id} not found")
        return record

    async def load_logs(self, execution_id: str, user_id: Optional[str] = None) -> List[LogEntry]:
        """Return an execution's logs from whichever layer still has them."""
        # Resolves ownership and raises ExecutionNotFoundError for unknown ids,
        # so a caller cannot use this to probe for other users' executions.
        await self.load_execution(execution_id, user_id)

        buffered = self._log_manager.get_logs(execution_id)
        if buffered:
            return buffered

        if self._db_store is not None:
            try:
                from_db = await self._db_store.get_logs(execution_id)
                if from_db:
                    return from_db
            except Exception as exc:  # noqa: BLE001
                logger.warning("DB log read failed for {id}: {exc}", id=execution_id, exc=exc)

        if self._file_log_store is not None:
            return self._file_log_store.read_logs(execution_id)

        return []

    async def _load_persisted_record(self, execution_id: str) -> Optional[ExecutionResponse]:
        """Look up a record in the database, then on disk. None when neither has it."""
        if self._db_store is not None:
            try:
                record = await self._db_store.peek(execution_id)
                if record is not None:
                    return record
            except Exception as exc:  # noqa: BLE001
                logger.warning("DB record read failed for {id}: {exc}", id=execution_id, exc=exc)

        if self._file_log_store is not None:
            return self._file_log_store.read_meta(execution_id)

        return None
