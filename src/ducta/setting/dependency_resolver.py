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

from collections import defaultdict, deque
from typing import Any, Dict, Iterable, List, Optional, Set

from loguru import logger  # type: ignore


class GraphCycleError(ValueError):
    """A directed graph (node or pipeline dependencies) contains a cycle."""

    def __init__(self, message: str, cycle: Optional[List[str]] = None) -> None:
        super().__init__(message)
        self.cycle = cycle or []


class MissingDependencyReferenceError(ValueError):
    """A node declares a dependency that is not part of the same pipeline."""

    def __init__(self, message: str, node: str, dependency: str) -> None:
        super().__init__(message)
        self.node = node
        self.dependency = dependency


def kahn_topological_sort(
    adjacency: Dict[str, Iterable[str]],
    node_order: List[str],
    *,
    sort_dependents: bool = False,
) -> List[str]:
    """Topologically sort using Kahn's algorithm."""
    in_degree: Dict[str, int] = {node: 0 for node in node_order}
    for node, dependents in adjacency.items():
        for dependent in dependents:
            in_degree[dependent] = in_degree.get(dependent, 0) + 1

    queue: deque = deque(node for node in node_order if in_degree.get(node, 0) == 0)
    ordered: List[str] = []
    while queue:
        node = queue.popleft()
        ordered.append(node)
        dependents = adjacency.get(node, ())
        for dependent in sorted(dependents) if sort_dependents else dependents:
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)

    return ordered


def detect_cycles_dfs(graph: Dict[str, List[str]]) -> None:
    """Detect cycles in a directed graph using 3-colour DFS."""
    WHITE, GRAY, BLACK = 0, 1, 2
    colors: Dict[str, int] = {node: WHITE for node in graph}
    path: List[str] = []

    def _dfs(node: str) -> bool:
        colors[node] = GRAY
        path.append(node)
        for neighbour in graph.get(node, []):
            if colors.get(neighbour, WHITE) == GRAY:
                path.append(neighbour)
                return True
            if colors.get(neighbour, WHITE) == WHITE:
                if _dfs(neighbour):
                    return True
        path.pop()
        colors[node] = BLACK
        return False

    for node in list(graph):
        if colors[node] == WHITE:
            if _dfs(node):
                cycle_end = path[-1]
                try:
                    segment = path[path.index(cycle_end) :]
                except ValueError:
                    segment = path
                arrow = " → "
                raise GraphCycleError(
                    f"Circular dependency detected in pipeline: {arrow.join(segment)}",
                    cycle=list(segment),
                )


class DependencyResolver:
    """Handles dependency resolution and topological sorting for pipeline nodes."""

    @staticmethod
    def build_dependency_graph(
        pipeline_nodes: List[str], node_configs: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Set[str]]:
        """Build a dependency graph from node configurations."""
        from ducta.setting.dependency_inference import resolve_node_dependencies

        resolved = resolve_node_dependencies(pipeline_nodes, node_configs)

        dag = defaultdict(set)
        for node_name in pipeline_nodes:
            dag[node_name] = set()

        for node_name in pipeline_nodes:
            for dep_name in resolved[node_name]:
                logger.debug("Processing dependency: {} -> {}", node_name, dep_name)

                if dep_name not in pipeline_nodes:
                    raise MissingDependencyReferenceError(
                        f"Node '{node_name}' depends on '{dep_name}' which is not in the pipeline",
                        node=node_name,
                        dependency=dep_name,
                    )

                dag[dep_name].add(node_name)

        return dict(dag)

    @staticmethod
    def topological_sort(dag: Dict[str, Set[str]]) -> List[str]:
        """Perform topological sort using Kahn's algorithm."""
        adj_lists = {node: list(dependents) for node, dependents in dag.items()}
        detect_cycles_dfs(adj_lists)

        return kahn_topological_sort(dag, list(dag.keys()), sort_dependents=True)
