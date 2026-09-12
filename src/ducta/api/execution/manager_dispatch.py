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
from functools import partial
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from loguru import logger  # type: ignore

from ducta.api.config import get_settings
from ducta.api.execution.context import execution_id_var
from ducta.api.execution.error_recovery import delete_error_log, flush_error_log, get_error_log
from ducta.api.execution.manager_shared import _TERMINAL_STATUSES
from ducta.api.execution.queue import ExecutionPriority
from ducta.api.execution.resilience_core import delete_resilience_context, get_resilience_context
from ducta.api.execution.runner import run_pipeline_sync
from ducta.api.models.execution import ExecutionResponse, ExecutionStatus, SweepResponse

#: Strong references to in-flight DB-store tasks.
#:
#: The event loop only holds a *weak* reference to a task, so a fire-and-forget
#: `create_task(...)` whose only strong reference is a local variable can be
#: garbage-collected mid-await — and what these tasks persist is the execution
#: record itself, which would then go missing with nothing logged. Discarded by
#: the done-callback, so the set never grows past what is actually pending.
_DB_TASKS: "set[asyncio.Task[Any]]" = set()


def _on_db_done(t: "asyncio.Task[Any]", label: str) -> None:
    """Callback for DB store tasks — logs failures without raising."""
    _DB_TASKS.discard(t)
    if not t.cancelled() and (exc := t.exception()):
        logger.warning("DB store {label} failed: {exc}", label=label, exc=exc)


def _spawn_db_task(coro: Any, label: str) -> None:
    """Schedule a DB-store coroutine on the running loop, logging failures."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        coro.close()
        return
    task = loop.create_task(coro)
    _DB_TASKS.add(task)
    task.add_done_callback(partial(_on_db_done, label=label))


class _DispatchMixin:
    """Execution submission/cancellation, the active-engine registry, and the run loop."""

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
                    user_id=user_id,
                    model_version=model_version,
                    # `merged` is the whole point of a sweep: without it every
                    # combination ran the pipeline with the *same* (empty)
                    # hyperparameters, so N runs produced N identical results
                    # while still reporting distinct sweep indices. `user_id`
                    # matters just as much — left None, `_get_owned` and
                    # `list_executions` filter these runs out, and the user who
                    # launched the sweep cannot list, tail or cancel their own
                    # runs once auth is on.
                    hyperparams=merged,
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

        except Exception as exc:
            exit_code = 1
            error_message = str(exc)
            with self._execution_lock:
                # Don't clobber a concurrent user cancellation with FAILED.
                if record.status != ExecutionStatus.CANCELLED:
                    record.status = ExecutionStatus.FAILED
            if isinstance(exc, TimeoutError):
                logger.warning("Execution {id} timeout: {exc}", id=execution_id, exc=exc)
            else:
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
