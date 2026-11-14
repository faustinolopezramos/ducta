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

What the ``ExecutionManager`` mixins share, declared once for the type checker.

``ExecutionManager`` is assembled from four mixins (lifecycle, dispatch, reads,
streaming); each uses state that ``_LifecycleMixin.__init__`` creates and methods
another mixin defines. Without this declaration mypy saw none of it. It is a
type-checking aid only: the mixins inherit it under ``TYPE_CHECKING``.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any, Dict, Optional

from ducta_server.execution.buffering import BufferedLogManager
from ducta_server.execution.file_log_store import FileLogStore
from ducta_server.execution.isolation import ModuleIsolationManager
from ducta_server.execution.queue import ExecutionQueue
from ducta_server.execution.store import ExecutionStore
from ducta_server.execution.timeout import TimeoutManager
from ducta_server.models.execution import ExecutionResponse


class _ManagerState:
    # Created by _LifecycleMixin.__init__.
    _store: ExecutionStore
    _db_store: Optional[Any]
    _execution_lock: threading.RLock
    _task_lock: threading.RLock
    _sink_id: Optional[int]
    _maintenance_task: Optional["asyncio.Task[None]"]
    _active_execution_id: Optional[str]
    max_executions: int
    _retention_seconds: float
    _maintenance_interval_seconds: float
    _running_tasks: "set[asyncio.Task[Any]]"
    _timeout_manager: TimeoutManager
    _execution_tasks: "Dict[str, asyncio.Task[Any]]"
    _log_manager: BufferedLogManager
    _file_log_store: Optional[FileLogStore]
    _isolation_manager: ModuleIsolationManager
    _execution_queue: ExecutionQueue
    _loop: Optional[asyncio.AbstractEventLoop]
    _log_events: Dict[str, asyncio.Event]
    _active_engines: Dict[str, Any]
    _bg_shutdown_lock: threading.Lock
    _bg_shutdown_threads: "set[threading.Thread]"

    # Defined by one mixin, called from another.
    def emit_execution_status(self, record: ExecutionResponse) -> None: ...

    def _get_owned(self, execution_id: str, user_id: Optional[str]) -> ExecutionResponse:
        raise NotImplementedError

    def _get_active_execution_id(self) -> Optional[str]: ...

    def _record_top_level_error(self, execution_id: str, exception: Exception) -> None: ...

    def _notify_log(self, execution_id: str) -> None: ...
