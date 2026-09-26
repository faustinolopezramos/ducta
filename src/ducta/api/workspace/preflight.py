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

import ast
from pathlib import Path
from typing import Any, Dict, List, Set

from loguru import logger

from ducta.api.exceptions import ValidationError


class PreflightValidator:
    """Validates configurations and code before pipeline execution."""

    def __init__(self, workspace_root: Path) -> None:
        self.root = workspace_root
        self.errors: List[Dict[str, Any]] = []
        self.warnings: List[str] = []

    # Public API

    def validate_pipeline(self, pipeline_name: str, pipeline_spec: Dict[str, Any]) -> None:
        """Validate a single pipeline before execution."""
        self.errors = []
        self.warnings = []

        # Check pipeline structure
        self._validate_pipeline_structure(pipeline_name, pipeline_spec)
        if self.errors:
            raise ValidationError(
                f"Pipeline '{pipeline_name}' validation failed",
                detail={"errors": self.errors},
            )

        # Check nodes exist and code is valid
        nodes = pipeline_spec.get("nodes", [])
        edges = pipeline_spec.get("edges", [])

        for node in nodes:
            self._validate_node(node)

        # Check DAG structure
        self._validate_dag(nodes, edges)

        if self.errors:
            raise ValidationError(
                f"Pipeline '{pipeline_name}' has validation errors",
                detail={
                    "errors": self.errors,
                    "warnings": self.warnings,
                },
            )

        logger.info(
            "Pre-flight validation passed for pipeline '{name}'",
            name=pipeline_name,
        )

    # Validation Methods

    def _validate_pipeline_structure(self, name: str, spec: Dict[str, Any]) -> None:
        """Check required fields and basic structure."""
        if not isinstance(spec, dict):
            self.errors.append({"field": "pipeline", "error": "Pipeline must be a dict"})
            return

        # nodes is required
        if "nodes" not in spec or not isinstance(spec.get("nodes"), list):
            self.errors.append(
                {
                    "field": "nodes",
                    "error": "Pipeline must define 'nodes' as a list",
                }
            )

        # edges can be optional
        edges = spec.get("edges", [])
        if not isinstance(edges, list):
            self.errors.append(
                {
                    "field": "edges",
                    "error": "edges must be a list",
                }
            )

    def _validate_node(self, node) -> None:
        """Validate a single node definition."""
        # Native Ducta format: node is a string identifier
        if isinstance(node, str):
            if not node.strip():
                self.errors.append({"field": "node", "error": "Node name cannot be empty"})
            return

        if not isinstance(node, dict):
            self.errors.append(
                {
                    "field": "node",
                    "error": f"Node must be a string or dict, got {type(node).__name__}",
                }
            )
            return

        node_name = node.get("name", "?")

        # Required fields
        if not node.get("name"):
            self.errors.append({"node": "?", "error": "Node must have 'name' field"})
            return

        if not node.get("type"):
            self.errors.append(
                {
                    "node": node_name,
                    "error": "Node must have 'type' field (source, transform, sink, custom)",
                }
            )

        # Validate code if present
        code = node.get("code")
        if code and isinstance(code, str):
            self._validate_python_code(code, node_name)

    def _validate_python_code(self, code: str, context: str = "code") -> None:
        """Validate Python code using ast.parse()."""
        try:
            ast.parse(code)
        except SyntaxError as e:
            self.errors.append(
                {
                    "context": context,
                    "error": f"Python syntax error at line {e.lineno}: {e.msg}",
                    "detail": {"line": e.lineno, "offset": e.offset},
                }
            )
        except Exception as e:
            self.errors.append(
                {
                    "context": context,
                    "error": f"Code validation error: {e}",
                }
            )

    def _validate_dag(self, nodes: List[Any], edges: List[Dict[str, Any]]) -> None:
        """Validate DAG structure: no cycles, edge targets exist."""
        if not nodes:
            self.warnings.append("Pipeline has no nodes")
            return

        # Support both string nodes (native Ducta) and dict nodes (UI format)
        node_names: Set[str] = set()
        for n in nodes:
            if isinstance(n, str) and n.strip():
                node_names.add(n.strip())
            elif isinstance(n, dict) and n.get("name"):
                node_names.add(n["name"])

        # Check edge targets exist
        for edge in edges:
            source = edge.get("source") or edge.get("from_node") or edge.get("from")
            target = edge.get("target") or edge.get("to_node") or edge.get("to")

            if source and source not in node_names:
                self.errors.append(
                    {
                        "edge": f"{source}->{target}",
                        "error": f"Source node '{source}' not found in pipeline",
                    }
                )

            if target and target not in node_names:
                self.errors.append(
                    {
                        "edge": f"{source}->{target}",
                        "error": f"Target node '{target}' not found in pipeline",
                    }
                )

        # Check for cycles using DFS
        adj_list: Dict[str, List[str]] = {n: [] for n in node_names}
        for edge in edges:
            source = edge.get("source") or edge.get("from_node") or edge.get("from")
            target = edge.get("target") or edge.get("to_node") or edge.get("to")
            if source and target and source in adj_list and target in adj_list:
                adj_list[source].append(target)

        cycle = self._find_cycle(adj_list)
        if cycle:
            self.errors.append(
                {
                    "dag": "cycle",
                    "error": f"Circular dependency detected: {' -> '.join(cycle)} -> {cycle[0]}",
                }
            )

    def _find_cycle(self, adj_list: Dict[str, List[str]]) -> List[str] | None:
        """Detect cycle in directed graph using iterative DFS with 3-colour marking."""
        # 0 = unvisited (WHITE), 1 = in current path (GRAY), 2 = done (BLACK)
        color: Dict[str, int] = dict.fromkeys(adj_list, 0)
        # Tracks current DFS traversal path for cycle extraction
        stack: List[str] = []

        def _dfs(start: str) -> List[str] | None:
            color[start] = 1
            stack.append(start)
            for neighbor in adj_list.get(start, []):
                if color[neighbor] == 1:
                    # Back-edge found: extract the cycle from the current stack
                    idx = stack.index(neighbor)
                    return stack[idx:]
                if color[neighbor] == 0:
                    result = _dfs(neighbor)
                    if result is not None:
                        return result
            stack.pop()
            color[start] = 2
            return None

        for node in adj_list:
            if color[node] == 0:
                cycle = _dfs(node)
                if cycle is not None:
                    return cycle

        return None


# ── Deep preflight (subprocess) ───────────────────────────────────────────────

_DEEP_PREFLIGHT_MARKER = "DUCTA_PREFLIGHT_JSON:"
_DEEP_PREFLIGHT_TIMEOUT_S = 180


def run_deep_preflight(exec_source: Path, pipeline_name: str, env: str) -> Dict[str, Any]:
    """Run the same checks as ``ducta config validate`` in a fresh subprocess.

    Imports every node function and checks its signature, validates I/O
    catalog keys, intermediate registration and DAG cycles — without executing
    anything. A subprocess keeps the API process free of the project's imports.

    Returns ``{"ok", "errors", "warnings"}``. *env* must already be validated
    (it is interpolated into the snippet, although through ``repr``).
    """
    import json
    import subprocess
    import sys
    import textwrap

    snippet = textwrap.dedent(
        f"""
        import json, sys
        sys.path.insert(0, {str(exec_source)!r})
        from ducta.console.config import ConfigManager
        from ducta.console.execution import ContextInitializer
        from ducta.core.preflight import validate_pipeline
        cm = ConfigManager()
        cm.change_to_config_directory()
        ctx = ContextInitializer(cm).initialize({env!r})
        r = validate_pipeline(ctx, {pipeline_name!r})
        print({_DEEP_PREFLIGHT_MARKER!r} + json.dumps(
            {{"ok": r.ok, "errors": r.errors, "warnings": r.warnings}}
        ))
        """
    )
    try:
        proc = subprocess.run(
            [sys.executable, "-c", snippet],
            cwd=str(exec_source),
            capture_output=True,
            text=True,
            timeout=_DEEP_PREFLIGHT_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "errors": [f"Preflight timed out after {_DEEP_PREFLIGHT_TIMEOUT_S}s"],
            "warnings": [],
        }

    for line in reversed((proc.stdout or "").splitlines()):
        if line.startswith(_DEEP_PREFLIGHT_MARKER):
            return json.loads(line[len(_DEEP_PREFLIGHT_MARKER) :])

    tail = ((proc.stderr or "") + (proc.stdout or ""))[-2000:]
    return {
        "ok": False,
        "errors": [f"Preflight subprocess failed (exit {proc.returncode}): {tail.strip()}"],
        "warnings": [],
    }
