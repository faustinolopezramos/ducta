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
from ducta.api.workspace.loaders import load_config_file, write_config_file


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _merge_legacy_config(legacy_path: Path, target_path: Path, *, label: str) -> None:
    if not legacy_path.exists():
        return
    try:
        new_data = load_config_file(legacy_path) or {}
        existing: Dict[str, Any] = load_config_file(target_path) if target_path.exists() else {}
        write_config_file(target_path, {**existing, **new_data})
        logger.info("Merged {label} into {target}", label=label, target=target_path)
    except Exception as exc:
        logger.warning("Could not merge {label}: {exc}", label=label, exc=exc)


def _migrate_config_file(workspace_config_dir: Path, target_name: str, candidates: list) -> None:
    target = workspace_config_dir / target_name
    if target.exists():
        return
    for candidate in candidates:
        if candidate.exists():
            try:
                write_config_file(target, load_config_file(candidate) or {})
                logger.info(
                    "Migrated {name} from {src} to {tgt}",
                    name=target_name,
                    src=candidate,
                    tgt=target,
                )
            except Exception as exc:
                logger.warning("Could not migrate {name}: {exc}", name=target_name, exc=exc)
            return


def _migrate_global_config(source: Path, workspace_config_dir: Path) -> None:
    _migrate_config_file(
        workspace_config_dir,
        "global_config.yaml",
        [
            source / "base" / "global_config.yml",
            source / "config" / "global_config.yaml",
        ],
    )
    _migrate_config_file(
        workspace_config_dir,
        "pipelines.yaml",
        [
            source / "base" / "pipeline" / "pipelines.yml",
            source / "config" / "pipelines.yaml",
        ],
    )


def _migrate_workspace_configs(source: Path, project_id: str, workspace_config_dir: Path) -> None:
    workspace_config_dir.mkdir(parents=True, exist_ok=True)
    _merge_legacy_config(
        source / "base" / "node" / "nodes.yml",
        workspace_config_dir / "nodes.yaml",
        label=f"nodes for '{project_id}'",
    )
    _merge_legacy_config(
        source / "base" / "catalog" / "input.yml",
        workspace_config_dir / "input.yaml",
        label=f"input catalog for '{project_id}'",
    )
    _merge_legacy_config(
        source / "base" / "catalog" / "output.yml",
        workspace_config_dir / "output.yaml",
        label=f"output catalog for '{project_id}'",
    )
    _migrate_global_config(source, workspace_config_dir)


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

        self._repo.create(project_id, settings)

        if auto_commit:
            _git_commit_files(
                self._workspace_path,
                f"feat: create project '{project_id}'",
                [
                    self._repo.settings_path(project_id),
                    self._repo.pipelines_path(project_id),
                ],
            )

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

        self._repo.update_settings(project_id, settings)

        if auto_commit:
            _git_commit_files(
                self._workspace_path,
                f"chore: update project '{project_id}' settings",
                [
                    self._repo.settings_path(project_id),
                ],
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

        config_dir = source / "config"
        config_dir.mkdir(parents=True, exist_ok=True)

        settings_file = self._repo.settings_path(project_id)
        if settings_file.exists():
            _migrate_workspace_configs(source, project_id, self._workspace_path / "config")
            settings = load_config_file(settings_file)
            return _build_response(self._workspace_path, project_id, settings, self._repo)

        now = _now_iso()
        settings: Dict[str, Any] = {
            "name": project_id,
            "description": body.description or f"Imported from {source.name}",
            "variables": {},
            "metadata": {"imported_from": str(source)},
            "created_at": now,
            "updated_at": now,
        }

        write_config_file(settings_file, settings)

        pipelines_file = self._repo.pipelines_path(project_id)
        if not pipelines_file.exists():
            legacy_pipelines = source / "base" / "pipeline" / "pipelines.yml"
            if legacy_pipelines.exists():
                try:
                    write_config_file(pipelines_file, load_config_file(legacy_pipelines) or {})
                    logger.info(
                        "Migrated pipelines from legacy layout for project '{id}'", id=project_id
                    )
                except Exception as exc:
                    logger.warning(
                        "Could not migrate legacy pipelines for '{id}': {exc}",
                        id=project_id,
                        exc=exc,
                    )
                    write_config_file(pipelines_file, {})
            else:
                write_config_file(pipelines_file, {})

        _migrate_workspace_configs(source, project_id, self._workspace_path / "config")

        logger.info("Project '{id}' imported from {path}", id=project_id, path=source)

        if auto_commit:
            _git_commit_files(
                self._workspace_path,
                f"feat: import project '{project_id}'",
                [settings_file, pipelines_file],
            )

        return _build_response(self._workspace_path, project_id, settings, self._repo)

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
