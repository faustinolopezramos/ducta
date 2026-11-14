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

Which workspace a path belongs to, and which one the current directory is.

Shared by the CLI (``ducta ui`` picks the workspace to open) and the web
server (every request names a path inside one).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

#: Suffixes of a project file (``ducta.yaml``, ``ducta.toml``…).
PROJECT_SUFFIXES = (".yaml", ".yml", ".toml", ".json")


def normalize_workspace_path(path: Path) -> Path:
    """The workspace a request path belongs to.

    A Ducta project (``ducta.yaml``) is its own workspace. A directory under a
    workspace's ``projects/`` that is not a project itself resolves to that
    workspace.
    """
    from ducta.setting.project.loader import find_project_root

    path = path.resolve()
    if find_project_root(path) is not None or (path / "projects").is_dir():
        return path
    if path.parent.name == "projects":
        return path.parent.parent
    return path


def detect_workspace(cwd: Optional[Path] = None) -> Optional[str]:
    """The Ducta workspace the current directory (or *cwd*) is in, or None.

    The nearest project at or above it, in any format; else a ``config/``
    directory with configuration files; else a ``projects/`` directory with
    projects in it (one project: that project; several: the workspace root).
    """
    from loguru import logger

    from ducta.setting.project.context import find_nearest_project
    from ducta.setting.project.loader import find_project_root

    def _is_project_dir(path: Path) -> bool:
        return find_project_root(path) is not None or (path / "config").is_dir()

    cwd = Path(cwd) if cwd is not None else Path.cwd()

    # The project at or above the current directory, in any of its formats:
    # looking only for ducta.yaml/.yml missed every TOML and JSON project.
    root = find_nearest_project(cwd)
    if root is not None:
        return str(normalize_workspace_path(root))
    # A project file that does not parse is still the project to open: the UI
    # is where its errors are shown.
    for candidate in (cwd, *cwd.parents):
        if any((candidate / f"ducta{ext}").is_file() for ext in PROJECT_SUFFIXES):
            return str(normalize_workspace_path(candidate))

    # Fallback: config/ directory with recognised config files in CWD
    config_dir = cwd / "config"
    if config_dir.is_dir():
        config_files = (
            list(config_dir.glob("*.yaml"))
            + list(config_dir.glob("*.yml"))
            + list(config_dir.glob("*.json"))
            + list(config_dir.glob("*.toml"))
        )
        if config_files:
            return str(normalize_workspace_path(cwd))

    # Fallback: multi-project root with a projects/ subdirectory
    projects_dir = cwd / "projects"
    if projects_dir.is_dir():
        sub_projects = [d for d in projects_dir.iterdir() if d.is_dir() and _is_project_dir(d)]
        if len(sub_projects) == 1:
            # Single project: use it unambiguously
            return str(normalize_workspace_path(sub_projects[0]))
        if len(sub_projects) > 1:
            # Multiple projects: use the workspace root (parent directory)
            # This allows the UI to show all projects in a grid
            logger.info(
                "Detected {} Ducta projects under {}. Using workspace root to display all projects.",
                len(sub_projects),
                projects_dir,
            )
            return str(normalize_workspace_path(cwd))

    return None
