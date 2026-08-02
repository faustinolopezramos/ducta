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

from ducta.api.repositories.config_repository import ConfigRepository


class ConfigService:
    """Orchestrates read, write and validation of workspace config files."""

    def __init__(self, root: Path) -> None:
        from ducta.api.workspace.utils import normalize_workspace_path

        # Normalize path in case user provided a project path instead of workspace path
        normalized_root = normalize_workspace_path(root)
        self._repo = ConfigRepository(normalized_root)
        self._root = normalized_root

    # ── Queries ───────────────────────────────────────────────────────────────

    def list_configs(self, env: str) -> Dict[str, Dict[str, Any]]:
        """Return all config files for *env* keyed by config name.

        Each value is a dict with keys ``name``, ``env``, ``path``, ``content``.
        Files that do not yet exist on disk are silently skipped.
        """
        paths = self._repo.get_paths(env)
        all_contents = self._repo.get_all(env)
        result: Dict[str, Dict[str, Any]] = {}
        for name, content in all_contents.items():
            path = paths.get(name)
            result[name] = {
                "name": name,
                "env": env,
                "path": str(path.relative_to(self._root)) if path else name,
                "content": content,
            }
        return result

    def get_config(self, name: str, env: str) -> Dict[str, Any]:
        """Return data for a single config file, enriched with path metadata.

        Returns a dict with keys ``name``, ``env``, ``path``, ``content``.
        Raises :exc:`ConfigFileNotFoundError` when not registered.
        """
        content = self._repo.get(name, env)
        paths = self._repo.get_paths(env)
        path = paths.get(name)
        return {
            "name": name,
            "env": env,
            "path": str(path.relative_to(self._root)) if path else name,
            "content": content,
        }

    def validate_configs(self, env: str) -> Dict[str, Any]:
        """Validate all config files for *env*.

        Returns ``{"valid": bool, "env": str, "errors": list}``.
        """
        return self._repo.validate(env)

    # ── Commands ──────────────────────────────────────────────────────────────

    def save_config(
        self,
        name: str,
        data: Dict[str, Any],
        env: str = "base",
        expected_sha: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Write *data* to the config file and git-commit.

        Returns an enriched response dict (same shape as :meth:`get_config`
        plus a ``commit_sha`` key).
        Raises :exc:`ConfigFileNotFoundError` when not registered.
        Raises :exc:`ConcurrencyError` when OCC check fails.
        """
        commit_sha = self._repo.save(name, data, env, expected_sha)
        paths = self._repo.get_paths(env)
        path = paths.get(name)
        return {
            "name": name,
            "env": env,
            "path": str(path.relative_to(self._root)) if path else name,
            "content": data,
            "commit_sha": commit_sha or None,
        }
