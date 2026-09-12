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
from ducta.api.utils.git_utils import GIT_AVAILABLE, http_auth_env, redact_git_credentials
from ducta.api.vcs.base import RepositoryAdapter


class AzureAdapter(RepositoryAdapter):
    """Adapter for Azure Repos using azure-devops-python-api + GitPython."""

    _provider_name = "Azure"

    def __init__(self, config: Dict[str, Any]) -> None:
        self._token: str = config.get("token", "")
        self._org: str = config.get("org", "").rstrip("/")  # strip trailing slash
        self._project: str = config.get("project", "")
        self._repo_name: str = config.get("repo", "")
        self._local_path: Optional[Path] = None

        if not all([self._token, self._org, self._project, self._repo_name]):
            raise ValueError(
                "Azure adapter requires 'token', 'org', 'project', and 'repo' in config."
            )

        try:
            from azure.devops.connection import Connection  # type: ignore
            from msrest.authentication import BasicAuthentication  # type: ignore

            credentials = BasicAuthentication("", self._token)
            self._connection = Connection(base_url=self._org, creds=credentials)
        except ImportError as exc:
            raise ImportError(
                "azure-devops is required for the Azure adapter. "
                "Install with: pip install azure-devops"
            ) from exc

    def clone(self, url: str, local_path: Path) -> None:
        """Clone from Azure Repos using PAT authentication."""
        if not GIT_AVAILABLE:
            raise RuntimeError(self._GIT_REQUIRED_ERROR)
        from git import Repo  # type: ignore

        # Log the original URL (without embedded credentials)
        logger.info(
            "Cloning Azure repo {url} -> {path}", url=redact_git_credentials(url), path=local_path
        )
        try:
            Repo.clone_from(
                url,
                str(local_path),
                env={"GIT_TERMINAL_PROMPT": "0", **self._auth_env()},
            )
        except Exception as exc:
            raise RepositoryAdapterError(
                f"Azure clone failed: {self._safe_error(exc)}",
                detail={"url": url, "local_path": str(local_path)},
            ) from exc
        self._local_path = local_path

    def get_remote_url(self) -> str:
        """Return the HTTPS clone URL for this Azure Repos repository."""
        return f"{self._org}/{self._project}/_git/{self._repo_name}"

    def get_commit_log(self) -> List[Dict[str, Any]]:
        """Return up to 50 commits from Azure DevOps Git ducta.api."""
        try:
            from azure.devops.v7_1.git.models import GitQueryCommitsCriteria  # type: ignore

            git_client = self._connection.clients.get_git_client()
            criteria = GitQueryCommitsCriteria(top=50)
            commits = git_client.get_commits(
                repository_id=self._repo_name,
                search_criteria=criteria,
                project=self._project,
            )
            return [self._format_commit(c) for c in commits or []]
        except Exception as exc:
            logger.warning("Azure get_commit_log failed: {exc}", exc=exc)
            raise RepositoryAdapterError(f"Azure get_commit_log failed: {exc}") from exc

    def _format_commit(self, commit: Any) -> Dict[str, Any]:
        """Format an Azure commit object into a standardized dictionary."""
        author_name = (commit.author.name if commit.author else "") or ""
        author_email = (commit.author.email if commit.author else "") or ""
        timestamp = commit.author.date.isoformat() if commit.author and commit.author.date else ""
        files_changed = commit.change_counts.edit if commit.change_counts else 0

        return {
            "sha": commit.commit_id or "",
            "short_sha": (commit.commit_id or "")[:8],
            "author": author_name,
            "email": author_email,
            "message": (commit.comment or "").strip(),
            "timestamp": timestamp,
            "files_changed": files_changed,
            "insertions": 0,
            "deletions": 0,
        }

    def set_local_path(self, path: Path) -> None:
        """Set the local workspace path for git push/pull operations."""
        self._local_path = path

    def _auth_env(self) -> Dict[str, str]:
        """Git config env vars authenticating with this adapter's PAT (see `http_auth_env`)."""
        return http_auth_env("", self._token)

    def _secret_values(self) -> List[str]:
        return [self._token]
