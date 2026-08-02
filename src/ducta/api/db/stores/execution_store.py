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
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from loguru import logger
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine

from ducta.api.db.models import ExecutionLogRow, ExecutionRow
from ducta.api.db.session import get_session_factory
from ducta.api.exceptions import ExecutionNotFoundError
from ducta.api.models.execution import ExecutionResponse, ExecutionStatus, LogEntry

_TERMINAL_STATUSES = frozenset(
    {ExecutionStatus.SUCCESS, ExecutionStatus.FAILED, ExecutionStatus.CANCELLED}
)


def _row_to_response(row: ExecutionRow) -> ExecutionResponse:
    return ExecutionResponse(
        id=row.id,
        pipeline_name=row.pipeline_name,
        user_id=row.user_id,
        env=row.env,
        status=ExecutionStatus(row.status),
        dry_run=row.dry_run,
        started_at=row.started_at,
        finished_at=row.finished_at,
        exit_code=row.exit_code,
        duration_seconds=row.duration_secs,
        error_message=row.error_message,
        model_version=row.model_version,
        sweep_id=row.sweep_id,
        sweep_index=row.sweep_index,
    )


class DatabaseExecutionStore:
    """Async execution store backed by SQLAlchemy (SQLite or PostgreSQL)."""

    def __init__(self, engine: AsyncEngine, max_size: int = 500, log_batch_size: int = 50) -> None:
        self.max_size = max_size
        self._engine = engine
        self._log_batch_size = log_batch_size
        self._pending_logs: Dict[str, List[ExecutionLogRow]] = {}
        self._pending_lock: asyncio.Lock = asyncio.Lock()

    # ------------------------------------------------------------------ write

    async def add(self, record: ExecutionResponse) -> None:
        factory = get_session_factory()
        if factory is None:
            return
        async with factory() as session:
            row = ExecutionRow(
                id=record.id,
                pipeline_name=record.pipeline_name,
                user_id=record.user_id,
                env=record.env,
                status=record.status.value,
                dry_run=record.dry_run,
                submitted_at=record.started_at,
                started_at=record.started_at,
                finished_at=record.finished_at,
                exit_code=record.exit_code,
                duration_secs=record.duration_seconds,
                error_message=record.error_message,
                model_version=record.model_version,
                sweep_id=record.sweep_id,
                sweep_index=record.sweep_index,
            )
            await session.merge(row)
            try:
                await session.commit()
            except Exception as exc:
                await session.rollback()
                logger.warning(
                    "DbExecutionStore.add merge failed for {id}: {exc}", id=record.id, exc=exc
                )

    async def update(self, record: ExecutionResponse) -> None:
        """Upsert a record (called when status transitions happen)."""
        factory = get_session_factory()
        if factory is None:
            return
        async with factory() as session:
            result = await session.get(ExecutionRow, record.id)
            if result is None:
                row = ExecutionRow(
                    id=record.id,
                    pipeline_name=record.pipeline_name,
                    user_id=record.user_id,
                    env=record.env,
                    status=record.status.value,
                    dry_run=record.dry_run,
                    submitted_at=record.started_at,
                    started_at=record.started_at,
                    finished_at=record.finished_at,
                    exit_code=record.exit_code,
                    duration_secs=record.duration_seconds,
                    error_message=record.error_message,
                    model_version=record.model_version,
                    sweep_id=record.sweep_id,
                    sweep_index=record.sweep_index,
                )
                await session.merge(row)
            else:
                result.status = record.status.value
                result.started_at = record.started_at
                result.finished_at = record.finished_at
                result.exit_code = record.exit_code
                result.duration_secs = record.duration_seconds
                result.error_message = record.error_message
            try:
                await session.commit()
            except Exception as exc:
                await session.rollback()
                logger.warning(
                    "DbExecutionStore.update failed for {id}: {exc}", id=record.id, exc=exc
                )

    async def delete(self, execution_id: str) -> None:
        factory = get_session_factory()
        if factory is None:
            return
        async with factory() as session:
            await session.execute(delete(ExecutionRow).where(ExecutionRow.id == execution_id))
            await session.commit()

    async def append_log(self, execution_id: str, entry: LogEntry) -> None:
        """Buffer log line and flush to DB in batches."""
        factory = get_session_factory()
        if factory is None:
            return

        row = ExecutionLogRow(
            execution_id=execution_id,
            ts=entry.timestamp,
            level=entry.level,
            message=entry.message,
        )
        row.extra = entry.extra

        batch_to_flush = None
        async with self._pending_lock:
            bucket = self._pending_logs.setdefault(execution_id, [])
            bucket.append(row)
            if len(bucket) >= self._log_batch_size:
                batch_to_flush = self._pending_logs.pop(execution_id)

        if batch_to_flush is not None:
            await self._flush_rows(batch_to_flush)

    async def flush_logs(self, execution_id: str) -> None:
        """Flush remaining buffered log rows for *execution_id* (call on execution completion)."""
        async with self._pending_lock:
            batch = self._pending_logs.pop(execution_id, [])
        if batch:
            await self._flush_rows(batch)

    async def _flush_rows(self, rows: List[ExecutionLogRow]) -> None:
        factory = get_session_factory()
        if factory is None:
            return
        async with factory() as session:
            session.add_all(rows)
            await session.commit()

    # ------------------------------------------------------------------ read

    async def get(self, execution_id: str) -> ExecutionResponse:
        factory = get_session_factory()
        if factory is None:
            raise ExecutionNotFoundError(
                f"Execution '{execution_id}' not found",
                detail={"id": execution_id},
            )
        async with factory() as session:
            row = await session.get(ExecutionRow, execution_id)
        if row is None:
            raise ExecutionNotFoundError(
                f"Execution '{execution_id}' not found",
                detail={"id": execution_id},
            )
        return _row_to_response(row)

    async def peek(self, execution_id: str) -> Optional[ExecutionResponse]:
        try:
            return await self.get(execution_id)
        except ExecutionNotFoundError:
            return None

    async def contains(self, execution_id: str) -> bool:
        return await self.peek(execution_id) is not None

    async def list_all(
        self,
        pipeline_name: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[ExecutionResponse]:
        factory = get_session_factory()
        if factory is None:
            return []
        stmt = select(ExecutionRow).order_by(ExecutionRow.started_at.desc())
        if pipeline_name:
            stmt = stmt.where(ExecutionRow.pipeline_name == pipeline_name)
        stmt = stmt.limit(limit).offset(offset)
        async with factory() as session:
            result = await session.execute(stmt)
            rows = result.scalars().all()
        return [_row_to_response(r) for r in rows]

    async def get_logs(
        self, execution_id: str, limit: int = 500, offset: int = 0
    ) -> List[LogEntry]:
        factory = get_session_factory()
        if factory is None:
            return []
        stmt = (
            select(ExecutionLogRow)
            .where(ExecutionLogRow.execution_id == execution_id)
            .order_by(ExecutionLogRow.ts.asc(), ExecutionLogRow.id.asc())
            .limit(limit)
            .offset(offset)
        )
        async with factory() as session:
            result = await session.execute(stmt)
            rows = result.scalars().all()
        return [
            LogEntry(
                timestamp=r.ts,
                level=r.level,
                message=r.message,
                extra=r.extra,
            )
            for r in rows
        ]

    # ------------------------------------------------------------------ maintenance

    async def prune_stale(self, retention_seconds: float) -> int:
        """Delete terminal executions (and their logs via cascade) older than *retention_seconds*."""
        cutoff = datetime.now(tz=timezone.utc) - timedelta(seconds=retention_seconds)
        terminal_values = [s.value for s in _TERMINAL_STATUSES]
        factory = get_session_factory()
        if factory is None:
            return 0
        async with factory() as session:
            result = await session.execute(
                delete(ExecutionRow).where(
                    ExecutionRow.status.in_(terminal_values),
                    ExecutionRow.finished_at < cutoff,
                )
            )
            await session.commit()
            deleted = result.rowcount
        if deleted:
            logger.debug("Pruned {n} stale execution records from DB", n=deleted)
        return deleted
