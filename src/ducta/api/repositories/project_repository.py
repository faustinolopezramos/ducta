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

import shutil
from pathlib import Path
from typing import Any, Dict, List

from loguru import logger

from ducta.api.exceptions import ProjectAlreadyExistsError, ProjectNotFoundError, ValidationError
from ducta.api.utils.validators import validate_identifier
from ducta.api.workspace.loaders import load_config_file, write_config_file
from ducta.api.workspace.utils import find_ducta_config

_PROJECT_SETTINGS_FILE = "project_settings.yaml"
_PROJECTS_DIR = "projects"
_PIPELINES_FILE = "pipelines.yaml"


class ProjectRepository:
    """Reads and writes project directories and their associated YAML files."""

    def __init__(self, workspace_path: Path) -> None:
        self._root = workspace_path

    # -- Path helpers -----------------------------------------------------------

    def projects_root(self) -> Path:
        return self._root / _PROJECTS_DIR

    def project_dir(self, project_id: str) -> Path:
        if project_id == "." or project_id == self._root.name:
            return self._root
        # `project_id` is attacker-controlled input from every `{project_id}`
        # route. Without this, `project_id=".."` resolves to
        # `projects_root().parent == workspace_root`, and e.g.
        # `DELETE /api/projects/..?force=true` deletes the whole workspace.
        try:
            validate_identifier(project_id, field="project_id")
        except ValueError as e:
            raise ValidationError(str(e)) from e
        return self.projects_root() / project_id

    def settings_path(self, project_id: str) -> Path:
        """Find project_settings file in any supported format (YAML, TOML, JSON)."""
        p_dir = self.project_dir(project_id)
        # Search in config/ or root
        search_dirs = [p_dir / "config", p_dir]
        for d in search_dirs:
            if not d.is_dir():
                continue
            for ext in ["yml", "yaml", "toml", "json"]:
                candidate = d / f"project_settings.{ext}"
                if candidate.exists():
                    return candidate
        # Default
        return (p_dir / "config" if (p_dir / "config").is_dir() else p_dir) / _PROJECT_SETTINGS_FILE

    def environment_path(self, project_id: str) -> Path:
        """Find environment file in any supported format (YAML, TOML, JSON)."""
        p_dir = self.project_dir(project_id)
        for ext in ["yml", "yaml", "toml", "json"]:
            candidate = p_dir / f"environment.{ext}"
            if candidate.exists():
                return candidate
        return p_dir / "environment.yml"

    def pipelines_path(self, project_id: str) -> Path:
        """Find pipelines file in any supported format (YAML, TOML, JSON)."""
        p_dir = self.project_dir(project_id)
        search_dirs = [p_dir / "config", p_dir]
        for d in search_dirs:
            if not d.is_dir():
                continue
            for ext in ["yml", "yaml", "toml", "json"]:
                candidate = d / f"pipelines.{ext}"
                if candidate.exists():
                    return candidate
        return (p_dir / "config" if (p_dir / "config").is_dir() else p_dir) / _PIPELINES_FILE

    # -- Queries ----------------------------------------------------------------

    def get_settings(self, project_id: str) -> Dict[str, Any]:
        """Return parsed project_settings.yaml.
        Falls back to default metadata if absent but environment.yml exists."""
        settings_file = self.settings_path(project_id)
        if settings_file.exists():
            return load_config_file(settings_file) or {}

        if self.exists(project_id):
            return {
                "name": project_id if project_id != "." else self._root.name,
                "description": (
                    f"Standalone project: {self._root.name}"
                    if project_id == "."
                    else f"Project: {project_id}"
                ),
                "created_at": None,
                "updated_at": None,
            }

        raise ProjectNotFoundError(
            f"Project '{project_id}' not found",
            detail={"project_id": project_id},
        )

    def list_ids(self) -> List[str]:
        """Sorted list of project IDs."""
        ids = []
        projects_root = self.projects_root()
        if projects_root.is_dir():
            ids.extend(
                sorted(
                    entry.name
                    for entry in projects_root.iterdir()
                    if entry.is_dir() and self.exists(entry.name)
                )
            )

        if not ids:
            _ENV_EXTS = (".yml", ".yaml", ".toml", ".json")
            has_root_project = (
                any((self._root / f"environment{ext}").exists() for ext in _ENV_EXTS)
                or any((self._root / "config" / f"pipelines{ext}").exists() for ext in _ENV_EXTS)
                or any((self._root / f"pipelines{ext}").exists() for ext in _ENV_EXTS)
            )
            if has_root_project:
                ids.append(self._root.name)

        return ids

    def exists(self, project_id: str) -> bool:
        p_dir = self.project_dir(project_id)
        _ENV_EXTS = (".yml", ".yaml", ".toml", ".json")
        if any((p_dir / f"environment{ext}").exists() for ext in _ENV_EXTS):
            return True
        # Also consider it a project if it has ducta.yaml (multi-layer projects)
        if any((p_dir / f"ducta{ext}").exists() for ext in _ENV_EXTS):
            return True
        # Also consider it a project if it has pipelines
        if any((p_dir / "config" / f"pipelines{ext}").exists() for ext in _ENV_EXTS):
            return True
        if any((p_dir / f"pipelines{ext}").exists() for ext in _ENV_EXTS):
            return True
        return False

    def get_pipelines(self, project_id: str) -> Dict[str, Any]:
        """Return pipeline dict for a project.

        For layered projects (with ducta.yaml): aggregates pipelines from all layers.
        For standard projects: searches in config/ and subdirectories.
        Falls back to legacy base/pipeline/pipelines.yml if not found.
        """
        p_dir = self.project_dir(project_id)
        all_pipelines = {}

        # Check if this is a layered project (ducta.yaml defines layers)
        ducta_config_file = find_ducta_config(p_dir)

        if ducta_config_file:
            try:
                ducta_config = load_config_file(ducta_config_file)
                layers = ducta_config.get("layers", {})

                # Collect pipelines from all layers
                for layer_name, layer_config in layers.items():
                    pipelines_path = layer_config.get("pipelines")
                    if not pipelines_path:
                        config_dir = layer_config.get("config")
                        if config_dir:
                            pipelines_path = str(Path(config_dir) / "pipelines.yaml")
                    if pipelines_path:
                        full_path = p_dir / pipelines_path
                        if full_path.exists():
                            try:
                                layer_pipelines = load_config_file(full_path)
                                if isinstance(layer_pipelines, dict):
                                    # Keep pipeline names as declared in the YAML — they
                                    # already carry unique prefixes (e.g. "worldcup.bronze_backfill").
                                    # Adding a layer prefix here would double-prefix names
                                    # and break execution lookups.
                                    for pipe_name, pipe_spec in layer_pipelines.items():
                                        all_pipelines[pipe_name] = pipe_spec
                                    logger.debug(
                                        f"Loaded {len(layer_pipelines)} pipelines from layer '{layer_name}'"
                                    )
                            except Exception as exc:
                                logger.debug(
                                    f"Failed to load layer '{layer_name}' pipelines: {exc}"
                                )

                if all_pipelines:
                    return all_pipelines
            except Exception as exc:
                logger.debug(f"Failed to parse ducta config: {exc}")

        # Standard project: search in config/ directory
        config_dir = p_dir / "config"
        if config_dir.exists():
            for pipelines_file in config_dir.rglob("pipelines.*"):
                if pipelines_file.suffix.lower() in (".yaml", ".yml", ".toml", ".json"):
                    try:
                        data = load_config_file(pipelines_file)
                        if isinstance(data, dict) and data:
                            logger.debug(f"Loaded pipelines from {pipelines_file}")
                            return data
                    except Exception as exc:
                        logger.debug(f"Failed to load {pipelines_file}: {exc}")
                        continue

        # Legacy fallback
        legacy_file = p_dir / "base" / "pipeline" / "pipelines.yml"
        if legacy_file.exists():
            try:
                data = load_config_file(legacy_file)
                return data if isinstance(data, dict) else {}
            except Exception:
                pass

        return {}

    def get_pipeline_count(self, project_id: str) -> int:
        return len(self.get_pipelines(project_id))

    # -- Commands ---------------------------------------------------------------

    def create(self, project_id: str, settings: Dict[str, Any]) -> None:
        """Create directory structure and write initial YAML files.
        Raises ProjectAlreadyExistsError when project already exists."""
        if self.exists(project_id):
            raise ProjectAlreadyExistsError(
                f"Project '{project_id}' already exists",
                detail={"project_id": project_id},
            )
        config_dir = self.project_dir(project_id) / "config"
        config_dir.mkdir(parents=True, exist_ok=True)

        write_config_file(
            self.environment_path(project_id),
            {
                "project": project_id,
                "base_path": "../..",
                "env_config": {
                    "base": {
                        "global_config_path": "config/global_config.yaml",
                        "pipelines_config_path": f"projects/{project_id}/config/pipelines.yaml",
                        "nodes_config_path": "config/nodes.yaml",
                        "input_config_path": "config/input.yaml",
                        "output_config_path": "config/output.yaml",
                    }
                },
            },
        )
        write_config_file(self.settings_path(project_id), settings)
        write_config_file(self.pipelines_path(project_id), {})
        logger.info(
            "Project '{id}' created at {path}",
            id=project_id,
            path=self.project_dir(project_id),
        )

    def update_settings(self, project_id: str, settings: Dict[str, Any]) -> None:
        """Overwrite project_settings.yaml."""
        settings_file = self.settings_path(project_id)
        if not settings_file.exists():
            raise ProjectNotFoundError(
                f"Project '{project_id}' not found",
                detail={"project_id": project_id},
            )
        write_config_file(settings_file, settings)

    def delete_dir(self, project_id: str) -> None:
        """Remove the full project directory from disk (non-git fallback)."""
        pdir = self.project_dir(project_id)
        if not pdir.is_dir():
            raise ProjectNotFoundError(
                f"Project '{project_id}' not found",
                detail={"project_id": project_id},
            )
        shutil.rmtree(pdir, ignore_errors=True)
        logger.info("Project '{id}' removed from disk", id=project_id)

    def save_pipeline(self, project_id: str, name: str, spec: Dict[str, Any]) -> None:
        """Add or update a pipeline entry in the project's pipelines.yaml."""
        if not self.exists(project_id):
            raise ProjectNotFoundError(
                f"Project '{project_id}' not found",
                detail={"project_id": project_id},
            )
        current = self.get_pipelines(project_id)
        current[name] = spec
        write_config_file(self.pipelines_path(project_id), current)

    def delete_pipeline(self, project_id: str, name: str) -> None:
        """Remove a pipeline entry. Raises ValidationError when absent."""
        current = self.get_pipelines(project_id)
        if name not in current:
            raise ValidationError(
                f"Pipeline '{name}' not found in project '{project_id}'",
                detail={"project_id": project_id, "pipeline": name},
            )
        del current[name]
        write_config_file(self.pipelines_path(project_id), current)
