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

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger  # type: ignore

from ducta.api.exceptions import PipelineNotFoundError, ProjectNotFoundError, ValidationError
from ducta.api.models.project import (
    ImportProjectRequest,
    ProjectCreateRequest,
    ProjectListResponse,
    ProjectResponse,
    ProjectUpdateRequest,
)
from ducta.api.repositories.project_repository import ProjectRepository
from ducta.api.utils.git_utils import commit_files
from ducta.api.utils.pagination import paginate
from ducta.api.utils.validators import validate_project_name


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_response(
    workspace_path: Path,
    project_id: str,
    settings: Dict[str, Any],
    repo: Optional[ProjectRepository] = None,
) -> ProjectResponse:
    """Build a ProjectResponse with pipeline count."""
    if repo is None:
        repo = ProjectRepository(workspace_path)

    pipelines = repo.get_pipelines(project_id)
    pipeline_count = len(pipelines) if isinstance(pipelines, dict) else 0

    return ProjectResponse(
        id=project_id,
        name=settings.get("name", project_id),
        description=settings.get("description"),
        workspace=str(workspace_path),
        pipeline_count=pipeline_count,
        variables=settings.get("variables", {}),
        metadata=settings.get("metadata", {}),
        created_at=settings.get("created_at"),
        updated_at=settings.get("updated_at"),
        _links={
            "self": f"/api/projects/{project_id}",
            "pipelines": f"/api/projects/{project_id}/pipelines",
            "workspace": "/api/workspace",
        },
    )


def _git_commit_files(workspace_path: Path, message: str, files: List[Path]) -> None:
    existing = [f for f in files if f.exists()]
    if not existing:
        return
    try:
        commit_files(workspace_path, existing, message)
    except Exception as exc:
        logger.warning("Git commit skipped (non-fatal): {exc}", exc=exc)


class ProjectService:
    def __init__(self, workspace_path: Path) -> None:
        from ducta.api.workspace.utils import normalize_workspace_path

        normalized_path = normalize_workspace_path(workspace_path)
        self._workspace_path = normalized_path
        self._repo = ProjectRepository(normalized_path)

    def list_projects_paginated(self, skip: int = 0, limit: int = 50) -> ProjectListResponse:
        items: List[ProjectResponse] = []
        all_ids = list(self._repo.list_ids())
        paginated_ids, total = paginate(all_ids, skip, limit)
        for project_id in paginated_ids:
            try:
                settings = self._repo.get_settings(project_id)
                items.append(
                    _build_response(self._workspace_path, project_id, settings, self._repo)
                )
            except Exception as exc:
                logger.warning(
                    "Skipping malformed project '{name}': {exc}", name=project_id, exc=exc
                )
        return ProjectListResponse(
            projects=items, count=len(items), total=total, skip=skip, limit=limit
        )

    def get_project(self, project_id: str) -> ProjectResponse:
        settings = self._repo.get_settings(project_id)
        return _build_response(self._workspace_path, project_id, settings, self._repo)

    def create_project(
        self, body: ProjectCreateRequest, *, auto_commit: bool = True
    ) -> ProjectResponse:
        project_id = body.name
        now = _now_iso()
        settings: Dict[str, Any] = {
            "name": project_id,
            "description": body.description or "",
            "variables": body.variables,
            "metadata": body.metadata,
            "created_at": now,
            "updated_at": now,
        }

        created = self._repo.create(project_id, settings)

        if auto_commit:
            _git_commit_files(self._workspace_path, f"feat: create project '{project_id}'", created)

        return _build_response(self._workspace_path, project_id, settings, self._repo)

    def update_project(
        self, project_id: str, body: ProjectUpdateRequest, *, auto_commit: bool = True
    ) -> ProjectResponse:
        settings = self._repo.get_settings(project_id)

        for field in ("description", "variables", "metadata"):
            value = getattr(body, field)
            if value is not None:
                settings[field] = value
        settings["updated_at"] = _now_iso()

        manifest = self._repo.update_settings(project_id, settings)

        if auto_commit:
            _git_commit_files(
                self._workspace_path, f"chore: update project '{project_id}' settings", [manifest]
            )

        return _build_response(self._workspace_path, project_id, settings, self._repo)

    def delete_project(
        self, project_id: str, *, auto_commit: bool = True, force: bool = False
    ) -> None:
        pdir = self._repo.project_dir(project_id)
        if not pdir.is_dir():
            raise ProjectNotFoundError(
                f"Project '{project_id}' not found", detail={"project_id": project_id}
            )

        if pdir == self._workspace_path:
            raise ValidationError(
                f"'{project_id}' is the connected workspace itself, not a "
                "sub-project under it — refusing to delete it via this "
                "endpoint. Disconnect or delete the workspace directly if "
                "that's really what you want.",
                detail={"project_id": project_id},
            )

        if not force:
            pipeline_count = self._repo.get_pipeline_count(project_id)
            if pipeline_count:
                raise ValidationError(
                    f"Project '{project_id}' still has {pipeline_count} pipeline(s). "
                    "Delete or move all pipelines first, or use force=true.",
                    detail={"pipeline_count": pipeline_count},
                )

        if auto_commit:
            try:
                from git import Repo  # type: ignore

                git_repo = Repo(str(self._workspace_path), search_parent_directories=True)
                git_repo.index.remove(
                    [str(pdir.relative_to(Path(git_repo.working_tree_dir)))],
                    r=True,
                    working_tree=True,
                )
                git_repo.index.commit(f"chore: delete project '{project_id}'")
                logger.info("Git commit: deleted project '{id}'", id=project_id)
                return
            except Exception as exc:
                logger.warning("Git-tracked delete failed, falling back to rm: {exc}", exc=exc)

        self._repo.delete_dir(project_id)

    def import_project(
        self, body: ImportProjectRequest, *, auto_commit: bool = True
    ) -> ProjectResponse:
        source = Path(body.path).resolve()

        if not source.is_dir():
            raise ValidationError(
                f"Path '{body.path}' does not exist or is not a directory.",
                detail={"path": body.path},
            )

        raw_name = body.name or source.name
        try:
            validate_project_name(raw_name)
        except ValueError as exc:
            raise ValidationError(str(exc), detail={"name": raw_name}) from exc
        project_id = raw_name.lower()

        projects_root = self._repo.projects_root().resolve()
        expected_location = projects_root / project_id
        if source.resolve() != expected_location:
            raise ValidationError(
                f"The path must be directly inside the workspace's projects/ folder. "
                f"Expected: {expected_location}  Got: {source}",
                detail={"expected": str(expected_location), "actual": str(source)},
            )

        # Importing registers a project that is already in place; it must have
        # a ducta.yaml with `version: 2`.
        self._repo.store(project_id)
        logger.info("Project '{id}' imported from {path}", id=project_id, path=source)
        settings = self._repo.get_settings(project_id)
        return _build_response(self._workspace_path, project_id, settings, self._repo)

    def project_dir(self, project_id: str) -> Path:
        """The project's directory (raises ``ProjectNotFoundError`` if unknown)."""
        self.get_project(project_id)
        return self._repo.project_dir(project_id)

    def list_project_pipelines(self, project_id: str) -> Dict[str, Any]:
        self._repo.get_settings(project_id)
        return self._repo.get_pipelines(project_id)

    def get_pipeline(self, project_id: str, pipeline_name: str) -> Dict[str, Any]:
        """Return one pipeline's spec, or raise ``PipelineNotFoundError``."""
        pipelines = self.list_project_pipelines(project_id)
        if pipeline_name not in pipelines:
            raise PipelineNotFoundError(
                f"Pipeline '{pipeline_name}' not found in project '{project_id}'",
                detail={"project_id": project_id, "pipeline": pipeline_name},
            )
        return pipelines[pipeline_name]

    def get_pipelines_commit_sha(self, project_id: str) -> Optional[str]:
        """Current commit SHA of this project's pipelines.yaml, for OCC."""
        return self._repo.get_pipelines_commit_sha(project_id) or None

    def save_project_pipeline(
        self,
        project_id: str,
        pipeline_name: str,
        spec: Dict[str, Any],
        *,
        expected_sha: Optional[str] = None,
    ) -> str:
        """Upsert a pipeline and return the new commit SHA."""
        return self._repo.save_pipeline(project_id, pipeline_name, spec, expected_sha=expected_sha)

    def delete_project_pipeline(
        self, project_id: str, pipeline_name: str, *, expected_sha: Optional[str] = None
    ) -> str:
        """Delete a pipeline and return the new commit SHA (see ``save_project_pipeline``).

        Raises ``PipelineNotFoundError`` (404) when the pipeline does not exist.
        """
        return self._repo.delete_pipeline(project_id, pipeline_name, expected_sha=expected_sha)
