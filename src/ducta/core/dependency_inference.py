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

from typing import Any, Dict, List

from loguru import logger  # type: ignore

from ducta.core.utils import get_node_dependencies


def extract_input_keys(node_config: Dict[str, Any]) -> List[str]:
    """Return the dataset keys a node consumes."""
    keys = (node_config or {}).get("input")
    return _normalize_dataset_keys(keys)


def extract_output_keys(node_config: Dict[str, Any]) -> List[str]:
    """Return the dataset keys a node produces (``output``), pure and non-raising."""
    keys = (node_config or {}).get("output")
    return _normalize_dataset_keys(keys)


def _normalize_dataset_keys(keys: Any) -> List[str]:
    """Coerce an input/output declaration to a clean list of dataset-key strings."""
    if keys is None:
        return []
    if isinstance(keys, str):
        return [keys.strip()] if keys.strip() else []
    if isinstance(keys, dict):
        if keys and all(isinstance(v, str) and v.strip() for v in keys.values()):
            return [v.strip() for v in keys.values()]
        return []
    if isinstance(keys, (list, tuple)):
        return [k.strip() for k in keys if isinstance(k, str) and k.strip()]
    return []


def build_producer_map(
    pipeline_nodes: List[str], node_configs: Dict[str, Dict[str, Any]]
) -> Dict[str, List[str]]:
    """Map each produced dataset key → the node(s) in *pipeline_nodes* producing it."""
    producers: Dict[str, List[str]] = {}
    for node in pipeline_nodes:
        for out_key in extract_output_keys(node_configs.get(node, {}) or {}):
            bucket = producers.setdefault(out_key, [])
            if node not in bucket:
                bucket.append(node)
    return producers


def resolve_node_dependencies(
    pipeline_nodes: List[str],
    node_configs: Dict[str, Dict[str, Any]],
    *,
    warn: bool = True,
) -> Dict[str, List[str]]:
    """Return the merged (explicit ∪ inferred) dependency list for every node."""
    producers = build_producer_map(pipeline_nodes, node_configs)

    resolved: Dict[str, List[str]] = {}
    for node in pipeline_nodes:
        cfg = node_configs.get(node, {}) or {}
        explicit = get_node_dependencies(cfg)

        inferred: List[str] = []
        for in_key in extract_input_keys(cfg):
            for producer in producers.get(in_key, []):
                if producer != node and producer not in inferred:
                    inferred.append(producer)

        merged = list(explicit)
        for dep in inferred:
            if dep not in merged:
                merged.append(dep)
        resolved[node] = merged

        if warn:
            _warn_on_mismatch(node, explicit, inferred)

    return resolved


def _warn_on_mismatch(node: str, explicit: List[str], inferred: List[str]) -> None:
    """Surface disagreements between hand-written and data-derived dependencies."""
    auto_added = [d for d in inferred if d not in explicit]
    if auto_added:
        log = logger.info if explicit else logger.debug
        log(
            "Node '{}': inferred dependency on {} from shared dataset(s); "
            "you can omit it from `dependencies`.",
            node,
            auto_added,
        )

    unbacked = [d for d in explicit if d not in inferred]
    if unbacked:
        logger.debug(
            "Node '{}': declared dependency on {} is not backed by a shared dataset "
            "(ordering-only, or a stale declaration).",
            node,
            unbacked,
        )


def infer_pipeline_depends_on(
    pipelines_config: Dict[str, Any],
    nodes_config: Dict[str, Dict[str, Any]],
) -> Dict[str, List[str]]:
    """Infer inter-pipeline ``depends_on`` from cross-pipeline dataset flow."""
    from ducta.core.utils import extract_pipeline_nodes

    # dataset key → set of pipelines producing it
    producers_by_pipeline: Dict[str, set] = {}
    pipeline_nodes: Dict[str, List[str]] = {}
    pipeline_produced: Dict[str, set] = {}
    pipeline_consumed: Dict[str, set] = {}

    for pname, pcfg in pipelines_config.items():
        nodes = extract_pipeline_nodes(pcfg if isinstance(pcfg, dict) else {"nodes": []})
        pipeline_nodes[pname] = nodes
        produced: set = set()
        consumed: set = set()
        for node in nodes:
            cfg = nodes_config.get(node, {}) or {}
            produced.update(extract_output_keys(cfg))
            consumed.update(extract_input_keys(cfg))
        pipeline_produced[pname] = produced
        pipeline_consumed[pname] = consumed
        for key in produced:
            producers_by_pipeline.setdefault(key, set()).add(pname)

    inferred: Dict[str, List[str]] = {}
    for pname in pipelines_config:
        deps: List[str] = []
        externally_consumed = pipeline_consumed[pname] - pipeline_produced[pname]
        for key in externally_consumed:
            for producer_pipeline in sorted(producers_by_pipeline.get(key, set())):
                if producer_pipeline != pname and producer_pipeline not in deps:
                    deps.append(producer_pipeline)
        inferred[pname] = deps
    return inferred


def merge_pipeline_depends_on(
    pipelines_config: Dict[str, Any],
    nodes_config: Dict[str, Dict[str, Any]],
) -> Dict[str, List[str]]:
    """Return explicit ∪ inferred ``depends_on`` for every pipeline."""
    from ducta.core.pipeline_dependency_resolver import _get_depends_on

    inferred = infer_pipeline_depends_on(pipelines_config, nodes_config)
    merged: Dict[str, List[str]] = {}
    for pname, pcfg in pipelines_config.items():
        explicit = _get_depends_on(pcfg)
        combined = list(explicit)
        for dep in inferred.get(pname, []):
            if dep not in combined:
                combined.append(dep)
        merged[pname] = combined
    return merged
