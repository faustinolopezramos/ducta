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

Execution context variables propagated from the event loop into worker threads.

asyncio.to_thread() copies the current Context snapshot into the worker thread,
giving each execution thread an isolated view of these variables without manual
set/reset in runner.py.

These live in ``core`` rather than ``api`` on purpose. The executor tags its log
lines with the current node so the API can stream them per node, but ``core`` must
not import ``api`` to do it: importing anything under ``ducta.api`` pulls in the
whole FastAPI surface, and ``core`` is the layer the CLI runs on. Two ContextVars
with no dependencies are the right thing to share; ``ducta.api.execution.context``
re-exports them for the API side.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Optional

execution_id_var: ContextVar[Optional[str]] = ContextVar("ducta_execution_id", default=None)
node_id_var: ContextVar[Optional[str]] = ContextVar("ducta_node_id", default=None)

__all__ = ["execution_id_var", "node_id_var"]
