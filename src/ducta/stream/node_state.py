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

# One node of a running stream, read out of the manager's status snapshot: the same
# reading for the CLI's live table and the API, so both call a quiet source "idle" and
# a hung one "stalled" alike.

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Optional

#: An active query that has reported no input rows for this long is called idle.
IDLE_AFTER_SECONDS = 60.0


def finite_number(value: Any) -> Optional[float]:
    """A finite float, or None: Spark reports NaN rates before the first batch."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _text(value: Any) -> Optional[str]:
    return None if value in (None, "") else str(value)


@dataclass
class NodeState:
    node: str
    #: active · failed · skipped (never started) · stopped
    state: str
    error: Optional[str] = None
    #: "stalled" (no progress report: a hang) or "idle" (no input rows for a while:
    #: a quiet source). Only for an active query.
    health: Optional[str] = None
    last_batch_id: Optional[int] = None
    num_input_rows: Optional[float] = None
    input_rows_per_second: Optional[float] = None
    processed_rows_per_second: Optional[float] = None
    trigger_execution_ms: Optional[float] = None
    idle_seconds: Optional[float] = None


def derive_node_state(node: str, snapshot: Dict[str, Any]) -> NodeState:
    """The state of *node* in a ``StreamingPipelineManager.get_pipeline_status`` snapshot."""
    query = (snapshot.get("query_statuses") or {}).get(node) or {}
    health = (snapshot.get("health_monitors") or {}).get(node) or {}
    progress = (snapshot.get("progress_metrics") or {}).get(node) or {}
    failed = snapshot.get("failed_nodes") or {}
    skipped = snapshot.get("skipped_nodes") or {}

    error = _text(query.get("exception") or query.get("error") or failed.get(node))
    health_error = _text(health.get("error"))
    error = error or health_error
    if query.get("isActive"):
        state = "active"
    elif error:
        state = "failed"
    elif node in skipped:
        state = "skipped"
        error = _text(skipped.get(node))
    else:
        state = "stopped"

    idle = finite_number(progress.get("idleSeconds"))
    node_health: Optional[str] = None
    if state == "active":
        if "stalled" in (health_error or "").lower():
            node_health = "stalled"
            # A stall is a warning on a query that still runs, not a failure of it.
            error = None if error == health_error else error
        elif idle is not None and idle >= IDLE_AFTER_SECONDS:
            node_health = "idle"

    batch_number = finite_number(progress.get("batchId", health.get("last_batch_id")))
    return NodeState(
        node=node,
        state=state,
        error=error,
        health=node_health,
        last_batch_id=None if batch_number is None else int(batch_number),
        num_input_rows=finite_number(progress.get("numInputRows")),
        input_rows_per_second=finite_number(progress.get("inputRowsPerSecond")),
        processed_rows_per_second=finite_number(progress.get("processedRowsPerSecond")),
        trigger_execution_ms=finite_number(progress.get("triggerExecutionMs")),
        idle_seconds=idle,
    )


def node_names(snapshot: Dict[str, Any]) -> list:
    """Every node the snapshot knows, started or not: in pipeline order (upstream first)
    when the snapshot carries it, else alphabetical."""
    names = (
        set(snapshot.get("query_statuses") or {})
        | set(snapshot.get("failed_nodes") or {})
        | set(snapshot.get("skipped_nodes") or {})
    )
    order = {name: i for i, name in enumerate(snapshot.get("node_order") or [])}
    return sorted(names, key=lambda n: (order.get(n, len(order)), n))
