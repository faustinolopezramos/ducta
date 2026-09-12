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

from functools import lru_cache

from ducta.api.execution.manager_dispatch import (  # noqa: F401 — re-exported, see below
    _DB_TASKS,
    _DispatchMixin,
    _spawn_db_task,
)
from ducta.api.execution.manager_lifecycle import _LifecycleMixin
from ducta.api.execution.manager_reads import _ReadsMixin
from ducta.api.execution.manager_streaming import _StreamingMixin

# `_DB_TASKS`/`_spawn_db_task` now live in manager_dispatch.py (the fire-and-forget
# DB-task bookkeeping is dispatch-specific), but are re-exported here since they were
# previously module-level names on `manager` and existing tests import them from here.


class ExecutionManager(_LifecycleMixin, _DispatchMixin, _ReadsMixin, _StreamingMixin):
    """Application-wide manager for pipeline execution lifecycle.

    Split across four mixins by responsibility — lifecycle (construction,
    startup/shutdown, maintenance), dispatch (submit/cancel/run), reads
    (lookups, filtering, durable DB/file fallback), and streaming (live
    status/log emission, the SSE generator) — kept together here as one
    class since callers depend on a single `ExecutionManager` type and a
    single `get_execution_manager()` singleton.
    """


@lru_cache(maxsize=1)
def get_execution_manager() -> ExecutionManager:
    return ExecutionManager()
