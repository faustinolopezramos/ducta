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

from typing import Any, Dict, List, Optional, Set, Tuple

from pydantic import BaseModel, Field

from ducta.api.models.spec import pipeline_node_names
from ducta.api.services.dataset_service import io_names, node_io


class DependencyEdge(BaseModel):
    from_pipeline: str
    from_node: str
    to_pipeline: str
    to_node: str
    dataset: Optional[str] = Field(
        default=None, description="Shared dataset name for dataset-derived edges"
    )
    kind: str = Field(description="'explicit' (node dependencies) or 'dataset' (output→input)")


def build_dependency_graph(
    pipelines: Dict[str, Any], node_specs: Dict[str, Any]
) -> Tuple[Dict[str, List[str]], List[DependencyEdge]]:
    """Node-level edges across a project's pipelines.

    Returns ``(pipeline → node names, edges)``. An edge is either a node's
    declared dependency (``explicit``) or an output→input dataset hand-off
    (``dataset``); a dataset edge that shadows an explicit one is dropped.
    """
    pipeline_nodes: Dict[str, List[str]] = {
        name: pipeline_node_names(spec)
        for name, spec in pipelines.items()
        if isinstance(spec, dict)
    }
    # node name → pipeline (first pipeline that declares it wins)
    node_pipeline: Dict[str, str] = {}
    for pipe, names in pipeline_nodes.items():
        for n in names:
            node_pipeline.setdefault(n, pipe)

    edges: List[DependencyEdge] = []
    seen: Set[Tuple[str, str, Optional[str]]] = set()

    def add_edge(src: str, dst: str, dataset: Optional[str], kind: str) -> None:
        key = (src, dst, dataset if kind == "dataset" else None)
        if src == dst or key in seen:
            return
        seen.add(key)
        edges.append(
            DependencyEdge(
                from_pipeline=node_pipeline[src],
                from_node=src,
                to_pipeline=node_pipeline[dst],
                to_node=dst,
                dataset=dataset,
                kind=kind,
            )
        )

    # dataset name → producing node (only nodes that belong to this project)
    producers: Dict[str, str] = {}
    for node_name in node_pipeline:
        for out in node_io(node_specs.get(node_name) or {}, "output"):
            if out:
                producers.setdefault(out, node_name)

    for node_name in node_pipeline:
        spec = node_specs.get(node_name) or {}
        for dep in io_names(spec.get("dependencies")):
            if dep in node_pipeline:
                add_edge(dep, node_name, None, "explicit")
        for inp in node_io(spec, "input"):
            producer = producers.get(inp)
            if producer and (producer, node_name, None) not in seen:
                add_edge(producer, node_name, inp, "dataset")

    return pipeline_nodes, edges
