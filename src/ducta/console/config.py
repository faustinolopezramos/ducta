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

Locating the project a CLI command works on.

A project is a directory holding ``ducta.yaml`` with ``version: 2`` (at its
root or under ``config/``). Commands find the nearest one from ``--base-path``
(default: the current directory) upwards, the way git finds a repository.
"""

import os
from pathlib import Path
from typing import List, Optional

from loguru import logger  # type: ignore

from ducta.console.core import ConfigurationError, SecurityError, SecurityValidator
from ducta.setting.project_loader import PROJECT_FILE, find_project_root

#: Files that mark a project still in configuration format 1.
_FORMAT1_MARKERS = (
    "environment.yaml",
    "environment.yml",
    "environment.toml",
    "environment.json",
    "settings.json",
    "config/global_config.yaml",
    "config/global_config.yml",
    "config/global_config.toml",
    "config/global_config.json",
)

FORMAT1_MESSAGE = (
    "{root} uses configuration format 1 (environment.yaml + config/*), which Ducta no "
    "longer reads. Convert it — the result is verified equivalent in every environment "
    "before anything is written:\n    ducta config migrate --path {root} --write"
)


def format1_markers(directory: Path) -> List[Path]:
    """Format-1 files present in ``directory`` (empty for a format-2 project)."""
    found = [directory / m for m in _FORMAT1_MARKERS if (directory / m).is_file()]
    manifest = directory / PROJECT_FILE
    if manifest.is_file() and find_project_root(directory) is None:
        found.append(manifest)  # a layered manifest or bundle named ducta.yaml
    return found


def find_nearest_project(start: Path) -> Optional[Path]:
    """The format-2 project at ``start`` or in its nearest ancestor."""
    start = start.resolve()
    for directory in (start, *start.parents):
        root = find_project_root(directory)
        if root is not None:
            return root
    return None


class ConfigManager:
    """The project a command operates on, and the working directory it runs in."""

    def __init__(self, base_path: Optional[str] = None, require_config: bool = True) -> None:
        self.original_cwd = Path.cwd()
        self.base_path = Path(base_path) if base_path else Path.cwd()
        self.require_config = require_config
        self.project_root: Optional[Path] = find_nearest_project(self.base_path)
        if self.project_root is None:
            legacy = format1_markers(self.base_path.resolve())
            if legacy:
                raise ConfigurationError(FORMAT1_MESSAGE.format(root=self.base_path.resolve()))
            if require_config:
                raise ConfigurationError(
                    f"No Ducta project found in {self.base_path.resolve()} or above it "
                    f"(looked for {PROJECT_FILE} with `version: 2`). Create one with "
                    "`ducta template`."
                )
            logger.debug("No project found under {}", self.base_path)

    def get_config_file_path(self) -> str:
        if self.project_root is None:
            raise ConfigurationError("No active project")
        return str((self.project_root / PROJECT_FILE).resolve())

    def get_config_directory(self) -> Path:
        if self.project_root is None:
            if not self.require_config:
                return self.base_path
            raise ConfigurationError("No active project")
        return self.project_root

    def change_to_config_directory(self) -> None:
        """Run from the project root: relative data paths and module imports resolve there."""
        if self.project_root and self.project_root != self.original_cwd:
            try:
                os.chdir(SecurityValidator.validate_path(self.project_root, self.project_root))
            except SecurityError as e:
                raise ConfigurationError(f"Failed to change directory: {e}")

    def restore_original_directory(self) -> None:
        try:
            os.chdir(self.original_cwd)
        except OSError:
            pass
