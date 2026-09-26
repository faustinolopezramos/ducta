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

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ducta.api.exceptions import ConfigValidationError

PIPELINE_TYPES = ("batch", "ml", "streaming", "hybrid")

ML_STAGES = ("feature_engineering", "training", "evaluation", "serving")


class PipelineSpec(BaseModel):
    """A pipeline specification as stored in a project's ``pipelines.yaml``."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    type: str = Field(
        default="batch",
        description=f"Pipeline type, one of {', '.join(PIPELINE_TYPES)}",
    )
    nodes: List[Union[str, Dict[str, Any]]] = Field(
        default_factory=list,
        description="Node names to execute, in order. May be empty while the "
        "pipeline is still being built.",
    )
    inputs: List[str] = Field(
        default_factory=list, description="Pipeline-level input dataset references"
    )
    outputs: List[str] = Field(
        default_factory=list, description="Pipeline-level output dataset references"
    )
    description: Optional[str] = Field(default=None, description="Human-readable description")
    requires_dates: bool = Field(
        default=True, description="Whether the pipeline requires date parameters"
    )
    depends_on: List[str] = Field(
        default_factory=list,
        description="Pipelines that must complete successfully before this one runs",
    )
    hyperparams: Optional[Dict[str, Any]] = Field(
        default=None, description="ML pipeline hyperparameters"
    )
    model_version: Optional[str] = Field(
        default=None, description="Override the default model version for ML pipelines"
    )
    spark_config: Optional[Dict[str, Any]] = Field(
        default=None, description="Pipeline-specific Spark configuration"
    )
    reuse_if_materialized: Optional[bool] = Field(
        default=None, description="Per-pipeline override for chain reuse"
    )


class NodeSpec(BaseModel):
    """A node specification as stored in a workspace or layer ``nodes.yaml``."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    module: Optional[str] = Field(default=None, description="Python module holding the function")
    function: Optional[Union[str, Dict[str, Any]]] = Field(
        default=None,
        description="Function to execute — a string, or a streaming function spec",
    )
    input: List[Union[str, Dict[str, Any]]] = Field(
        default_factory=list, description="Input dataset references"
    )
    output: List[Union[str, Dict[str, Any]]] = Field(
        default_factory=list, description="Output dataset references"
    )
    dependencies: List[str] = Field(
        default_factory=list, description="Names of nodes this one depends on"
    )
    retry: int = Field(default=0, ge=0, le=10, description="Retry attempts (0-10)")
    timeout: Optional[int] = Field(
        default=None, ge=1, le=86400, description="Execution timeout in seconds"
    )
    description: Optional[str] = Field(default=None, description="Human-readable description")
    ml_stage: Optional[str] = Field(
        default=None, description=f"ML lifecycle stage, one of {', '.join(ML_STAGES)}"
    )
    run_in_process: bool = Field(default=False, description="Run this node in its own process")
    data_quality: Optional[Dict[str, Any]] = Field(
        default=None, description="Post-execution data quality check configuration"
    )
    sanity_checks: Optional[Dict[str, Any]] = Field(
        default=None, description="Pre-execution sanity check configuration"
    )


def _format_errors(exc: ValidationError) -> str:
    """Render pydantic errors as one line naming each offending field."""
    parts = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", ())) or "(root)"
        parts.append(f"{loc}: {err.get('msg', 'invalid')}")
    return "; ".join(parts)


def validate_pipeline_spec(name: str, spec: Dict[str, Any]) -> None:
    """Validate a pipeline spec before it is written to disk."""
    if not isinstance(spec, dict):
        raise ConfigValidationError(
            f"Pipeline '{name}' spec must be a mapping, got {type(spec).__name__}",
            detail={"pipeline": name},
        )
    try:
        parsed = PipelineSpec.model_validate(spec)
    except ValidationError as exc:
        raise ConfigValidationError(
            f"Invalid pipeline spec for '{name}' — {_format_errors(exc)}",
            detail={"pipeline": name},
        )

    if parsed.type not in PIPELINE_TYPES:
        raise ConfigValidationError(
            f"Invalid pipeline type '{parsed.type}' for '{name}'. "
            f"Expected one of: {', '.join(PIPELINE_TYPES)}.",
            detail={"pipeline": name, "type": parsed.type},
        )


def pipeline_node_names(spec: Dict[str, Any]) -> List[str]:
    """The node names a pipeline spec's ``nodes`` list refers to.

    Entries are normally plain strings; a dict entry is named by its ``name``
    (or, failing that, ``id``); a mapping is named by its keys. The single
    rule every caller uses.
    """
    nodes = (spec or {}).get("nodes") or []
    if isinstance(nodes, dict):
        return [str(k) for k in nodes]
    names: List[str] = []
    for entry in nodes:
        if isinstance(entry, str):
            names.append(entry)
        elif isinstance(entry, dict):
            name = entry.get("name") or entry.get("id")
            if isinstance(name, str) and name:
                names.append(name)
    return names


def validate_pipeline(name: str, spec: Dict[str, Any], known_nodes: Dict[str, Any]) -> None:
    """Every check a pipeline spec must pass before it is saved."""
    validate_pipeline_spec(name, spec)
    validate_pipeline_nodes(name, spec, known_nodes)
    check_no_cycles(name, spec, known_nodes)


def validate_pipeline_nodes(name: str, spec: Dict[str, Any], known_nodes: Dict[str, Any]) -> None:
    """Reject a pipeline spec that references a node nowhere in the workspace."""
    missing = sorted(set(pipeline_node_names(spec)) - set(known_nodes))
    if missing:
        raise ConfigValidationError(
            f"Pipeline '{name}' references unknown node(s): {', '.join(missing)}",
            detail={"pipeline": name, "missing_nodes": missing},
        )


def check_no_cycles(name: str, spec: Dict[str, Any], known_nodes: Dict[str, Any]) -> None:
    """Reject a pipeline spec whose nodes form a dependency cycle."""
    pipeline_nodes = set(pipeline_node_names(spec))
    graph: Dict[str, List[str]] = {
        n: [d for d in (known_nodes.get(n, {}).get("dependencies") or []) if d in pipeline_nodes]
        for n in pipeline_nodes
    }

    WHITE, GRAY, BLACK = 0, 1, 2
    color: Dict[str, int] = dict.fromkeys(graph, WHITE)
    path: List[str] = []

    def visit(node: str) -> Optional[List[str]]:
        color[node] = GRAY
        path.append(node)
        for dep in graph.get(node, []):
            if color.get(dep) == GRAY:
                return path[path.index(dep) :] + [dep]
            if color.get(dep, WHITE) == WHITE:
                found = visit(dep)
                if found:
                    return found
        path.pop()
        color[node] = BLACK
        return None

    for start in graph:
        if color[start] == WHITE:
            cycle = visit(start)
            if cycle:
                raise ConfigValidationError(
                    f"Pipeline '{name}' has a dependency cycle: {' -> '.join(cycle)}",
                    detail={"pipeline": name, "cycle": cycle},
                )


def validate_node_spec(name: str, spec: Dict[str, Any]) -> None:
    """Validate a node spec before it is written to disk."""
    if not isinstance(spec, dict):
        raise ConfigValidationError(
            f"Node '{name}' spec must be a mapping, got {type(spec).__name__}",
            detail={"node": name},
        )
    try:
        parsed = NodeSpec.model_validate(spec)
    except ValidationError as exc:
        raise ConfigValidationError(
            f"Invalid node spec for '{name}' — {_format_errors(exc)}",
            detail={"node": name},
        )

    if parsed.ml_stage is not None and parsed.ml_stage not in ML_STAGES:
        raise ConfigValidationError(
            f"Invalid ml_stage '{parsed.ml_stage}' for node '{name}'. "
            f"Expected one of: {', '.join(ML_STAGES)}.",
            detail={"node": name, "ml_stage": parsed.ml_stage},
        )

    fn = parsed.function
    if isinstance(fn, str) and fn and not parsed.module and "." not in fn:
        raise ConfigValidationError(
            f"Node '{name}' function '{fn}' is not addressable: provide 'module' "
            "separately, or use a fully-qualified dotted path.",
            detail={"node": name, "function": fn},
        )
