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

from loguru import logger

from ducta.api.exceptions import RepositoryAdapterError
from ducta.api.utils.git_utils import (
    GIT_AVAILABLE,
    get_repo,
    http_auth_env,
    redact_git_credentials,
)
from ducta.api.vcs.base import RepositoryAdapter


class GitHubAdapter(RepositoryAdapter):
    """Adapter for GitHub repositories."""

    _GITPYTHON_ERROR = "GitPython required. Install: pip install gitpython"

    def __init__(self, config: Dict[str, Any]) -> None:
        self._token: str = config.get("token", "")
        self._org: str = config.get("org", "")
        self._repo_name: str = config.get("repo", "")
        self._local_path: Optional[Path] = None

        if not self._token:
            raise ValueError("GitHub adapter requires 'token' in config.")
        if not self._org or not self._repo_name:
            raise ValueError("GitHub adapter requires 'org' and 'repo' in config.")

        try:
            from github import Github  # type: ignore[import]

            self._client = Github(self._token)
        except ImportError as exc:
            raise ImportError(
                "PyGithub is required for the GitHub adapter. Install with: pip install pygithub"
            ) from exc

    def clone(self, url: str, local_path: Path) -> None:
        """Clone the GitHub repository."""
        if not GIT_AVAILABLE:
            raise RuntimeError(self._GITPYTHON_ERROR)
        from git import Repo  # type: ignore[import]

        # Log the original URL (without embedded credentials)
        logger.info(
            "Cloning GitHub repo {url} -> {path}", url=redact_git_credentials(url), path=local_path
        )
        try:
            Repo.clone_from(
                url,
                str(local_path),
                env={"GIT_TERMINAL_PROMPT": "0", **self._auth_env()},
            )
        except Exception as exc:
            # Sanitize error message to strip credentials from URLs
            safe_msg = redact_git_credentials(str(exc)).replace(self._token, "***")
            raise RepositoryAdapterError(
                f"GitHub clone failed: {safe_msg}",
                detail={"url": url, "local_path": str(local_path)},
            ) from exc
        self._local_path = local_path

    def get_remote_url(self) -> str:
        """Return the HTTPS remote URL."""
        return f"https://github.com/{self._org}/{self._repo_name}.git"

    def push(self, branch: str = "main") -> None:
        """Push local commits to GitHub."""
        self._require_local_path("push")
        if not GIT_AVAILABLE:
            raise RuntimeError(self._GITPYTHON_ERROR)
        try:
            repo = get_repo(self._local_path)  # type: ignore[arg-type]
            with repo.git.custom_environment(**self._auth_env()):
                repo.git.push(self.get_remote_url(), f"HEAD:{branch}")
            logger.info("Pushed to GitHub branch: {branch}", branch=branch)
        except Exception as exc:
            safe_msg = redact_git_credentials(str(exc)).replace(self._token, "***")
            raise RepositoryAdapterError(
                f"GitHub push failed: {safe_msg}",
                detail={"branch": branch},
            ) from exc

    def pull(self, branch: str = "main") -> None:
        """Pull latest commits from GitHub."""
        self._require_local_path("pull")
        if not GIT_AVAILABLE:
            raise RuntimeError(self._GITPYTHON_ERROR)
        try:
            repo = get_repo(self._local_path)  # type: ignore[arg-type]
            with repo.git.custom_environment(**self._auth_env()):
                repo.git.pull(self.get_remote_url(), branch)
            logger.info("Pulled from GitHub branch: {branch}", branch=branch)
        except Exception as exc:
            safe_msg = redact_git_credentials(str(exc)).replace(self._token, "***")
            raise RepositoryAdapterError(
                f"GitHub pull failed: {safe_msg}",
                detail={"branch": branch},
            ) from exc

    def get_commit_log(self) -> List[Dict[str, Any]]:
        """Return up to 50 commits from GitHub ducta.api."""
        try:
            gh_repo = self._client.get_repo(f"{self._org}/{self._repo_name}")
            commits = gh_repo.get_commits()
            result = []
            for c in commits[:50]:
                result.append(
                    {
                        "sha": c.sha,
                        "short_sha": c.sha[:8],
                        "author": c.commit.author.name or "",
                        "email": c.commit.author.email or "",
                        "message": (c.commit.message or "").strip(),
                        "timestamp": c.commit.author.date.isoformat(),
                        "files_changed": c.stats.total if c.stats else 0,
                        "insertions": c.stats.additions if c.stats else 0,
                        "deletions": c.stats.deletions if c.stats else 0,
                    }
                )
            return result
        except Exception as exc:
            logger.warning("GitHub get_commit_log failed: {exc}", exc=exc)
            raise RepositoryAdapterError(f"GitHub get_commit_log failed: {exc}") from exc

    def set_local_path(self, path: Path) -> None:
        """Set the local workspace path."""
        self._local_path = path

    def _auth_env(self) -> Dict[str, str]:
        """Git config env vars authenticating as this adapter's token (see `http_auth_env`)."""
        return http_auth_env("x-oauth-basic", self._token)

    def _require_local_path(self, operation: str) -> None:
        if not self._local_path:
            raise RepositoryAdapterError(
                f"No local path set for {operation}. Call clone() or set_local_path() first."
            )
