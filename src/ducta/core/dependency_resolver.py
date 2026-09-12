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

Thin core-layer wrapper around ``ducta.setting.dependency_resolver``'s graph
algorithms. The algorithm itself (Kahn's topological sort, 3-colour DFS cycle
detection) lives in ``setting`` because ``setting/validators.py`` needs it to
validate a project's dependency declarations independently of ``core``. This
module translates that layer's plain ``ValueError`` subtypes
(``GraphCycleError``/``MissingDependencyReferenceError``) into ``core.errors``'
typed ``DuctaError`` hierarchy, so existing ``core``/``console`` exit-code and
HTTP-status mapping for configuration/cycle errors is unaffected by where the
algorithm lives.
"""

from typing import Any, Dict, List, Set

from ducta.core.errors import ConfigurationError, DependencyCycleError
from ducta.setting.dependency_resolver import DependencyResolver as _DependencyResolver
from ducta.setting.dependency_resolver import GraphCycleError, MissingDependencyReferenceError
from ducta.setting.dependency_resolver import detect_cycles_dfs as _detect_cycles_dfs


def detect_cycles_dfs(graph: Dict[str, List[str]]) -> None:
    """Detect cycles in a directed graph using 3-colour DFS."""
    try:
        _detect_cycles_dfs(graph)
    except GraphCycleError as e:
        raise DependencyCycleError(str(e), cycle=e.cycle) from e


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
        :mod:`ducta.setting.dependency_inference`.
        """
        try:
            return _DependencyResolver.build_dependency_graph(pipeline_nodes, node_configs)
        except MissingDependencyReferenceError as e:
            raise ConfigurationError(str(e), node=e.node, dependency=e.dependency) from e

    @staticmethod
    def topological_sort(dag: Dict[str, Set[str]]) -> List[str]:
        """Perform topological sort using Kahn's algorithm.

        Runs DFS cycle detection first to provide a precise cycle path on error.
        """
        try:
            return _DependencyResolver.topological_sort(dag)
        except GraphCycleError as e:
            raise DependencyCycleError(str(e), cycle=e.cycle) from e
