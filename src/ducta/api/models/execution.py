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

import re
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, PrivateAttr, field_validator

_DATE_RE = re.compile(r"^\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])$")


class ExecutionStatus(str, Enum):
    """Possible states of a pipeline execution."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"
    #: An atomic ``--node`` run whose inputs were not available. Nothing ran, and
    #: nothing was supposed to.
    SKIPPED = "skipped"
    #: At least one node's quality gate rejected its data. The run finished
    #: without an error, but it did not do all of its work. Distinct from SKIPPED
    #: (data absent) and from FAILED (something broke); mirrors
    #: ``ducta.core.results.RunStatus.GATE_BLOCKED``.
    GATE_BLOCKED = "gate_blocked"


class ExecutionResponse(BaseModel):
    """Response model for a pipeline execution record."""

    id: str = Field(description="Unique execution identifier (UUID)")
    pipeline_name: str = Field(description="Name of the executed pipeline")
    user_id: Optional[str] = Field(
        default=None, description="ID of the user that started the execution (ownership)"
    )
    project_id: Optional[str] = Field(default=None, description="Project that owns the pipeline")
    node_name: Optional[str] = Field(default=None, description="Specific node executed, if any")
    env: str = Field(description="Environment used for execution")
    status: ExecutionStatus = Field(description="Current execution status")
    dry_run: bool = Field(default=False, description="True if this was a dry-run")
    model_version: Optional[str] = Field(
        default=None, description="Model version used for ML pipelines, if any"
    )
    sweep_id: Optional[str] = Field(
        default=None, description="Sweep group identifier when part of a hyperparameter sweep"
    )
    sweep_index: Optional[int] = Field(
        default=None, description="1-based index of this run within its sweep"
    )
    started_at: Optional[datetime] = Field(default=None)
    finished_at: Optional[datetime] = Field(default=None)
    exit_code: Optional[int] = Field(default=None, description="Process exit code")
    duration_seconds: Optional[float] = Field(default=None)
    error_message: Optional[str] = Field(
        default=None, description="Error message if status is FAILED"
    )
    certificate_run_id: Optional[str] = Field(
        default=None,
        description=(
            "run_id of the Run Certificate emitted by this execution "
            "(fetch it via /projects/{project_id}/certificates/{run_id})"
        ),
    )


class LogEntry(BaseModel):
    """A single log line from a pipeline execution."""

    timestamp: datetime
    level: str
    message: str
    extra: Dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "allow"}

    # Memoized JSON-mode serialization. Log entries are immutable once created
    # and appended to the buffer, so the dict can be cached and reused across
    # every WebSocket client streaming the same execution — turning per-entry
    # serialization from O(entries x clients) into O(entries).
    _serialized: Optional[Dict[str, Any]] = PrivateAttr(default=None)

    def as_serialized_dict(self) -> Dict[str, Any]:
        """Return the cached ``model_dump(mode="json")`` dict, computing it once."""
        if self._serialized is None:
            self._serialized = self.model_dump(mode="json")
        return self._serialized


class ExecuteRequest(BaseModel):
    """Request body for POST /api/pipelines/{name}/execute."""

    env: str = Field(
        default="base",
        description="Environment to use when loading the Ducta context.",
    )
    node_name: Optional[str] = Field(
        default=None,
        description="Specific node within the pipeline to execute (optional).",
    )
    dry_run: bool = Field(
        default=False,
        description="If True, simulate execution without writing output.",
    )
    validate_only: bool = Field(
        default=False,
        description="If True, validate pipeline structure and syntax without executing.",
    )
    sanity_only: bool = Field(
        default=False,
        description="If True, run node input sanity checks without executing the pipeline.",
    )
    start_date: Optional[str] = Field(
        default=None,
        description="Start date passed to the pipeline executor (YYYY-MM-DD).",
    )
    end_date: Optional[str] = Field(
        default=None,
        description="End date passed to the pipeline executor (YYYY-MM-DD).",
    )
    model_version: Optional[str] = Field(
        default=None,
        description="Model version for ML pipelines.",
    )
    hyperparams: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Hyperparameters passed to the pipeline executor.",
    )
    reuse_upstream: bool = Field(
        default=False,
        description="If True, reuse materialized outputs from upstream nodes.",
    )
    rerun_all: bool = Field(
        default=False,
        description="If True, force re-execution of all upstream nodes in the DAG.",
    )

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def _validate_date_format(cls, v: Optional[str]) -> Optional[str]:
        """Reject any value that is not a valid YYYY-MM-DD string."""
        if v is None:
            return v
        if not isinstance(v, str):
            raise ValueError("date must be a string in YYYY-MM-DD format")
        if not _DATE_RE.match(v):
            raise ValueError(f"'{v}' is not a valid date (expected YYYY-MM-DD)")
        # Verify it's an actual calendar date (regex alone allows e.g. Feb 31)
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError(f"'{v}' is not a valid calendar date")
        return v


class SweepRequest(BaseModel):
    """Request body for launching a hyperparameter sweep.

    Expands ``sweep`` (a mapping of param → list of values) into the cartesian
    product and enqueues one execution per combination, all tagged with a shared
    ``sweep_id``.
    """

    env: str = Field(default="base", description="Environment to use.")
    node_name: Optional[str] = Field(default=None, description="Specific node to execute.")
    start_date: Optional[str] = Field(default=None, description="Start date (YYYY-MM-DD).")
    end_date: Optional[str] = Field(default=None, description="End date (YYYY-MM-DD).")
    model_version: Optional[str] = Field(
        default=None, description="Model version for ML pipelines."
    )
    base_hyperparams: Optional[Dict[str, Any]] = Field(
        default=None, description="Hyperparameters merged into every sweep combination."
    )
    sweep: Dict[str, Any] = Field(
        description="Sweep spec: mapping of hyperparameter name to a list of candidate values."
    )

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def _validate_date_format(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not isinstance(v, str) or not _DATE_RE.match(v):
            raise ValueError(f"'{v}' is not a valid date (expected YYYY-MM-DD)")
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError(f"'{v}' is not a valid calendar date")
        return v


class SweepResponse(BaseModel):
    """Response for a launched sweep: the group id and its queued executions."""

    sweep_id: str = Field(description="Shared identifier for all runs in the sweep")
    total: int = Field(description="Number of executions queued")
    executions: List[ExecutionResponse] = Field(
        description="Queued executions, one per combination"
    )


class ExecutionListResponse(BaseModel):
    """Response for GET /api/executions."""

    executions: List[ExecutionResponse]
    count: int
    total: int = Field(default=0, description="Total number of executions")
    skip: int = Field(default=0, description="Number of records skipped")
    limit: int = Field(default=0, description="Maximum number of records returned")


class QueueStatusResponse(BaseModel):
    """Response for GET /api/executions/queue."""

    running: int = Field(description="Number of currently running executions")
    queued: int = Field(description="Number of executions waiting in queue")
    max_concurrent: int = Field(description="Maximum allowed concurrent executions")
    total_queued: int = Field(default=0, description="Lifetime total executions queued")
    total_completed: int = Field(default=0, description="Lifetime total executions completed")


class BulkCancelRequest(BaseModel):
    """Request body for POST /api/executions/bulk-cancel."""

    # Unbounded list let a single request enumerate an arbitrary number of
    # IDs to process — 1000 is far beyond any realistic bulk-cancel batch.
    execution_ids: List[str] = Field(description="Execution IDs to cancel", max_length=1000)


class BulkCancelResponse(BaseModel):
    """Response for POST /api/executions/bulk-cancel."""

    cancelled: List[str] = Field(default_factory=list, description="IDs that were cancelled")
    skipped: List[str] = Field(
        default_factory=list, description="IDs that were not cancellable (already terminal/unknown)"
    )


class ExecutionErrorDetail(BaseModel):
    """A single categorized failure with its full Python traceback."""

    timestamp: str = Field(description="ISO-8601 timestamp of the failure")
    node_id: Optional[str] = Field(default=None, description="Node that failed, if any")
    node_type: Optional[str] = Field(default=None, description="Node type (source/transform/ml/…)")
    attempt: int = Field(default=1, description="Attempt number at the time of failure")
    error_type: str = Field(description="Exception class name (e.g. ValueError)")
    message: str = Field(description="Exception message")
    category: str = Field(
        description="Error category: temporary/permanent/resource/configuration/timeout/cancelled/unknown"
    )
    traceback: str = Field(description="Formatted Python traceback (full)")
    traceback_lines: List[str] = Field(
        default_factory=list, description="Last traceback lines (frame summary)"
    )
    hint: Optional[str] = Field(
        default=None, description="What to look at first for this category of failure"
    )


class ExecutionErrorsResponse(BaseModel):
    """Response for GET /api/executions/{id}/errors."""

    execution_id: str
    error_count: int
    warning_count: int
    has_critical_errors: bool = Field(
        default=False, description="True when any error is permanent (needs manual intervention)"
    )
    errors: List[ExecutionErrorDetail] = Field(default_factory=list)
    warnings: List[Dict[str, Any]] = Field(default_factory=list)


class StreamingNodeStatus(BaseModel):
    """One streaming node of a running execution: its query, throughput and model."""

    node: str
    #: active · failed · skipped (never started) · stopped
    state: str
    error: Optional[str] = None
    last_batch_id: Optional[int] = None
    num_input_rows: Optional[float] = None
    input_rows_per_second: Optional[float] = None
    processed_rows_per_second: Optional[float] = None
    trigger_execution_ms: Optional[float] = None
    #: The model the query was pinned to when it started (`model:` on the node).
    model: Optional[Dict[str, Any]] = None


class StreamingPipelineStatus(BaseModel):
    """A streaming (or hybrid) pipeline an execution is running."""

    stream_execution_id: str
    pipeline_name: Optional[str] = None
    status: str
    uptime_seconds: Optional[float] = None
    total_queries: int = 0
    active_queries: int = 0
    failed_queries: int = 0
    error: Optional[str] = None
    nodes: List[StreamingNodeStatus] = Field(default_factory=list)


class StreamingStatusResponse(BaseModel):
    """`GET /executions/{id}/streaming`: the live state of an execution's streams."""

    execution_id: str
    #: False once the execution no longer holds a running engine.
    active: bool
    pipelines: List[StreamingPipelineStatus] = Field(default_factory=list)
