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

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class RunStatus(str, Enum):
    """Terminal state of a pipeline run."""

    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    GATE_BLOCKED = "gate_blocked"
    RUNNING = "running"


class NodeStatus(str, Enum):
    """Outcome of a single node within a run."""

    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    GATE_BLOCKED = "gate_blocked"


@dataclass
class NodeOutcome:
    """What happened to one node."""

    name: str
    status: NodeStatus = NodeStatus.SUCCESS
    node_type: str = "batch"
    duration_seconds: float = 0.0
    outputs: List[str] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.status is NodeStatus.SUCCESS

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data

    @classmethod
    def from_trace(cls, record: Dict[str, Any]) -> "NodeOutcome":
        """Build from a ``context._run_node_details`` entry."""
        raw_status = str(record.get("status", "success"))
        try:
            status = NodeStatus(raw_status)
        except ValueError:
            status = NodeStatus.FAILED if record.get("error") else NodeStatus.SUCCESS
        return cls(
            name=str(record.get("name", "")),
            status=status,
            node_type=str(record.get("type", "batch")),
            duration_seconds=float(record.get("duration_seconds") or 0.0),
            outputs=list(record.get("outputs") or []),
            error=record.get("error"),
        )


@dataclass
class PipelineRunResult:
    """Everything one ``run_pipeline`` call produced."""

    pipeline: str
    status: RunStatus = RunStatus.SUCCESS
    run_id: Optional[str] = None
    nodes: List[NodeOutcome] = field(default_factory=list)
    streaming_execution_ids: List[str] = field(default_factory=list)
    gate_blocked: Dict[str, Any] = field(default_factory=dict)
    skipped: Dict[str, str] = field(default_factory=dict)
    reused_pipelines: List[str] = field(default_factory=list)
    certificate_path: Optional[str] = None
    errors: List[str] = field(default_factory=list)
    mlops_run_id: Optional[str] = None
    metrics: Dict[str, float] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """True only for a run that completed all of its work."""
        return self.status is RunStatus.SUCCESS

    @property
    def failed(self) -> bool:
        return self.status is RunStatus.FAILED

    def __bool__(self) -> bool:
        return self.ok

    @property
    def failed_nodes(self) -> List[NodeOutcome]:
        return [n for n in self.nodes if n.status is NodeStatus.FAILED]

    @property
    def primary_error(self) -> Optional[str]:
        """The first recorded error, for a one-line report."""
        if self.errors:
            return self.errors[0]
        for node in self.nodes:
            if node.error:
                return f"node '{node.name}': {node.error}"
        return None

    def add_error(self, message: str) -> "PipelineRunResult":
        """Record an error and mark the run failed."""
        self.errors.append(message)
        self.status = RunStatus.FAILED
        return self

    def absorb_trace(self, trace: Optional[List[Dict[str, Any]]]) -> "PipelineRunResult":
        """Populate ``nodes`` from the executor's per-node trace records."""
        for record in trace or []:
            if isinstance(record, dict):
                self.nodes.append(NodeOutcome.from_trace(record))
        self.nodes.sort(key=lambda n: n.name)
        return self

    def resolve_status(self) -> "PipelineRunResult":
        """Derive the run status from what was recorded, unless already failed.

        Precedence: an explicit failure wins, then a gate block, then a skip.
        A gate block outranks a skip because it means data was rejected, while
        a skip means data was merely absent.
        """
        if self.status is RunStatus.FAILED or self.errors or self.failed_nodes:
            self.status = RunStatus.FAILED
        elif self.gate_blocked:
            self.status = RunStatus.GATE_BLOCKED
        elif self.skipped and not self.nodes:
            self.status = RunStatus.SKIPPED
        return self

    def to_dict(self) -> Dict[str, Any]:
        """JSON-ready view, for the API and for structured logging."""
        return {
            "pipeline": self.pipeline,
            "status": self.status.value,
            "run_id": self.run_id,
            "nodes": [n.to_dict() for n in self.nodes],
            "streaming_execution_ids": list(self.streaming_execution_ids),
            "gate_blocked": dict(self.gate_blocked),
            "skipped": dict(self.skipped),
            "reused_pipelines": list(self.reused_pipelines),
            "certificate_path": self.certificate_path,
            "errors": list(self.errors),
        }

    def summary(self) -> str:
        """One-line human summary."""
        parts = [f"pipeline '{self.pipeline}': {self.status.value}"]
        if self.nodes:
            ok_count = sum(1 for n in self.nodes if n.ok)
            parts.append(f"{ok_count}/{len(self.nodes)} nodes ok")
        if self.gate_blocked:
            parts.append(f"{len(self.gate_blocked)} gate-blocked")
        if self.skipped:
            parts.append(f"{len(self.skipped)} skipped")
        if self.reused_pipelines:
            parts.append(f"{len(self.reused_pipelines)} reused")
        error = self.primary_error
        if error:
            parts.append(f"error: {error}")
        return " — ".join(parts)
