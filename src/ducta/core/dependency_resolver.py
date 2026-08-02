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
from typing import Any, Dict, List, Set

from loguru import logger  # type: ignore


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
                arrow = " \u2192 "
                raise ValueError(f"Circular dependency detected in pipeline: {arrow.join(segment)}")


class DependencyResolver:
    """Handles dependency resolution and topological sorting for pipeline nodes."""

    @staticmethod
    def build_dependency_graph(
        pipeline_nodes: List[str], node_configs: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Set[str]]:
        """Build a dependency graph from node configurations.

        Dependencies are the merge of each node's explicit ``dependencies`` and
        the edges inferred from the shared dataset namespace (a node depends on
        whoever produces the datasets it consumes). See
        :mod:`ducta.core.dependency_inference`.
        """
        from ducta.core.dependency_inference import resolve_node_dependencies

        resolved = resolve_node_dependencies(pipeline_nodes, node_configs)

        dag = defaultdict(set)
        for node_name in pipeline_nodes:
            dag[node_name] = set()

        for node_name in pipeline_nodes:
            for dep_name in resolved[node_name]:
                logger.debug("Processing dependency: {} -> {}", node_name, dep_name)

                if dep_name not in pipeline_nodes:
                    raise ValueError(
                        f"Node '{node_name}' depends on '{dep_name}' which is not in the pipeline"
                    )

                dag[dep_name].add(node_name)

        return dict(dag)

    @staticmethod
    def topological_sort(dag: Dict[str, Set[str]]) -> List[str]:
        """Perform topological sort using Kahn's algorithm.

        Runs DFS cycle detection first to provide a precise cycle path on error.

        Deterministic across runs/processes: the initial ready-queue is seeded
        from ``dag``'s own key order (the pipeline's declaration order, since
        dicts preserve insertion order — not from ``set(dag.keys())``, whose
        iteration order depends on Python's per-process hash randomization),
        and dependents freed at the same step are enqueued in sorted order
        (``dag[node]`` is a ``set``, likewise unordered). Without this, two
        runs of the identical pipeline config could execute independent
        (same-rank) nodes in a different order each time — undermining the
        reproducibility the run-certificate system is built around.
        """
        # DFS cycle detection before Kahn's loop for a precise error path
        adj_lists = {node: list(dependents) for node, dependents in dag.items()}
        detect_cycles_dfs(adj_lists)

        in_degree = defaultdict(int)
        node_order = list(dag.keys())

        for node in node_order:
            in_degree[node] = 0

        for node, dependents in dag.items():
            for dependent in dependents:
                in_degree[dependent] += 1

        queue = deque([node for node in node_order if in_degree[node] == 0])
        sorted_nodes = []

        while queue:
            node = queue.popleft()
            sorted_nodes.append(node)

            for dependent in sorted(dag[node]):
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

        return sorted_nodes
