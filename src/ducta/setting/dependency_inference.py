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

_DEPENDENCY_KEYS = ("dependencies", "depends_on")


def normalize_dependencies(dependencies: Any) -> List[Any]:
    """Normalize dependencies to a consistent list format."""
    if dependencies is None:
        return []
    elif isinstance(dependencies, str):
        return [dependencies]
    elif isinstance(dependencies, dict):
        return list(dependencies.keys())
    elif isinstance(dependencies, list):
        return dependencies
    else:
        return [str(dependencies)]


def extract_dependency_name(dependency: Any) -> str:
    """Extract dependency name from various formats."""
    if isinstance(dependency, str):
        return dependency
    elif isinstance(dependency, dict):
        if len(dependency) != 1:
            raise ValueError(f"Dict dependency must have exactly one key-value pair: {dependency}")
        return next(iter(dependency.keys()))
    elif dependency is None:
        raise ValueError("Dependency cannot be None")
    else:
        raise TypeError(f"Unsupported dependency type: {type(dependency)} - {dependency}")


def extract_pipeline_nodes(pipeline: Dict[str, Any]) -> List[str]:
    """Extract node names from pipeline configuration."""
    pipeline_nodes_raw = pipeline.get("nodes", [])
    pipeline_nodes = []
    for node in pipeline_nodes_raw:
        if isinstance(node, str):
            pipeline_nodes.append(node)
        elif isinstance(node, dict):
            if len(node) == 1:
                pipeline_nodes.append(next(iter(node)))
            elif "name" in node:
                pipeline_nodes.append(node["name"])
            else:
                raise ValueError(f"Invalid node format in pipeline: {node}")
        else:
            pipeline_nodes.append(str(node))
    return pipeline_nodes


def get_node_dependencies(node_config: Dict[str, Any]) -> List[str]:
    """Extract and normalize a node's declared dependencies."""
    normalized_deps: List[str] = []
    seen = set()
    for key in _DEPENDENCY_KEYS:
        for dep in normalize_dependencies(node_config.get(key, [])):
            try:
                dep_name = extract_dependency_name(dep)
            except (TypeError, ValueError) as e:
                logger.error(f"Error processing dependency {dep}: {str(e)}")
                raise
            if dep_name not in seen:
                seen.add(dep_name)
                normalized_deps.append(dep_name)
    return normalized_deps


#: Keys that mark an ``input``/``output`` dict as an inline connector config
#: (a streaming source, say) rather than a ``{param_name: dataset_key}`` map.
#: ``NodeSchema.input`` accepts ``Dict[str, Any]`` for both, so the shapes have
#: to be told apart by content.
_INLINE_CONFIG_MARKERS = frozenset({"format", "options", "schema", "path"})


def extract_input_keys(node_config: Dict[str, Any], *, node: str = "?") -> List[str]:
    """Return the dataset keys a node consumes."""
    keys = (node_config or {}).get("input")
    return _normalize_dataset_keys(keys, node=node, field="input")


def extract_output_keys(node_config: Dict[str, Any], *, node: str = "?") -> List[str]:
    """Return the dataset keys a node produces (``output``), pure and non-raising."""
    keys = (node_config or {}).get("output")
    return _normalize_dataset_keys(keys, node=node, field="output")


def _normalize_dataset_keys(keys: Any, *, node: str = "?", field: str = "input") -> List[str]:
    """Coerce an input/output declaration to a clean list of dataset-key strings."""
    if keys is None:
        return []
    if isinstance(keys, str):
        return [keys.strip()] if keys.strip() else []
    if isinstance(keys, dict):
        if not keys:
            return []
        if _INLINE_CONFIG_MARKERS & {str(k).lower() for k in keys}:
            logger.debug(
                "Node '{}': '{}' is an inline connector config, not dataset "
                "references; no dependency edges inferred from it.",
                node,
                field,
            )
            return []
        if all(isinstance(v, str) and v.strip() for v in keys.values()):
            return [v.strip() for v in keys.values()]
        bad = sorted(k for k, v in keys.items() if not (isinstance(v, str) and v.strip()))
        logger.warning(
            "Node '{}': '{}' is a {{name: dataset_key}} map but {} do(es) not map to a "
            "non-empty string, so no dependency edges can be inferred from it and the "
            "node may be scheduled before whatever produces its data. Fix the "
            "declaration, or move the extra settings out of '{}'.",
            node,
            field,
            bad,
            field,
        )
        return []
    if isinstance(keys, (list, tuple)):
        usable = [k.strip() for k in keys if isinstance(k, str) and k.strip()]
        if len(usable) != len(list(keys)):
            logger.warning(
                "Node '{}': {} entr(y/ies) in '{}' are not non-empty strings and were "
                "ignored for dependency inference.",
                node,
                len(list(keys)) - len(usable),
                field,
            )
        return usable
    logger.warning(
        "Node '{}': '{}' is a {}, which is not a valid dataset declaration "
        "(expected a string, a list, or a {{name: dataset_key}} map); no dependency "
        "edges inferred.",
        node,
        field,
        type(keys).__name__,
    )
    return []


def _dedupe_merge(explicit: List[str], inferred: List[str]) -> List[str]:
    """Explicit entries first, then any inferred entry not already present.

    Shared by ``resolve_node_dependencies`` and ``merge_pipeline_depends_on``,
    which previously each carried an identical copy of this merge loop.
    """
    merged = list(explicit)
    for dep in inferred:
        if dep not in merged:
            merged.append(dep)
    return merged


def build_producer_map(
    pipeline_nodes: List[str], node_configs: Dict[str, Dict[str, Any]]
) -> Dict[str, List[str]]:
    """Map each produced dataset key → the node(s) in *pipeline_nodes* producing it."""
    producers: Dict[str, List[str]] = {}
    for node in pipeline_nodes:
        for out_key in extract_output_keys(node_configs.get(node, {}) or {}, node=node):
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
        for in_key in extract_input_keys(cfg, node=node):
            for producer in producers.get(in_key, []):
                if producer != node and producer not in inferred:
                    inferred.append(producer)

        resolved[node] = _dedupe_merge(explicit, inferred)

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
            produced.update(extract_output_keys(cfg, node=node))
            consumed.update(extract_input_keys(cfg, node=node))
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
    from ducta.setting.pipeline_dependency_resolver import _get_depends_on

    inferred = infer_pipeline_depends_on(pipelines_config, nodes_config)
    merged: Dict[str, List[str]] = {}
    for pname, pcfg in pipelines_config.items():
        explicit = _get_depends_on(pcfg)
        merged[pname] = _dedupe_merge(explicit, inferred.get(pname, []))
    return merged
