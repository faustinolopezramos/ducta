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
from typing import Optional

from loguru import logger  # type: ignore

from ducta.console.core import ConfigurationError, SecurityError, SecurityValidator
from ducta.setting.project_context import find_nearest_project
from ducta.setting.project_loader import PROJECT_FILE, project_file

__all__ = ["ConfigManager", "find_nearest_project"]


class ConfigManager:
    """The project a command operates on, and the working directory it runs in."""

    def __init__(self, base_path: Optional[str] = None, require_config: bool = True) -> None:
        self.original_cwd = Path.cwd()
        self.base_path = Path(base_path) if base_path else Path.cwd()
        self.require_config = require_config
        self.project_root: Optional[Path] = find_nearest_project(self.base_path)
        if self.project_root is None:
            if require_config:
                from ducta.console.ux.view import display_path

                shown = display_path(self.base_path)
                where = "here" if shown == "." else f"in {shown}"
                raise ConfigurationError(
                    f"No Ducta project {where} or in any folder above it "
                    f"(no {PROJECT_FILE}, ducta.toml or ducta.json with `version: 2`)",
                    hints=[
                        ("create one", "ducta init project --name my_project"),
                        ("or use one", "--base-path PATH"),
                    ],
                )
            logger.debug("No project found under {}", self.base_path)

    def get_config_file_path(self) -> str:
        if self.project_root is None:
            raise ConfigurationError("No active project")
        return str(project_file(self.project_root).resolve())

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
