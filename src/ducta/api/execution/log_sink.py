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

import logging
from typing import Any, Optional

from ducta.api.execution.context import execution_id_var
from ducta.api.execution.output_capture import node_status_re
from ducta.api.execution.resilience_helpers import get_current_node_id
from ducta.api.models.execution import LogEntry

__all__ = ["make_log_filter", "make_log_sink"]

_internal_logger = logging.getLogger("ducta.api.execution.log_sink")


def _current_execution_id(get_active_id: Any) -> Optional[str]:  # noqa: ANN001
    return execution_id_var.get() or get_active_id()


def make_log_filter(get_active_id: Any, log_manager: Any):  # noqa: ANN001
    """Return a loguru filter function bound to *log_manager*."""

    def _log_filter(record: dict) -> bool:  # type: ignore[type-arg]
        exec_id = _current_execution_id(get_active_id)
        return exec_id is not None and log_manager.get_buffer(exec_id) is not None

    return _log_filter


def make_log_sink(get_active_id: Any, log_manager: Any, on_append: Any = None):  # noqa: ANN001
    """Return a loguru sink function bound to *log_manager*."""

    def _log_sink(message: Any) -> None:
        exec_id = _current_execution_id(get_active_id)
        if exec_id is None:
            return

        record = message.record
        msg: str = record["message"]
        # No `render: "cli"` / `display_message` here: this sink carries the
        # app's own structured log calls (logger.info/.warning/etc. across the
        # whole codebase) — the vast majority of what a run actually emits.
        # It used to bake each one into a synthetic ANSI-colored terminal
        # line ("ducta: [HH:MM:SS] LEVEL   message") and force the frontend's
        # raw-CLI rendering path for it, which meant virtually every log line
        # a user saw was a dense terminal dump regardless of how the
        # structured row was designed — the redesigned row (level dot,
        # elapsed-time column, sans chrome) never actually showed up. Genuine
        # external process/stdout output (ProcessOutputCapture, which can
        # contain arbitrary formatting we can't structure) still opts into
        # `render: "cli"` itself in manager_streaming.py; this sink no longer
        # does it on that path's behalf.
        entry = LogEntry(
            timestamp=record["time"],
            level=record["level"].name,
            message=msg,
        )

        m = node_status_re.match(msg)
        if m:
            entry.extra.update(
                {
                    "type": "node_status",
                    "node_id": m.group(1),
                    "status": m.group(2),
                }
            )
        else:
            node_id = get_current_node_id()
            if node_id:
                entry.extra["node_id"] = node_id

        near_capacity = log_manager.append_log(exec_id, entry)
        if on_append is not None:
            on_append(exec_id)
        if near_capacity:
            _internal_logger.warning("Execution %s: log buffer approaching capacity", exec_id)

    return _log_sink
