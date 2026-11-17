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

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ducta.stream.node_state import derive_node_state, finite_number, node_names
from ducta_server.models.execution import (
    StreamingNodeStatus,
    StreamingPipelineStatus,
    StreamingStatusResponse,
)


def _text(value: Any) -> Optional[str]:
    return None if value in (None, "") else str(value)


def _node_status(node: str, snapshot: Dict[str, Any]) -> StreamingNodeStatus:
    state = derive_node_state(node, snapshot)
    summary = (snapshot.get("node_summaries") or {}).get(node) or {}
    micro = (snapshot.get("micro_batches") or {}).get(node) or {}
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
        rows_quarantined=micro.get("rows_quarantined"),
        gate=_text(micro.get("gate")),
        restarts=state.restarts,
        next_restart_in_seconds=state.next_restart_in_seconds,
        watermark=state.watermark,
        state_rows=state.state_rows,
        state_memory_bytes=state.state_memory_bytes,
        late_rows_dropped=state.late_rows_dropped,
        source_lag=state.source_lag,
        sources=state.sources,
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
        run_id=_text(snapshot.get("run_id")),
    )


_UNFINISHED_JOURNAL_STATES = frozenset({"running", "pending", "starting", "active"})


def journal_pipeline_status(run: Dict[str, Any]) -> StreamingPipelineStatus:
    """A stream no engine holds any more, as its journal left it (ducta.stream.journal)."""
    from ducta.stream.journal import summarize

    outcome = run.get("outcome") or {}
    journaled = summarize(Path(run["journal_dir"])) if run.get("journal_dir") else {}
    nodes = []
    for name in run.get("nodes") or sorted(outcome):
        final = outcome.get(name) or {}
        counts = journaled.get(name) or final.get("journal") or {}
        gates = counts.get("gate") or {}
        nodes.append(
            StreamingNodeStatus(
                node=name,
                # An interrupted run never wrote its nodes' outcome.
                state=str(final.get("state") or "unknown"),
                error=_text(final.get("error")),
                sink=_text(final.get("sink")),
                last_batch_id=counts.get("last_batch"),
                rows_quarantined=counts.get("rows_quarantined"),
                gate="block" if gates.get("block") else (next(iter(gates), None)),
            )
        )
    status = str(run.get("status") or "unknown")
    return StreamingPipelineStatus(
        stream_execution_id=str(run.get("execution_id") or ""),
        pipeline_name=_text(run.get("pipeline")),
        status=status,
        error=_text(run.get("error")),
        nodes=nodes,
        run_id=_text(run.get("run_id")),
        from_journal=True,
    )


def journal_lookup(
    source_path: Any, project_id: Optional[str], env: str, pipeline: str, execution_id: str
) -> List[StreamingPipelineStatus]:
    """The journaled stream of API execution *execution_id*, if it left one."""
    from ducta.runs.certificates import env_stream_journal_dir
    from ducta.stream.journal import find_run
    from ducta_server.workspace.manager import WorkspaceManager

    try:
        root = (
            WorkspaceManager(source_path).for_project(project_id).root
            if project_id
            else Path(source_path)
        )
        base = env_stream_journal_dir(Path(root), env)
        run = find_run(str(base), pipeline, api_execution_id=execution_id) if base else None
    except Exception:  # noqa: BLE001 - no journal is an answer, not an error
        return []
    return [journal_pipeline_status(run)] if run else []


def settle_interrupted(
    status: StreamingStatusResponse, run_finished: bool
) -> StreamingStatusResponse:
    """A journal that never recorded an end, for a run that is over, says ``interrupted``.

    Read from the journal means no engine holds the stream. While the run itself is
    still queued or running that can be a moment between phases, so it is left
    alone; once the run is over (or was found orphaned), "running" was a lie the
    stream page showed in green next to every node stopped.
    """
    if status.active or not run_finished:
        return status
    for pipeline in status.pipelines:
        if pipeline.status in _UNFINISHED_JOURNAL_STATES:
            pipeline.status = "interrupted"
    return status


def streaming_status(
    execution_id: str,
    engine: Any,
    from_journal: Optional[Callable[[], List[StreamingPipelineStatus]]] = None,
) -> StreamingStatusResponse:
    """The streams ``engine`` is running for ``execution_id``; without an engine, what
    *from_journal* finds on disk (a finished run, or one a server restart cut off)."""
    if engine is None:
        pipelines = from_journal() if from_journal is not None else []
        return StreamingStatusResponse(execution_id=execution_id, active=False, pipelines=pipelines)
    snapshot = engine.streaming_snapshot() if hasattr(engine, "streaming_snapshot") else []
    return StreamingStatusResponse(
        execution_id=execution_id,
        active=True,
        pipelines=[pipeline_status(s) for s in snapshot],
    )
