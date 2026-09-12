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

from collections import deque
from typing import Any, Callable, Dict, List, Optional, Set

from ducta.setting.dependency_resolver import detect_cycles_dfs, kahn_topological_sort


def _get_depends_on(pipeline_cfg: Any) -> List[str]:
    """Extract depends_on from a pipeline config (dict or PipelineSchema)."""
    if isinstance(pipeline_cfg, dict):
        return list(pipeline_cfg.get("depends_on", []) or [])
    return list(getattr(pipeline_cfg, "depends_on", []) or [])


def _deps_getter(
    depends_on_map: Optional[Dict[str, List[str]]],
) -> Callable[[str, Any], List[str]]:
    """Return a ``(name, cfg) -> deps`` resolver."""
    effective = depends_on_map or {}
    return lambda name, cfg: list(effective.get(name, _get_depends_on(cfg)))


class PipelineDependencyResolver:
    """Handles inter-pipeline dependency resolution and topological ordering."""

    @staticmethod
    def validate_pipeline_dependencies(
        pipelines_config: Dict[str, Any],
        depends_on_map: Optional[Dict[str, List[str]]] = None,
    ) -> None:
        """Validate depends_on declarations across all pipelines."""
        deps_of = _deps_getter(depends_on_map)
        pipeline_names = set(pipelines_config.keys())

        for name, cfg in pipelines_config.items():
            for dep in deps_of(name, cfg):
                if dep == name:
                    raise ValueError(f"Pipeline '{name}' cannot depend on itself.")
                if dep not in pipeline_names:
                    raise ValueError(
                        f"Pipeline '{name}' depends on '{dep}' which does not exist. "
                        f"Available pipelines: {sorted(pipeline_names)}"
                    )

        graph: Dict[str, List[str]] = {
            name: deps_of(name, cfg) for name, cfg in pipelines_config.items()
        }
        detect_cycles_dfs(graph)

    @staticmethod
    def resolve_execution_chain(
        target: str,
        pipelines_config: Dict[str, Any],
        depends_on_map: Optional[Dict[str, List[str]]] = None,
    ) -> List[str]:
        """Return the ordered list of pipelines to execute to satisfy *target*."""
        deps_of = _deps_getter(depends_on_map)

        ancestors: Set[str] = set()
        queue: deque = deque([target])
        while queue:
            current = queue.popleft()
            for dep in deps_of(current, pipelines_config.get(current, {})):
                if dep not in ancestors:
                    ancestors.add(dep)
                    queue.append(dep)

        config_order = {name: idx for idx, name in enumerate(pipelines_config)}
        fallback_rank = len(config_order)
        subgraph_names = sorted(
            ancestors | {target},
            key=lambda name: (config_order.get(name, fallback_rank), name),
        )

        subgraph_deps: Dict[str, List[str]] = {
            name: [
                dep
                for dep in deps_of(name, pipelines_config.get(name, {}))
                if dep in ancestors or dep == target
            ]
            for name in subgraph_names
        }

        detect_cycles_dfs(subgraph_deps)

        adj: Dict[str, List[str]] = {name: [] for name in subgraph_names}
        for name in subgraph_names:
            for dep in subgraph_deps[name]:
                adj[dep].append(name)

        ordered = kahn_topological_sort(adj, subgraph_names)

        if len(ordered) != len(subgraph_names):
            unresolved = sorted(set(subgraph_names) - set(ordered))
            raise ValueError(
                f"Could not resolve a complete execution chain for pipeline "
                f"'{target}': {len(unresolved)} pipeline(s) left unordered "
                f"({unresolved}). This indicates a dependency cycle in 'depends_on'."
            )

        return ordered
