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

MEDALLION_LAYERS = ("bronze", "silver", "gold")


class DatasetRef(BaseModel):
    """A node's reference to a dataset, with the registry entry resolved."""

    name: str = Field(description="Reference name, as declared on the node")
    declared: bool = Field(
        description="False when no registry entry exists for this name — the "
        "reference is dangling and nothing downstream can know its format"
    )
    format: Optional[str] = Field(
        default=None, description="Declared format (parquet, delta, csv, json, kafka, kinesis)"
    )
    path: Optional[str] = Field(
        default=None, description="Declared filepath, with ${VAR} placeholders left intact"
    )
    write_mode: Optional[str] = Field(
        default=None, description="Write mode for outputs (overwrite, append, ignore, error, merge)"
    )
    schema_: Optional[str] = Field(
        default=None,
        alias="schema",
        description="Declared schema definition (DDL or Pydantic path)",
    )
    layer: Optional[str] = Field(
        default=None, description="Medallion layer read from the name's namespace"
    )
    options: Optional[Dict[str, Any]] = Field(
        default=None, description="Format-specific options from the registry"
    )

    model_config = {"populate_by_name": True}


class DatasetEndpoint(BaseModel):
    """One end of a dataset's wiring: a node, and the pipeline it belongs to."""

    node: str = Field(description="Node name")
    pipeline: Optional[str] = Field(
        default=None, description="Pipeline that declares the node, when known"
    )


class DatasetResponse(BaseModel):
    """A dataset as a first-class resource: identity, storage and wiring."""

    name: str = Field(description="Reference name used by nodes")
    layer: Optional[str] = Field(
        default=None, description="Medallion layer, when the name declares one"
    )
    format: Optional[str] = Field(
        default=None, description="Declared format, or null when undeclared"
    )
    path: Optional[str] = Field(default=None, description="Declared filepath with ${VAR} intact")
    write_mode: Optional[str] = Field(default=None, description="Declared write mode")
    schema_: Optional[str] = Field(default=None, alias="schema", description="Declared schema")
    options: Optional[Dict[str, Any]] = Field(default=None, description="Format-specific options")
    declared_in: List[str] = Field(
        default_factory=list,
        description="Which registries declare it: 'input', 'output', or both",
    )
    producers: List[DatasetEndpoint] = Field(
        default_factory=list, description="Nodes that write this dataset"
    )
    consumers: List[DatasetEndpoint] = Field(
        default_factory=list, description="Nodes that read this dataset"
    )
    description: Optional[str] = Field(default=None, description="The catalog entry's description")
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="The catalog entry's metadata (owner, tags, sla, pii, criticality, docs…)",
    )

    model_config = {"populate_by_name": True}


class DatasetListResponse(BaseModel):
    """Every dataset referenced or declared within a project."""

    project_id: str
    datasets: List[DatasetResponse]
    count: int


def medallion_layer(name: str) -> Optional[str]:
    """Return the medallion layer encoded in *name*'s namespace, if any."""
    head = name.split(".")[0].strip().lower()
    return head if head in MEDALLION_LAYERS else None
