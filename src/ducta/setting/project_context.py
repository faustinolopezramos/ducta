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

The project at a path, and its Context — without the CLI around it.

Worker processes and the API's deep preflight rebuild a Context from a path.
They used the CLI's ``ConfigManager``/``ContextInitializer`` for it, which tied
``core`` and ``api`` to the console layer and printed a CLI banner in places
that have no terminal. The CLI keeps those classes; everything else calls this.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Tuple, Union

from ducta.setting.exceptions import ConfigurationError
from ducta.setting.project_loader import PROJECT_FILE, find_project_root, load_project_v2

if TYPE_CHECKING:
    from ducta.setting.contexts import Context


def find_nearest_project(start: Path) -> Optional[Path]:
    """The format-2 project at ``start`` or in its nearest ancestor."""
    start = start.resolve()
    for directory in (start, *start.parents):
        root = find_project_root(directory)
        if root is not None:
            return root
    return None


def load_project_context(
    base_path: Optional[Union[str, Path]] = None,
    env: str = "base",
    *,
    chdir: bool = False,
) -> Tuple[Path, "Context"]:
    """``(project_root, context)`` for the project at or above *base_path* (default: cwd).

    With ``chdir`` the process moves to the project root first, as a CLI run
    does: relative data paths and ``run: module:function`` imports resolve there.
    """
    start = Path(base_path) if base_path else Path.cwd()
    root = find_nearest_project(start)
    if root is None:
        raise ConfigurationError(
            f"No Ducta project found in {start.resolve()} or above it (looked for {PROJECT_FILE})"
        )
    if chdir:
        os.chdir(root)
    return root, load_project_v2(root, env)
