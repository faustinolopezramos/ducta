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

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class IOItem(BaseModel):
    """One side of a node's dataset wiring, with the registry entry resolved."""

    id: str = Field(description="Stable port id, used to anchor canvas edges")
    name: str = Field(description="Dataset reference name, as declared on the node")
    declared: bool = Field(
        default=False,
        description="False when no registry entry exists for this reference name",
    )
    format: Optional[str] = Field(default=None, description="Declared format, or null")
    path: Optional[str] = Field(
        default=None, description="Declared filepath, with ${VAR} placeholders intact"
    )
    write_mode: Optional[str] = Field(
        default=None, description="Declared write mode (outputs only)"
    )
    schema_: Optional[Dict[str, Any]] | Optional[str] = Field(
        default=None, alias="schema", description="Declared schema definition"
    )
    layer: Optional[str] = Field(
        default=None, description="Medallion layer read from the reference's namespace"
    )
    description: Optional[str] = None

    model_config = {"populate_by_name": True}


class QualityInfo(BaseModel):
    """Quality checks and gate configured on a node."""

    check_count: int = Field(default=0, description="Number of enabled checks")
    gate_behavior: Optional[str] = Field(
        default=None,
        description="Gate behavior when a gate is enabled (e.g. skip_downstream)",
    )
    is_sanity: bool = Field(
        default=False, description="True when the checks run before the node rather than after"
    )


class NodeSchemaResponse(BaseModel):
    """Enriched schema response for a node with full details."""

    name: str
    node_id: str
    type: str
    module: str
    fn: str = Field(default="execute")
    description: Optional[str] = None

    # Input/Output specifications, resolved against the dataset registries
    inputs: List[IOItem] = Field(default_factory=list)
    outputs: List[IOItem] = Field(default_factory=list)

    # Dependencies
    dependencies: List[str] = Field(
        default_factory=list, description="Node IDs this node depends on"
    )

    # File information
    file_path: str = Field(description="Relative path to source file")
    file_size_bytes: Optional[int] = None
    file_exists: bool = Field(default=True, description="Whether the Python source file exists")

    # Quality checks and gate
    quality: Optional[QualityInfo] = Field(
        default=None, description="Quality/sanity checks and gate, when configured"
    )

    # Execution hints
    last_execution_status: Optional[str] = None
    last_execution_time: Optional[str] = None
    last_execution_duration: Optional[float] = None
    last_execution_error_message: Optional[str] = None


class PipelineNodeSchemaResponse(BaseModel):
    """Schema response for a node within a pipeline context."""

    project_id: str
    pipeline_name: str
    node: NodeSchemaResponse
