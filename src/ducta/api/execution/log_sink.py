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
from ducta.api.execution.output_capture import format_cli_log_line, node_status_re
from ducta.api.models.execution import LogEntry

__all__ = ["make_log_filter", "make_log_sink"]

_internal_logger = logging.getLogger("ducta.api.execution.log_sink")


def make_log_filter(get_active_id: Any, log_manager: Any):  # noqa: ANN001
    """Return a loguru filter function bound to *log_manager*."""

    def _log_filter(record: dict) -> bool:  # type: ignore[type-arg]
        exec_id: Optional[str] = execution_id_var.get() or get_active_id()
        return exec_id is not None and log_manager.get_buffer(exec_id) is not None

    return _log_filter


def make_log_sink(get_active_id: Any, log_manager: Any, on_append: Any = None):  # noqa: ANN001
    """Return a loguru sink function bound to *log_manager*."""

    def _log_sink(message: Any) -> None:
        exec_id: Optional[str] = execution_id_var.get() or get_active_id()
        if exec_id is None:
            return

        record = message.record
        msg: str = record["message"]
        entry = LogEntry(
            timestamp=record["time"],
            level=record["level"].name,
            message=msg,
            extra={
                "render": "cli",
                "display_message": format_cli_log_line(
                    record["time"],
                    record["level"].name,
                    msg,
                ),
            },
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
            try:
                from ducta.api.execution.resilience_helpers import get_current_node_id

                node_id = get_current_node_id()
            except Exception:  # noqa: BLE001
                node_id = None
            if node_id:
                entry.extra["node_id"] = node_id

        near_capacity = log_manager.append_log(exec_id, entry)
        if on_append is not None:
            on_append(exec_id)
        if near_capacity:
            _internal_logger.warning("Execution %s: log buffer approaching capacity", exec_id)

    return _log_sink
