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

from typing import Any, Dict, Optional

from ducta.api.models.execution import (
    StreamingNodeStatus,
    StreamingPipelineStatus,
    StreamingStatusResponse,
)
from ducta.stream.node_state import derive_node_state, finite_number, node_names


def _text(value: Any) -> Optional[str]:
    return None if value in (None, "") else str(value)


def _node_status(node: str, snapshot: Dict[str, Any]) -> StreamingNodeStatus:
    state = derive_node_state(node, snapshot)
    summary = (snapshot.get("node_summaries") or {}).get(node) or {}
    return StreamingNodeStatus(
        node=node,
        state=state.state,
        error=state.error,
        source=_text(summary.get("source")),
        sink=_text(summary.get("sink")),
        trigger=_text(summary.get("trigger")),
        checkpoint=_text(summary.get("checkpoint")),
        health=state.health,
        idle_seconds=state.idle_seconds,
        last_batch_id=state.last_batch_id,
        num_input_rows=state.num_input_rows,
        input_rows_per_second=state.input_rows_per_second,
        processed_rows_per_second=state.processed_rows_per_second,
        trigger_execution_ms=state.trigger_execution_ms,
        model=(snapshot.get("served_models") or {}).get(node),
    )


def pipeline_status(snapshot: Dict[str, Any]) -> StreamingPipelineStatus:
    """One entry of ``PipelineExecutor.streaming_snapshot()`` for the API."""
    nodes = node_names(snapshot)
    return StreamingPipelineStatus(
        stream_execution_id=str(snapshot.get("execution_id") or ""),
        pipeline_name=_text(snapshot.get("pipeline_name")),
        status=str(snapshot.get("status") or "unknown"),
        uptime_seconds=finite_number(snapshot.get("uptime_seconds")),
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
