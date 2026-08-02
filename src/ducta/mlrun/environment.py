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

import hashlib
import platform
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional

from loguru import logger


def _get_ducta_version() -> str:
    try:
        import importlib.metadata

        return importlib.metadata.version("ducta")
    except Exception:
        try:
            from ducta import __version__

            return __version__
        except Exception:
            return "unknown"


def _run_git_command(args: list, cwd: Optional[str] = None) -> Optional[str]:
    try:
        kwargs: Dict[str, Any] = {}
        if cwd:
            kwargs["cwd"] = cwd
        return subprocess.check_output(
            ["git"] + args, stderr=subprocess.DEVNULL, text=True, **kwargs
        ).strip()
    except Exception:
        return None


def _capture_git_info(git_root: Optional[str] = None) -> Dict[str, Any]:
    info: Dict[str, Any] = {"commit": None, "branch": None, "dirty": None}
    try:
        commit = _run_git_command(["rev-parse", "--short=12", "HEAD"], cwd=git_root)
        if commit is None:
            return {}  # Return empty dict if git is unavailable as per test

        info["commit"] = commit
        info["branch"] = _run_git_command(["rev-parse", "--abbrev-ref", "HEAD"], cwd=git_root)

        status = _run_git_command(["status", "--porcelain", "--untracked-files=no"], cwd=git_root)
        if status is not None:
            info["dirty"] = bool(status.strip())
    except Exception as e:
        logger.debug(f"Git info capture skipped: {e}")
        return {}
    return info


def _capture_pip_packages() -> Dict[str, str]:
    packages: Dict[str, str] = {}
    try:
        if sys.version_info >= (3, 8):
            import importlib.metadata

            for dist in importlib.metadata.distributions():
                name = dist.metadata.get("Name")
                if name:
                    packages[name] = dist.version
        else:
            import pkg_resources

            for dist in pkg_resources.working_set:
                packages[dist.project_name] = dist.version
    except Exception as e:
        logger.debug(f"Pip packages capture skipped: {e}")
    return packages


def _hash_packages(packages: Dict[str, str]) -> str:
    if not packages:
        return ""
    try:
        hasher = hashlib.sha256()
        for name in sorted(packages.keys()):
            hasher.update(f"{name}=={packages[name]}\n".encode("utf-8"))
        return hasher.hexdigest()
    except Exception as e:
        logger.debug(f"Package hashing skipped: {e}")
        return ""


@dataclass
class EnvironmentSnapshot:
    """Immutable snapshot of the execution environment."""

    python_version: str = ""
    os_info: str = ""
    hostname: str = ""
    ducta_version: str = ""
    git_commit: Optional[str] = None
    git_branch: Optional[str] = None
    git_dirty: Optional[bool] = None
    pip_packages: Dict[str, str] = field(default_factory=dict)
    env_hash: str = ""  # SHA256 of sorted pip_packages

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def capture(
        cls, include_packages: bool = True, git_root: Optional[str] = None
    ) -> "EnvironmentSnapshot":
        """Capture current environment. Safe: never raises."""
        snap = cls()
        try:
            snap.python_version = platform.python_version()
            snap.os_info = f"{platform.system()} {platform.release()}"
            snap.hostname = platform.node()
            snap.ducta_version = _get_ducta_version()

            try:
                git = _capture_git_info(git_root)
                snap.git_commit = git.get("commit")
                snap.git_branch = git.get("branch")
                snap.git_dirty = git.get("dirty")
            except Exception as e:
                logger.debug(f"Git capture raised: {e}")

            if include_packages:
                try:
                    snap.pip_packages = _capture_pip_packages()
                    snap.env_hash = _hash_packages(snap.pip_packages)
                except Exception as e:
                    logger.debug(f"Package capture raised: {e}")

        except Exception as e:
            logger.debug(f"Environment capture top-level exception: {e}")

        return snap
