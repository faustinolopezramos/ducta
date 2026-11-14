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

The variables themselves now live in :mod:`ducta.core.execution_context` so that
``core`` can tag its log lines with the current node without importing ``api``.
They are re-exported here because the API side has always referred to them by this
path — and because both layers must share the *same* ContextVar objects for the
tagging to be visible across the boundary.
"""

from __future__ import annotations

from ducta.core.execution_context import execution_id_var, node_id_var

__all__ = ["execution_id_var", "node_id_var"]
