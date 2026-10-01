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

CONFIG_EXTENSIONS = (".yaml", ".yml", ".json", ".toml")


def find_config_file(directory: Path, stem: str) -> Path | None:
    """Return ``<directory>/<stem>.<ext>`` for the first ext in
    ``CONFIG_EXTENSIONS`` that exists, or None."""
    for ext in CONFIG_EXTENSIONS:
        candidate = directory / f"{stem}{ext}"
        if candidate.exists():
            return candidate
    return None


def has_config_file(directory: Path, stem: str) -> bool:
    """Whether *directory* holds ``<stem>`` in any supported config format."""
    return find_config_file(directory, stem) is not None


def resolve_module_path(workspace_root: Path, module_dotted: str) -> Path:
    """Convert a dotted module path to a ``.py`` file path inside *workspace_root*."""
    from ducta.api.utils.git_utils import safe_path  # avoid circular at top level

    parts = module_dotted.split(".")
    relative = Path(*parts).with_suffix(".py")
    return safe_path(workspace_root, str(relative))


def normalize_workspace_path(path: Path) -> Path:
    """The workspace a request path belongs to.

    A Ducta project (``ducta.yaml``) is its own workspace. A directory under a
    workspace's ``projects/`` that is not a project itself resolves to that
    workspace.
    """
    from ducta.setting.project_loader import find_project_root

    path = path.resolve()
    if find_project_root(path) is not None or (path / "projects").is_dir():
        return path
    if path.parent.name == "projects":
        return path.parent.parent
    return path
