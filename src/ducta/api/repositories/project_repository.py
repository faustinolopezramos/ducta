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

Projects of a workspace.

A workspace is either a Ducta project itself (``ducta.yaml`` at its root) or a
directory whose ``projects/<id>/`` sub-directories are Ducta projects. Every
project is self-contained: its settings, catalog and pipelines live in its own
``ducta.yaml``, ``catalog.yaml`` and ``pipelines/``. A project's API metadata
(description, variables, timestamps) is kept in ``ducta.yaml`` as well —
``description`` and ``metadata``.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml  # type: ignore[import-untyped]
from loguru import logger

from ducta.api.exceptions import (
    ProjectAlreadyExistsError,
    ProjectNotFoundError,
    ValidationError,
)
from ducta.api.repositories.v2_store import V2ProjectStore, _dump_rt, _load_rt, _sync
from ducta.api.utils.validators import validate_identifier
from ducta.setting.project_loader import (
    CATALOG_FILE,
    PIPELINES_DIR,
    PROJECT_FILE,
    find_project_root,
)

_PROJECTS_DIR = "projects"
#: API-owned keys kept under ``metadata`` in ducta.yaml.
_API_META = ("variables", "created_at", "updated_at")


class ProjectRepository:
    """Reads and writes the projects of one workspace."""

    def __init__(self, workspace_path: Path) -> None:
        self._root = workspace_path

    # -- Paths ------------------------------------------------------------------

    def projects_root(self) -> Path:
        return self._root / _PROJECTS_DIR

    def project_dir(self, project_id: str) -> Path:
        if project_id == "." or project_id == self._root.name:
            return self._root
        try:
            validate_identifier(project_id, field="project_id")
        except ValueError as e:
            raise ValidationError(str(e)) from e
        return self.projects_root() / project_id

    def manifest_path(self, project_id: str) -> Path:
        root = find_project_root(self.project_dir(project_id))
        return (root or self.project_dir(project_id)) / PROJECT_FILE

    def store(self, project_id: str) -> V2ProjectStore:
        """The project's configuration store; ProjectNotFoundError if there is none."""
        found = find_project_root(self.project_dir(project_id))
        if found is None:
            from ducta.console.config import FORMAT1_MESSAGE, format1_markers

            p_dir = self.project_dir(project_id)
            if p_dir.is_dir() and format1_markers(p_dir):
                raise ValidationError(
                    FORMAT1_MESSAGE.format(root=p_dir), detail={"project_id": project_id}
                )
            raise ProjectNotFoundError(
                f"Project '{project_id}' not found", detail={"project_id": project_id}
            )
        return V2ProjectStore(found, self._root)

    # -- Queries ----------------------------------------------------------------

    def exists(self, project_id: str) -> bool:
        return find_project_root(self.project_dir(project_id)) is not None

    def list_ids(self) -> List[str]:
        """Sorted project IDs: the workspace itself when it is a project, else projects/*."""
        ids: List[str] = []
        projects_root = self.projects_root()
        if projects_root.is_dir():
            ids.extend(
                sorted(
                    entry.name
                    for entry in projects_root.iterdir()
                    if entry.is_dir() and self.exists(entry.name)
                )
            )
        if not ids and find_project_root(self._root) is not None:
            ids.append(self._root.name)
        return ids

    def get_settings(self, project_id: str) -> Dict[str, Any]:
        """name/description/variables/metadata/created_at/updated_at, from ducta.yaml."""
        self.store(project_id)  # raises for unknown or format-1 projects
        data = yaml.safe_load(self.manifest_path(project_id).read_text(encoding="utf-8")) or {}
        metadata = dict(data.get("metadata") or {})
        return {
            "name": data.get("project", project_id),
            "description": data.get("description"),
            "variables": metadata.pop("variables", {}) or {},
            "created_at": metadata.pop("created_at", None),
            "updated_at": metadata.pop("updated_at", None),
            "metadata": metadata,
        }

    def get_pipelines(self, project_id: str) -> Dict[str, Any]:
        return self.store(project_id).pipelines()

    def get_pipeline_count(self, project_id: str) -> int:
        return len(self.get_pipelines(project_id))

    def get_pipelines_commit_sha(self, project_id: str) -> str:
        store = self.store(project_id)
        return store.commit_sha(store.pipelines_dir)

    # -- Commands ---------------------------------------------------------------

    def create(self, project_id: str, settings: Dict[str, Any]) -> List[Path]:
        """Write a new, empty format-2 project; return the files created."""
        if self.exists(project_id):
            raise ProjectAlreadyExistsError(
                f"Project '{project_id}' already exists", detail={"project_id": project_id}
            )
        p_dir = self.project_dir(project_id)
        (p_dir / PIPELINES_DIR).mkdir(parents=True, exist_ok=True)
        manifest = {
            "version": 2,
            "project": settings.get("name", project_id),
            "description": settings.get("description") or None,
            "paths": {"input": "data", "output": "data"},
            "settings": {},
            "metadata": _metadata(settings),
        }
        manifest = {k: v for k, v in manifest.items() if v is not None}
        (p_dir / PROJECT_FILE).write_text(
            yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True), encoding="utf-8"
        )
        (p_dir / CATALOG_FILE).write_text("{}\n", encoding="utf-8")
        keep = p_dir / PIPELINES_DIR / ".gitkeep"
        keep.write_text("", encoding="utf-8")
        logger.info("Project '{id}' created at {path}", id=project_id, path=p_dir)
        return [p_dir / PROJECT_FILE, p_dir / CATALOG_FILE, keep]

    def update_settings(self, project_id: str, settings: Dict[str, Any]) -> Path:
        """Write description and metadata into ducta.yaml (comments are kept)."""
        store = self.store(project_id)
        path = store.root / PROJECT_FILE
        doc = _load_rt(path)
        if settings.get("description"):
            doc["description"] = settings["description"]
        elif "description" in doc:
            del doc["description"]
        meta = _metadata(settings)
        if isinstance(doc.get("metadata"), dict):
            _sync(doc["metadata"], meta)
        else:
            doc["metadata"] = meta
        _dump_rt(path, doc)
        store.project()  # still valid
        return path

    def delete_dir(self, project_id: str) -> None:
        """Remove the full project directory from disk (non-git fallback)."""
        pdir = self.project_dir(project_id)
        if not pdir.is_dir():
            raise ProjectNotFoundError(
                f"Project '{project_id}' not found", detail={"project_id": project_id}
            )
        shutil.rmtree(pdir, ignore_errors=True)
        logger.info("Project '{id}' removed from disk", id=project_id)

    def save_pipeline(
        self, project_id: str, name: str, spec: Dict[str, Any], expected_sha: Optional[str] = None
    ) -> str:
        return self.store(project_id).save_pipeline(name, spec, expected_sha)

    def delete_pipeline(
        self, project_id: str, name: str, expected_sha: Optional[str] = None
    ) -> str:
        return self.store(project_id).delete_pipeline(name, expected_sha)


def _metadata(settings: Dict[str, Any]) -> Dict[str, Any]:
    meta = dict(settings.get("metadata") or {})
    for key in _API_META:
        if settings.get(key) not in (None, {}, ""):
            meta[key] = settings[key]
    return meta
