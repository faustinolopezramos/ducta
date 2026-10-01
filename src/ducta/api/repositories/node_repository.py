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

Nodes of a workspace's projects, in the engine's shape.

A node lives in a pipeline file of one project; the API addresses it by name
across the workspace. A name defined by more than one project is ambiguous and
reported as such rather than resolved by guessing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from ducta.api.exceptions import NodeNotFoundError, PipelineNotFoundError, ValidationError
from ducta.api.repositories.v2_store import V2ProjectStore, workspace_stores
from ducta.api.utils.git_utils import file_commit_sha
from ducta.api.workspace.utils import resolve_module_path


def _normalize_node_spec(spec: Dict[str, Any], node_name: Optional[str] = None) -> Dict[str, Any]:
    """Normalize a node spec to the frontend's shape (``inputs``/``outputs`` lists)."""
    normalized = dict(spec)
    for single, plural in (("input", "inputs"), ("output", "outputs")):
        if single in normalized and plural not in normalized:
            value = normalized.pop(single)
            if value:
                normalized[plural] = value if isinstance(value, list) else [value]
        if plural in normalized and not isinstance(normalized[plural], list):
            normalized[plural] = [normalized[plural]]
    if not normalized.get("module") and isinstance(normalized.get("function"), dict):
        fn_module = normalized["function"].get("module")
        if fn_module:
            normalized["module"] = fn_module
    return normalized


class NodeRepository:
    """Reads and writes node definitions for a workspace root."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def _stores(self) -> List[V2ProjectStore]:
        return workspace_stores(self._root)

    def _owner(self, name: str) -> V2ProjectStore:
        owners = [s for s in self._stores() if name in s.nodes()]
        if not owners:
            raise NodeNotFoundError(f"Node '{name}' not found", detail={"name": name})
        if len(owners) > 1:
            raise ValidationError(
                f"Node '{name}' is defined by several projects "
                f"({', '.join(str(s.root.name) for s in owners)}); rename one of them",
                detail={"name": name},
            )
        return owners[0]

    # ── Queries ───────────────────────────────────────────────────────────────

    def list_all(self) -> Dict[str, Dict[str, Any]]:
        """All nodes keyed by name, normalized to the frontend's shape."""
        nodes: Dict[str, Dict[str, Any]] = {}
        for store in self._stores():
            for name, spec in store.nodes().items():
                if name in nodes:
                    logger.warning("Node '{}' is defined by several projects", name)
                    continue
                nodes[name] = _normalize_node_spec(spec, node_name=name)
        return nodes

    def get(self, name: str) -> Dict[str, Any]:
        nodes = self.list_all()
        if name not in nodes:
            raise NodeNotFoundError(f"Node '{name}' not found", detail={"name": name})
        return nodes[name]

    def get_file_path(self) -> Optional[Path]:
        stores = self._stores()
        return stores[0].pipelines_dir if len(stores) == 1 else None

    def get_commit_sha(self) -> str:
        """Latest commit touching the nodes — the project's pipelines/ directory
        (or the whole projects/ tree for a multi-project workspace)."""
        stores = self._stores()
        if len(stores) == 1:
            return stores[0].commit_sha(stores[0].pipelines_dir)
        return file_commit_sha(self._root, self._root / "projects")

    def resolve_python_file(self, name: str) -> Path:
        """The ``.py`` file of a node's module, inside the node's project."""
        store = self._owner(name)
        spec = store.nodes()[name]
        module = spec.get("module")
        if not module and isinstance(spec.get("function"), dict):
            module = spec["function"].get("module")
        if not module:
            raise NodeNotFoundError(f"Node '{name}' names no Python module", detail={"name": name})
        return resolve_module_path(store.root, module)

    # ── Commands ──────────────────────────────────────────────────────────────

    def save(
        self,
        name: str,
        spec: Dict[str, Any],
        expected_sha: Optional[str] = None,
        pipeline: Optional[str] = None,
    ) -> str:
        """Update a node where it lives, or create it in ``pipeline``'s file."""
        try:
            store = self._owner(name)
        except NodeNotFoundError:
            if not pipeline:
                raise ValidationError(
                    f"A node lives in a pipeline: pass `pipeline` to create node '{name}'",
                    detail={"node": name},
                )
            candidates = [s for s in self._stores() if pipeline in s.pipelines()]
            if not candidates:
                raise PipelineNotFoundError(
                    f"Pipeline '{pipeline}' not found", detail={"pipeline": pipeline}
                )
            if len(candidates) > 1:
                raise ValidationError(
                    f"Pipeline '{pipeline}' exists in several projects; rename one of them",
                    detail={"pipeline": pipeline},
                )
            store = candidates[0]
        return store.save_node(name, spec, expected_sha, pipeline=pipeline)

    def delete(self, name: str, expected_sha: Optional[str] = None) -> str:
        return self._owner(name).delete_node(name, expected_sha)
