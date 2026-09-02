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
from typing import Any, Dict, List

from loguru import logger

from ducta.api.utils.git_utils import GIT_AVAILABLE, format_commit, get_repo
from ducta.api.vcs.base import RepositoryAdapter


class LocalAdapter(RepositoryAdapter):
    """Adapter that operates purely on a local Git repository."""

    def __init__(self, config: Dict[str, Any] | None = None) -> None:
        self._config = config or {}
        self._local_path: Path | None = None

    def clone(self, url: str, local_path: Path) -> None:
        """Clone from a local path URL."""
        if not GIT_AVAILABLE:
            raise RuntimeError("GitPython is required. Install it with: pip install gitpython")
        from git import Repo

        logger.info("Cloning {url} -> {local_path}", url=url, local_path=local_path)
        Repo.clone_from(url, str(local_path))
        self._local_path = local_path

    def get_remote_url(self) -> str:
        """Return remote URL if configured."""
        if self._local_path and GIT_AVAILABLE:
            try:
                repo = get_repo(self._local_path)
                if repo.remotes:
                    return repo.remotes[0].url
            except Exception:
                pass
        return ""

    def push(self, branch: str = "main") -> None:
        """Push to remote if configured."""
        if not self._local_path:
            logger.debug("LocalAdapter.push: no local path set — skipping")
            return
        if not GIT_AVAILABLE:
            raise RuntimeError("GitPython is required for git push.")
        try:
            repo = get_repo(self._local_path)
            if not repo.remotes:
                logger.debug("LocalAdapter.push: no remotes configured — skipping")
                return
            repo.remotes[0].push(branch)
            logger.info("Pushed to remote branch: {branch}", branch=branch)
        except Exception as exc:
            logger.warning("Push failed: {exc}", exc=exc)

    def pull(self, branch: str = "main") -> None:
        """Pull from remote if configured."""
        if not self._local_path:
            logger.debug("LocalAdapter.pull: no local path set — skipping")
            return
        if not GIT_AVAILABLE:
            raise RuntimeError("GitPython is required for git pull.")
        try:
            repo = get_repo(self._local_path)
            if not repo.remotes:
                logger.debug("LocalAdapter.pull: no remotes configured — skipping")
                return
            repo.remotes[0].pull(branch)
            logger.info("Pulled from remote branch: {branch}", branch=branch)
        except Exception as exc:
            logger.warning("Pull failed: {exc}", exc=exc)

    def get_commit_log(self) -> List[Dict[str, Any]]:
        """Return commit log from local git history."""
        if not self._local_path or not GIT_AVAILABLE:
            return []
        try:
            repo = get_repo(self._local_path)
            return [format_commit(c) for c in repo.iter_commits(max_count=100)]
        except Exception as exc:
            logger.warning("Could not read commit log: {exc}", exc=exc)
            return []

    def set_local_path(self, path: Path) -> None:
        """Update the tracked local path."""
        self._local_path = path
