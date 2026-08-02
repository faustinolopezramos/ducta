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
from typing import Any, Dict, List, Optional

from ducta.api.exceptions import ConfigFileNotFoundError, ConfigValidationError
from ducta.api.utils.git_utils import commit_files, validate_occ
from ducta.api.workspace.loaders import load_config_file, write_config_file
from ducta.api.workspace.utils import find_config_files


class ConfigRepository:
    """Reads and writes workspace config files for a given root path."""

    def __init__(self, root: Path) -> None:
        self._root = root

    # ── Queries ───────────────────────────────────────────────────────────────

    def get_paths(self, env: str) -> Dict[str, Path]:
        """Return mapping of config-name → absolute Path for *env*."""
        return find_config_files(self._root, env)

    def get(self, name: str, env: str) -> Dict[str, Any]:
        """Return parsed content of a single config file."""
        paths = find_config_files(self._root, env)
        path = paths.get(name)
        if path is None:
            raise ConfigFileNotFoundError(
                f"Config '{name}' not found for environment '{env}'",
                detail={"name": name, "env": env},
            )
        return load_config_file(path)

    def get_all(self, env: str) -> Dict[str, Dict[str, Any]]:
        """Return all config files for *env* as ``{name: content}``."""
        paths = find_config_files(self._root, env)
        return {name: load_config_file(path) for name, path in paths.items() if path.exists()}

    def validate(self, env: str) -> Dict[str, Any]:
        """Validate that all config files for *env* can be parsed."""
        errors: List[Dict[str, Any]] = []
        try:
            paths = find_config_files(self._root, env)
        except ConfigFileNotFoundError as exc:
            return {
                "valid": False,
                "env": env,
                "errors": [{"config": "environment", "error": exc.message}],
            }

        for name, path in paths.items():
            if not path.exists():
                errors.append({"config": name, "error": f"File not found: {path}"})
                continue
            try:
                load_config_file(path)
            except (ConfigFileNotFoundError, ConfigValidationError) as exc:
                errors.append({"config": name, "error": exc.message})
            except Exception as exc:
                errors.append({"config": name, "error": str(exc)})

        return {"valid": len(errors) == 0, "env": env, "errors": errors}

    # ── Commands ──────────────────────────────────────────────────────────────

    def save(
        self,
        name: str,
        data: Dict[str, Any],
        env: str = "base",
        expected_sha: Optional[str] = None,
    ) -> str:
        """Write *data* to the config file and git-commit."""
        paths = find_config_files(self._root, env)
        path = paths.get(name)
        if path is None:
            raise ConfigFileNotFoundError(
                f"Config '{name}' not configured for environment '{env}'",
                detail={"name": name, "env": env},
            )
        validate_occ(self._root, path, expected_sha)
        write_config_file(path, data)
        return commit_files(self._root, [path], f"chore: update {name} config for env={env}")
