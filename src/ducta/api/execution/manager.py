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
import threading
from datetime import datetime, timezone
from functools import lru_cache, partial
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional
from uuid import uuid4

from loguru import logger  # type: ignore

from ducta.api.config import get_settings
from ducta.api.exceptions import ExecutionNotFoundError
from ducta.api.execution.buffering import get_buffered_log_manager
from ducta.api.execution.context import execution_id_var
from ducta.api.execution.error_recovery import (
    delete_error_log,
    flush_error_log,
    get_error_log,
    load_error_log_summary,
    try_get_error_log,
)
from ducta.api.execution.file_log_store import build_file_log_store
from ducta.api.execution.isolation import get_module_isolation_manager
from ducta.api.execution.log_sink import make_log_filter, make_log_sink
from ducta.api.execution.queue import ExecutionPriority, ExecutionQueue
from ducta.api.execution.resilience_core import delete_resilience_context, get_resilience_context
from ducta.api.execution.runner import run_pipeline_sync
from ducta.api.execution.store import ExecutionStore
from ducta.api.execution.timeout import get_timeout_manager
from ducta.api.models.execution import ExecutionResponse, ExecutionStatus, LogEntry, SweepResponse

_TERMINAL_STATUSES = frozenset(
    {ExecutionStatus.SUCCESS, ExecutionStatus.FAILED, ExecutionStatus.CANCELLED}
)


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


# ── ExecutionManager ─────────────────────────────────────────────────────────


def _on_db_done(t: "asyncio.Task[Any]", label: str) -> None:
    """Callback for DB store tasks — logs failures without raising."""
    if not t.cancelled() and (exc := t.exception()):
        logger.warning("DB store {label} failed: {exc}", label=label, exc=exc)


def _spawn_db_task(coro: Any, label: str) -> None:
    """Schedule a DB-store coroutine on the running loop, logging failures.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        coro.close()
        return
    task = loop.create_task(coro)
    task.add_done_callback(partial(_on_db_done, label=label))


class ExecutionManager:
    """Application-wide manager for pipeline execution lifecycle."""

    def __init__(self) -> None:
        settings = get_settings()

        self._store = ExecutionStore(max_size=settings.max_executions_in_memory)
        self._db_store: "Optional[Any]" = self._init_db_store(settings)
        self._execution_lock = threading.RLock()
        self._task_lock = threading.RLock()
        self._sink_id: Optional[int] = None
        self._maintenance_task: Optional[asyncio.Task[None]] = None
        self._active_execution_id: Optional[str] = None

        self.max_executions = settings.max_executions_in_memory
        self._retention_seconds = settings.execution_retention_seconds
        self._maintenance_interval_seconds = settings.execution_maintenance_interval_seconds

        self._running_tasks: set[asyncio.Task] = set()
        self._timeout_manager = get_timeout_manager(
            default_timeout_seconds=settings.execution_timeout_seconds,
        )
        self._execution_tasks: Dict[str, asyncio.Task] = {}

        self._log_manager = get_buffered_log_manager(
            default_buffer_size=settings.execution_log_buffer_size,
        )
        self._file_log_store = build_file_log_store(settings.runs_dir)
        self._isolation_manager = get_module_isolation_manager()
        self._execution_queue = ExecutionQueue(max_concurrent=settings.max_concurrent_executions)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._log_events: Dict[str, asyncio.Event] = {}
        self._active_engines: Dict[str, Any] = {}
        self._bg_shutdown_lock = threading.Lock()
        self._bg_shutdown_threads: set[threading.Thread] = set()

    @staticmethod
    def _init_db_store(settings: Any) -> "Optional[Any]":
        """Initialize DB store if enabled; returns None and degrades gracefully if not."""
        try:
            from ducta.api.db.engine import get_engine, is_db_enabled

            if is_db_enabled():
                from ducta.api.db.stores.execution_store import DatabaseExecutionStore

                return DatabaseExecutionStore(
                    engine=get_engine(),  # pyrefly: ignore [bad-argument-type]
                    max_size=settings.max_executions_in_memory,
                    log_batch_size=settings.execution_log_db_batch_size,
                )
        except Exception:  # noqa: BLE001
            pass
        return None


    def startup(self) -> None:
        if self._sink_id is not None:
            return

        self._loop = asyncio.get_running_loop()

        log_filter = make_log_filter(
            get_active_id=self._get_active_execution_id,
            log_manager=self._log_manager,
        )
        log_sink = make_log_sink(
            get_active_id=self._get_active_execution_id,
            log_manager=self._log_manager,
            on_append=self._notify_log,
        )

        self._sink_id = logger.add(
            log_sink,
            level="DEBUG",
            format="{message}",
            filter=log_filter,
            serialize=False,
        )

        if self._file_log_store is not None:
            self._log_manager.set_entry_observer(self._file_log_store.append)

        if self._maintenance_task is None or self._maintenance_task.done():
            loop = asyncio.get_running_loop()
            self._maintenance_task = loop.create_task(self._maintenance_loop())

    def shutdown(self) -> None:
        if self._maintenance_task is not None:
            self._maintenance_task.cancel()
            self._maintenance_task = None

        with self._task_lock:
            tasks = list(self._running_tasks)
            self._running_tasks.clear()
            self._execution_tasks.clear()

        for task in tasks:
            task.cancel()

        self._execution_queue.shutdown()
        self._timeout_manager.cleanup_all()
        self._log_manager.cleanup_all()
        if self._file_log_store is not None:
            self._file_log_store.cleanup_all()

        with self._bg_shutdown_lock:
            bg_threads = list(self._bg_shutdown_threads)
        for thread in bg_threads:
            thread.join(timeout=5.0)
            if thread.is_alive():
                logger.warning(
                    "Background shutdown thread {name} did not finish within timeout",
                    name=thread.name,
                )

        if self._sink_id is not None:
            logger.remove(self._sink_id)
            self._sink_id = None

    async def _maintenance_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(self._maintenance_interval_seconds)
                with self._execution_lock:
                    stale_removed = self._store.prune_stale(self._retention_seconds)
                    evicted_removed = self._store.evict_old()

                for removed_id in (*stale_removed, *evicted_removed):
                    self._log_manager.delete_buffer(removed_id)

                if stale_removed or evicted_removed:
                    logger.debug(
                        "ExecutionManager maintenance: stale={stale}, evicted={evicted}",
                        stale=len(stale_removed),
                        evicted=len(evicted_removed),
                    )
        except asyncio.CancelledError:
            logger.debug("ExecutionManager maintenance loop cancelled")
            raise
        except Exception as exc:
            logger.warning("ExecutionManager maintenance loop failed: {exc}", exc=exc)

    # ── Dispatch ────────────────────────────────────────────────────────────

    def execute(
        self,
        source_path: Path,
        pipeline_name: str,
        env: str,
        node_name: Optional[str] = None,
        dry_run: bool = False,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        project_id: Optional[str] = None,
        user_id: Optional[str] = None,
        model_version: Optional[str] = None,
        hyperparams: Optional[Dict[str, Any]] = None,
        sanity_only: bool = False,
        sweep_id: Optional[str] = None,
        sweep_index: Optional[int] = None,
        reuse_upstream: bool = False,
        rerun_all: bool = False,
    ) -> ExecutionResponse:
        execution_id = str(uuid4())
        now = datetime.now(tz=timezone.utc)

        record = ExecutionResponse(
            id=execution_id,
            pipeline_name=pipeline_name,
            user_id=user_id,
            project_id=project_id,
            node_name=node_name,
            env=env,
            status=ExecutionStatus.PENDING,
            dry_run=dry_run,
            model_version=model_version,
            sweep_id=sweep_id,
            sweep_index=sweep_index,
            started_at=now,
        )
        evicted_ids = self._store.add(record)
        for evicted_id in evicted_ids:
            self._log_manager.delete_buffer(evicted_id)

        if self._file_log_store is not None:
            self._file_log_store.start_run(record)

        if self._db_store is not None:
            _spawn_db_task(self._db_store.add(record), "add")

        self._log_manager.create_buffer(execution_id)
        self._log_events[execution_id] = asyncio.Event()
        # Module snapshot/cleanup is taken inside run_pipeline_sync under the global
        # execution-body lock so it cannot race with another run's imports.
        get_resilience_context(execution_id)
        get_error_log(execution_id)

        priority = ExecutionPriority.from_env(env)
        self._execution_queue.enqueue(
            execution_id=execution_id,
            pipeline_name=pipeline_name,
            priority=priority,
        )

        task = asyncio.create_task(
            self._run_execution(
                execution_id,
                source_path,
                pipeline_name,
                env,
                node_name,
                dry_run,
                start_date,
                end_date,
                model_version,
                hyperparams,
                sanity_only,
                reuse_upstream,
                rerun_all,
            )
        )
        with self._task_lock:
            self._running_tasks.add(task)
            self._execution_tasks[execution_id] = task

        def _cleanup_task(t: asyncio.Task[None]) -> None:  # type: ignore[type-arg]
            with self._task_lock:
                self._running_tasks.discard(t)
                self._execution_tasks.pop(execution_id, None)
            self._timeout_manager.cancel_handler(execution_id)
            self._execution_queue.mark_complete(execution_id)
            delete_resilience_context(execution_id)
            delete_error_log(execution_id)
            self._log_events.pop(execution_id, None)

        task.add_done_callback(_cleanup_task)
        return record

    def execute_sweep(
        self,
        source_path: Path,
        pipeline_name: str,
        env: str,
        sweep: Dict[str, Any],
        node_name: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        model_version: Optional[str] = None,
        base_hyperparams: Optional[Dict[str, Any]] = None,
        project_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> "SweepResponse":
        """Expand a sweep spec and enqueue one execution per combination.

        All executions share a ``sweep_id`` and carry a 1-based ``sweep_index``
        plus the sweep metadata inside their hyperparameters, mirroring the CLI
        (``ducta start --sweep``).
        """
        from ducta.core.sweep import SweepError, expand_sweep, new_sweep_id

        # max_runs must be passed into the expansion itself, not checked against
        # len(combos) afterwards: expand_sweep_grid truncates internally at its
        # own default of 50 during expansion, so a max_sweep_size configured
        # above 50 never had any effect under the old post-hoc check.
        max_sweep_size = get_settings().max_sweep_size
        try:
            combos = expand_sweep(sweep, max_runs=max_sweep_size)
        except SweepError as e:
            raise ValueError(str(e)) from e
        sweep_id = new_sweep_id()
        executions: List[ExecutionResponse] = []
        for index, combo in enumerate(combos, start=1):
            merged = {**(base_hyperparams or {}), **combo}
            merged["sweep_id"] = sweep_id
            merged["sweep_index"] = index
            executions.append(
                self.execute(
                    source_path=source_path,
                    pipeline_name=pipeline_name,
                    env=env,
                    node_name=node_name,
                    start_date=start_date,
                    end_date=end_date,
                    project_id=project_id,
                    sweep_id=sweep_id,
                    sweep_index=index,
                )
            )
        return SweepResponse(sweep_id=sweep_id, total=len(executions), executions=executions)

    async def _run_execution(
        self,
        execution_id: str,
        source_path: Path,
        pipeline_name: str,
        env: str,
        node_name: Optional[str],
        dry_run: bool,
        start_date: Optional[str],
        end_date: Optional[str],
        model_version: Optional[str] = None,
        hyperparams: Optional[Dict[str, Any]] = None,
        sanity_only: bool = False,
        reuse_upstream: bool = False,
        rerun_all: bool = False,
    ) -> None:
        await self._execution_queue.acquire_slot(execution_id)

        record = self._store.get(execution_id)

        with self._execution_lock:
            record.status = ExecutionStatus.RUNNING
        self.emit_execution_status(record)

        error_message: Optional[str] = None
        exit_code = 1

        token = execution_id_var.set(execution_id)
        try:
            outcome = await asyncio.to_thread(
                run_pipeline_sync,
                execution_id,
                source_path,
                pipeline_name,
                env,
                node_name,
                dry_run,
                start_date,
                end_date,
                self,  # manager reference for _append_process_output etc.
                model_version,
                hyperparams,
                sanity_only,
                record.project_id,
                reuse_upstream,
                rerun_all,
            )
            exit_code = 0
            with self._execution_lock:
                if not outcome:
                    record.status = ExecutionStatus.SUCCESS
                elif outcome.get("status") == "gate_blocked":
                    exit_code = 1
                    record.status = ExecutionStatus.GATE_BLOCKED
                    error_message = (
                        f"Quality gate blocked node "
                        f"'{outcome.get('node', '?')}': {outcome.get('reason', 'blocked')}"
                    )
                else:
                    record.status = ExecutionStatus.SKIPPED
                    error_message = str(outcome.get("reason", "Skipped: missing dependencies"))

        except asyncio.CancelledError:
            exit_code = 1
            error_message = "Execution cancelled by user"
            with self._execution_lock:
                if record.status != ExecutionStatus.CANCELLED:
                    record.status = ExecutionStatus.CANCELLED
            logger.info("Execution {id} cancelled", id=execution_id)
            raise

        except TimeoutError as exc:
            exit_code = 1
            error_message = str(exc)
            with self._execution_lock:
                record.status = ExecutionStatus.FAILED
            logger.warning("Execution {id} timeout: {exc}", id=execution_id, exc=exc)
            self._record_top_level_error(execution_id, exc)

        except Exception as exc:
            exit_code = 1
            error_message = str(exc)
            with self._execution_lock:
                # Don't clobber a concurrent user cancellation with FAILED.
                if record.status != ExecutionStatus.CANCELLED:
                    record.status = ExecutionStatus.FAILED
            logger.warning("Execution {id} failed: {exc}", id=execution_id, exc=exc)
            self._record_top_level_error(execution_id, exc)

        finally:
            with self._execution_lock:
                record.finished_at = datetime.now(tz=timezone.utc)
                record.exit_code = exit_code
                record.error_message = error_message
                if record.started_at and record.finished_at:
                    record.duration_seconds = (
                        record.finished_at - record.started_at
                    ).total_seconds()

            self.emit_execution_status(record)

            if self._file_log_store is not None:
                self._file_log_store.finish_run(record)

            flush_error_log(execution_id)

            if self._db_store is not None:
                _spawn_db_task(self._db_store.flush_logs(execution_id), "flush_logs")
                _spawn_db_task(self._db_store.update(record), "update")
            execution_id_var.reset(token)


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
        """Return the categorized error summary for an execution, or None.
        """
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

        total = len(all_executions)
        all_executions.sort(key=lambda e: e.started_at or e.finished_at or "", reverse=True)
        paginated = all_executions[skip : skip + limit]
        return paginated, total

    def queue_status(self) -> Dict[str, Any]:
        """Return current queue depth and concurrency stats."""
        return self._execution_queue.get_stats()

    def retry(
        self,
        execution_id: str,
        source_path: Path,
        user_id: Optional[str] = None,
    ) -> ExecutionResponse:
        """Clone a terminal execution and re-enqueue it."""
        original = self._get_owned(execution_id, user_id)
        if original.status not in _TERMINAL_STATUSES:
            raise ValueError(
                f"Cannot retry execution in state '{original.status.value}'; "
                "only terminal executions (success, failed, cancelled) can be retried."
            )
        return self.execute(
            source_path=source_path,
            pipeline_name=original.pipeline_name,
            env=original.env,
            node_name=original.node_name,
            dry_run=original.dry_run,
            project_id=original.project_id,
            user_id=user_id,
        )

    def get_logs(self, execution_id: str, user_id: Optional[str] = None) -> List[LogEntry]:
        self._get_owned(execution_id, user_id)
        return self._log_manager.get_logs(execution_id)

    def register_active_engine(self, execution_id: str, engine: Any) -> None:
        with self._execution_lock:
            self._active_engines[execution_id] = engine

    def unregister_active_engine(self, execution_id: str) -> None:
        with self._execution_lock:
            self._active_engines.pop(execution_id, None)

    def get_active_engine(self, execution_id: str) -> Optional[Any]:
        with self._execution_lock:
            return self._active_engines.get(execution_id)

    def cancel_execution(self, execution_id: str, user_id: Optional[str] = None) -> bool:
        """Mark an execution cancelled and best-effort stop its work."""
        with self._execution_lock:
            record = self._get_owned(execution_id, user_id)

            if record.status not in {ExecutionStatus.PENDING, ExecutionStatus.RUNNING}:
                return False

            record.status = ExecutionStatus.CANCELLED
            record.finished_at = datetime.now(tz=timezone.utc)
            if record.started_at:
                record.duration_seconds = (record.finished_at - record.started_at).total_seconds()
            record.error_message = "Execution cancelled by user"

            self._timeout_manager.cancel_handler(execution_id)
            self._execution_queue.cancel_execution(execution_id)

            # Retrieve the active engine and shut it down asynchronously to avoid blocking the API loop
            engine = self._active_engines.get(execution_id)
            if engine:
                logger.info(
                    "Triggering asynchronous shutdown for cancelled streaming execution {id}",
                    id=execution_id,
                )

                def _bg_shutdown():
                    try:
                        engine.shutdown()
                    except Exception as exc:
                        logger.warning(
                            "Error shutting down engine in background for {id}: {exc}",
                            id=execution_id,
                            exc=exc,
                        )
                    finally:
                        with self._bg_shutdown_lock:
                            self._bg_shutdown_threads.discard(thread)

                thread = threading.Thread(
                    target=_bg_shutdown, name=f"shutdown-{execution_id}", daemon=True
                )
                with self._bg_shutdown_lock:
                    self._bg_shutdown_threads.add(thread)
                thread.start()

            with self._task_lock:
                task = self._execution_tasks.get(execution_id)
            if task is not None and not task.done():
                task.cancel()

        logger.info("Execution {id} cancelled", id=execution_id)
        return True

    def _get_active_execution_id(self) -> Optional[str]:
        with self._execution_lock:
            return self._active_execution_id

    def set_active_execution(self, execution_id: Optional[str]) -> None:
        with self._execution_lock:
            self._active_execution_id = execution_id

    def get_or_create_timeout_handler(self, execution_id: str) -> Any:
        self._timeout_manager.create_handler(execution_id)
        return self._timeout_manager.get_handler(execution_id)

    def attach_certificate(self, execution_id: str, certificate_run_id: str) -> None:
        """Link the Run Certificate emitted by an execution to its record."""
        record = self._store.peek(execution_id)
        if record is not None:
            record.certificate_run_id = certificate_run_id

    def emit_execution_status(self, record: ExecutionResponse) -> None:
        """Push an execution-level status update through the live log channel.
        """
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
        self._log_manager.append_log(record.id, entry)
        self._notify_log(record.id)

    def emit_node_status(self, execution_id: str, node_id: str, status: str) -> None:
        entry = LogEntry(
            timestamp=datetime.now(tz=timezone.utc),
            level="INFO",
            message=f"[node_status] node_id={node_id} status={status}",
            extra={"type": "node_status", "node_id": node_id, "status": status},
        )
        self._log_manager.append_log(execution_id, entry)
        self._notify_log(execution_id)

    def _record_top_level_error(self, execution_id: str, exception: Exception) -> None:
        """Record a whole-pipeline failure into the execution's error log.
        """
        try:
            from ducta.api.execution.error_recovery import ErrorContext

            get_error_log(execution_id).log_error(
                exception, ErrorContext(execution_id=execution_id)
            )
        except Exception as exc:  # noqa: BLE001
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
        self._log_manager.append_log(execution_id, entry)
        self._notify_log(execution_id)

    async def stream_logs(
        self, execution_id: str, user_id: Optional[str] = None
    ) -> AsyncGenerator[List[LogEntry], None]:
        self._get_owned(execution_id, user_id)

        event = self._log_events.get(execution_id)
        pos = 0

        while True:
            batch, pos = self._log_manager.get_logs_from(execution_id, pos)

            if batch:
                yield batch

            record = self._store.peek(execution_id)
            if record is None:
                break
            if record.status in _TERMINAL_STATUSES:
                final_batch, pos = self._log_manager.get_logs_from(execution_id, pos)
                if final_batch:
                    yield final_batch
                break

            if event is not None:
                event.clear()
                batch, pos = self._log_manager.get_logs_from(execution_id, pos)
                if batch:
                    yield batch
                    continue

                try:
                    await asyncio.wait_for(event.wait(), timeout=0.1)
                except asyncio.TimeoutError:
                    continue
            else:
                await asyncio.sleep(0.1)



@lru_cache(maxsize=1)
def get_execution_manager() -> ExecutionManager:
    return ExecutionManager()
