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
from typing import Any, Dict, Optional

from loguru import logger  # type: ignore

from ducta.api.config import get_settings
from ducta.api.execution.buffering import get_buffered_log_manager
from ducta.api.execution.file_log_store import build_file_log_store
from ducta.api.execution.isolation import get_module_isolation_manager
from ducta.api.execution.log_sink import make_log_filter, make_log_sink
from ducta.api.execution.queue import ExecutionQueue
from ducta.api.execution.store import ExecutionStore
from ducta.api.execution.timeout import get_timeout_manager


class _LifecycleMixin:
    """ExecutionManager construction, startup/shutdown, and the maintenance loop."""

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
