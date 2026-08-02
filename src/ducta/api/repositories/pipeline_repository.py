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

from pathlib import Path
from typing import Any, Dict, Optional

from ducta.api.exceptions import ConfigFileNotFoundError, PipelineNotFoundError
from ducta.api.utils.git_utils import commit_files, validate_occ
from ducta.api.workspace.loaders import load_config_file, write_config_file
from ducta.api.workspace.utils import find_config_files


class PipelineRepository:
    """Reads and writes base pipeline records for a workspace root."""

    def __init__(self, root: Path) -> None:
        self._root = root

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _get_path(self) -> Optional[Path]:
        """Return the absolute path to the base pipelines config file, or None."""
        base_paths = find_config_files(self._root, "base")
        return base_paths.get("pipelines")

    # ── Queries ───────────────────────────────────────────────────────────────

    def get_file_path(self) -> Optional[Path]:
        """Expose the config file path for OCC/commit SHA queries."""
        return self._get_path()

    def list_all(self) -> Dict[str, Any]:
        """Return all pipeline definitions keyed by name."""
        path = self._get_path()
        if path is None or not path.exists():
            return {}
        return load_config_file(path) or {}

    def get(self, name: str) -> Dict[str, Any]:
        """Return the spec for a single pipeline.

        Raises :exc:`PipelineNotFoundError` when the pipeline is absent.
        """
        pipelines = self.list_all()
        if name not in pipelines:
            raise PipelineNotFoundError(
                f"Pipeline '{name}' not found",
                detail={"name": name},
            )
        return pipelines[name]

    # ── Commands ──────────────────────────────────────────────────────────────

    def save(
        self,
        name: str,
        spec: Dict[str, Any],
        expected_sha: Optional[str] = None,
    ) -> str:
        """Update or create a pipeline entry and git-commit.

        Returns the new commit SHA (empty string when git is unavailable).
        """
        path = self._get_path()
        if path is None:
            raise ConfigFileNotFoundError(
                "Pipelines config file not found in base environment",
                detail={"env": "base"},
            )
        validate_occ(self._root, path, expected_sha)
        current = load_config_file(path) if path.exists() else {}
        current[name] = spec
        write_config_file(path, current)
        return commit_files(self._root, [path], f"chore: update pipeline '{name}'")

    def delete(self, name: str, expected_sha: Optional[str] = None) -> str:
        """Remove a pipeline entry and git-commit.

        Raises :exc:`PipelineNotFoundError` when the pipeline is absent.
        Raises :exc:`ConcurrencyError` (via ``validate_occ``) when
        *expected_sha* is given and the file was modified since — the same
        check ``save()`` already applies, but ``delete()`` used to skip it
        entirely, so a delete could silently discard a change made
        concurrently by someone else.
        Returns the new commit SHA (empty string when git is unavailable).
        """
        path = self._get_path()
        if path is None:
            raise ConfigFileNotFoundError(
                "Pipelines config file not found in base environment",
                detail={"env": "base"},
            )
        validate_occ(self._root, path, expected_sha)
        current = load_config_file(path) if path.exists() else {}
        if name not in current:
            raise PipelineNotFoundError(
                f"Pipeline '{name}' not found",
                detail={"name": name},
            )
        del current[name]
        write_config_file(path, current)
        return commit_files(self._root, [path], f"chore: delete pipeline '{name}'")
