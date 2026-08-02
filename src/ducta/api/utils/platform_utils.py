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

import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

# Path helpers


def posix_relative(path: Path, base: Path) -> str:
    """Return path relative to base using forward slashes."""
    return path.relative_to(base).as_posix()


# Git executable


def get_git_executable() -> Optional[str]:
    """Return the absolute path to the git binary, or None if not found."""
    return shutil.which("git")


def get_git_version() -> Optional[str]:
    """Return the git version string (e.g. 2.44.0), or None."""
    git = get_git_executable()
    if not git:
        return None
    try:
        result = subprocess.run(
            [git, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        # "git version 2.44.0.windows.1" → "2.44.0.windows.1"
        return result.stdout.strip().removeprefix("git version ").strip()
    except Exception:
        return None


# Platform information


def get_platform_info() -> dict:
    """Return a dict describing the runtime environment."""
    os_name = platform.system()
    friendly = {"Darwin": "macOS", "Windows": "Windows", "Linux": "Linux"}.get(os_name, os_name)

    git_path = get_git_executable()
    git_version = get_git_version() if git_path else None

    return {
        "os": friendly,
        "os_version": platform.version(),
        "arch": platform.machine(),
        "python": sys.version.split()[0],
        "git_available": git_path is not None,
        "git_version": git_version,
        "git_path": git_path,
    }
