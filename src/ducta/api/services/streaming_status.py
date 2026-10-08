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

# The streaming manager's status snapshot, as the API shows it: per node, the
# query's state, its latest batch's throughput and the model it scores with.
# The snapshot itself carries Spark progress objects and the pipeline's config;
# none of that leaves the server.

import math
from typing import Any, Dict, Optional

from ducta.api.models.execution import (
    StreamingNodeStatus,
    StreamingPipelineStatus,
    StreamingStatusResponse,
)


def _number(value: Any) -> Optional[float]:
    """A finite float, or None: Spark reports NaN rates before the first batch."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _text(value: Any) -> Optional[str]:
    return None if value in (None, "") else str(value)


def _node_status(node: str, snapshot: Dict[str, Any]) -> StreamingNodeStatus:
    query = (snapshot.get("query_statuses") or {}).get(node) or {}
    health = (snapshot.get("health_monitors") or {}).get(node) or {}
    progress = (snapshot.get("progress_metrics") or {}).get(node) or {}
    failed = snapshot.get("failed_nodes") or {}
    skipped = snapshot.get("skipped_nodes") or {}

    error = _text(query.get("exception") or query.get("error") or failed.get(node))
    error = error or _text(health.get("error"))
    if query.get("isActive"):
        state = "active"
    elif error:
        state = "failed"
    elif node in skipped:
        state = "skipped"
        error = _text(skipped.get(node))
    else:
        state = "stopped"

    batch = progress.get("batchId", health.get("last_batch_id"))
    return StreamingNodeStatus(
        node=node,
        state=state,
        error=error,
        last_batch_id=int(batch) if _number(batch) is not None else None,
        num_input_rows=_number(progress.get("numInputRows")),
        input_rows_per_second=_number(progress.get("inputRowsPerSecond")),
        processed_rows_per_second=_number(progress.get("processedRowsPerSecond")),
        trigger_execution_ms=_number(progress.get("triggerExecutionMs")),
        model=(snapshot.get("served_models") or {}).get(node),
    )


def pipeline_status(snapshot: Dict[str, Any]) -> StreamingPipelineStatus:
    """One entry of ``PipelineExecutor.streaming_snapshot()`` for the API."""
    nodes = sorted(
        set(snapshot.get("query_statuses") or {})
        | set(snapshot.get("failed_nodes") or {})
        | set(snapshot.get("skipped_nodes") or {})
    )
    return StreamingPipelineStatus(
        stream_execution_id=str(snapshot.get("execution_id") or ""),
        pipeline_name=_text(snapshot.get("pipeline_name")),
        status=str(snapshot.get("status") or "unknown"),
        uptime_seconds=_number(snapshot.get("uptime_seconds")),
        total_queries=int(snapshot.get("total_queries") or 0),
        active_queries=int(snapshot.get("active_queries") or 0),
        failed_queries=int(snapshot.get("failed_queries") or 0),
        error=_text(snapshot.get("error")),
        nodes=[_node_status(node, snapshot) for node in nodes],
    )


def streaming_status(execution_id: str, engine: Any) -> StreamingStatusResponse:
    """The streams ``engine`` is running for ``execution_id`` (none without an engine)."""
    if engine is None:
        return StreamingStatusResponse(execution_id=execution_id, active=False)
    snapshot = engine.streaming_snapshot() if hasattr(engine, "streaming_snapshot") else []
    return StreamingStatusResponse(
        execution_id=execution_id,
        active=True,
        pipelines=[pipeline_status(s) for s in snapshot],
    )
