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

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from ducta.api.repositories.node_repository import NodeRepository


@dataclass
class NodeFileInfo:
    """Resolved Python source file information for a node."""

    abs_path: Path
    rel_path: str
    code: str
    exists: bool
    size_bytes: int


class NodeService:
    """Orchestrates node CRUD and Python source management."""

    def __init__(self, root: Path) -> None:
        from ducta.api.workspace.utils import normalize_workspace_path

        # Normalize path in case user provided a project path instead of workspace path
        normalized_root = normalize_workspace_path(root)
        self._repo = NodeRepository(normalized_root)
        self._root = normalized_root

    @property
    def root(self) -> Path:
        """Normalized workspace root this service operates on."""
        return self._root

    # ── Queries ───────────────────────────────────────────────────────────────

    def list_nodes(self) -> Dict[str, Any]:
        """Return all node definitions keyed by name."""
        return self._repo.list_all()

    def get_node(self, name: str) -> tuple[Dict[str, Any], Optional[str]]:
        """Return ``(spec, commit_sha)`` for a single node."""
        spec = self._repo.get(name)
        commit_sha = self._repo.get_commit_sha() or None
        return spec, commit_sha

    def get_node_python_file(self, name: str) -> NodeFileInfo:
        """Resolve and optionally read the Python source file for a node."""
        py_path = self._repo.resolve_python_file(name)
        exists = py_path.exists()
        code = py_path.read_text(encoding="utf-8") if exists else ""
        rel_path = py_path.relative_to(self._root)
        return NodeFileInfo(
            abs_path=py_path,
            rel_path=str(rel_path).replace("\\", "/"),
            code=code,
            exists=exists,
            size_bytes=len(code.encode("utf-8")),
        )

    def get_node_python_file_by_module(self, module: str) -> NodeFileInfo:
        """Resolve and optionally read the Python source file of a module.

        Looked up in each project of the workspace (modules resolve from the
        project root, where the node runs); the workspace root otherwise.
        """
        from ducta.api.repositories.v2_store import workspace_stores
        from ducta.api.workspace.utils import resolve_module_path

        for store in workspace_stores(self._root):
            candidate = resolve_module_path(store.root, module)
            if candidate.exists():
                return self._build_file_info(candidate)
        return self._build_file_info(resolve_module_path(self._root, module))

    def _build_file_info(self, py_path: Path) -> NodeFileInfo:
        """Build a NodeFileInfo for the given path."""
        exists = py_path.exists()
        code = py_path.read_text(encoding="utf-8") if exists else ""
        rel_path = py_path.relative_to(self._root)
        return NodeFileInfo(
            abs_path=py_path,
            rel_path=str(rel_path).replace("\\", "/"),
            code=code,
            exists=exists,
            size_bytes=len(code.encode("utf-8")),
        )

    # ── Commands ──────────────────────────────────────────────────────────────

    def save_node(
        self,
        name: str,
        spec: Dict[str, Any],
        expected_sha: Optional[str] = None,
        pipeline: Optional[str] = None,
    ) -> str:
        """Save a node spec (not committed). Returns the new version token.

        ``pipeline``: where to create a new node in a format-2 project.
        """
        from ducta.api.models.spec import validate_node_spec

        validate_node_spec(name, spec)
        return self._repo.save(name, spec, expected_sha, pipeline=pipeline)

    def delete_node(self, name: str, expected_sha: Optional[str] = None) -> None:
        """Delete a node spec and git-commit."""
        self._repo.delete(name, expected_sha)

    def save_node_code(self, name: str, code: str) -> NodeFileInfo:
        """Validate Python syntax and write the source file. Committing is the user's step."""
        from ducta.api.utils.validators import validate_python_syntax

        py_path = self._repo.resolve_python_file(name)
        validate_python_syntax(code, source_label=py_path.name)
        py_path.parent.mkdir(parents=True, exist_ok=True)
        py_path.write_text(code, encoding="utf-8")
        rel = py_path.relative_to(self._root)
        return NodeFileInfo(
            abs_path=py_path,
            rel_path=str(rel).replace("\\", "/"),
            code=code,
            exists=True,
            size_bytes=len(code.encode("utf-8")),
        )
