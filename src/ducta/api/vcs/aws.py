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

from datetime import datetime, timezone
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


class AWSAdapter(RepositoryAdapter):
    """Adapter for AWS CodeCommit using boto3 + GitPython."""

    _GIT_REQUIRED_ERROR = "GitPython required. Install: pip install gitpython"

    def __init__(self, config: Dict[str, Any]) -> None:
        self._region: str = config.get("region", "")
        self._repo_name: str = config.get("repo", "")
        self._access_key: Optional[str] = config.get("aws_access_key_id")
        self._secret_key: Optional[str] = config.get("aws_secret_access_key")
        self._https_username: Optional[str] = config.get("aws_https_username")
        self._https_password: Optional[str] = config.get("aws_https_password")
        self._local_path: Optional[Path] = None

        if not self._region or not self._repo_name:
            raise ValueError("AWS adapter requires 'region' and 'repo' in config.")

        try:
            import boto3  # type: ignore

            kwargs: Dict[str, Any] = {"region_name": self._region}
            if self._access_key and self._secret_key:
                kwargs["aws_access_key_id"] = self._access_key
                kwargs["aws_secret_access_key"] = self._secret_key
            self._client = boto3.client("codecommit", **kwargs)
        except ImportError as exc:
            raise ImportError(
                "boto3 is required for the AWS adapter. Install with: pip install boto3"
            ) from exc

    def clone(self, url: str, local_path: Path) -> None:
        """Clone from AWS CodeCommit using HTTPS Git credentials."""
        if not GIT_AVAILABLE:
            raise RuntimeError(self._GIT_REQUIRED_ERROR)
        from git import Repo  # noqa: PLC0415

        logger.info(
            "Cloning AWS CodeCommit repo {url} -> {path}",
            url=redact_git_credentials(url),
            path=local_path,
        )
        try:
            Repo.clone_from(url, str(local_path), env=self._auth_env())
        except Exception as exc:
            raise RepositoryAdapterError(
                f"AWS clone failed: {redact_git_credentials(str(exc))}",
                detail={"url": url, "local_path": str(local_path)},
            ) from exc
        self._local_path = local_path

    def get_remote_url(self) -> str:
        """Return the HTTPS clone URL for this CodeCommit repository."""
        return f"https://git-codecommit.{self._region}.amazonaws.com/v1/repos/{self._repo_name}"

    def push(self, branch: str = "main") -> None:
        """Push local commits to AWS CodeCommit."""
        self._require_local_path("push")
        if not GIT_AVAILABLE:
            raise RuntimeError(self._GIT_REQUIRED_ERROR)
        try:
            repo = get_repo(self._local_path)  # type: ignore[arg-type]
            with repo.git.custom_environment(**self._auth_env()):
                repo.git.push(self.get_remote_url(), f"HEAD:{branch}")
            logger.info("Pushed to AWS CodeCommit branch: {branch}", branch=branch)
        except Exception as exc:
            raise RepositoryAdapterError(
                f"AWS push failed: {redact_git_credentials(str(exc))}",
                detail={"branch": branch},
            ) from exc

    def pull(self, branch: str = "main") -> None:
        """Pull latest commits from AWS CodeCommit."""
        self._require_local_path("pull")
        if not GIT_AVAILABLE:
            raise RuntimeError(self._GIT_REQUIRED_ERROR)
        try:
            repo = get_repo(self._local_path)  # type: ignore[arg-type]
            with repo.git.custom_environment(**self._auth_env()):
                repo.git.pull(self.get_remote_url(), branch)
            logger.info("Pulled from AWS CodeCommit branch: {branch}", branch=branch)
        except Exception as exc:
            raise RepositoryAdapterError(
                f"AWS pull failed: {redact_git_credentials(str(exc))}",
                detail={"branch": branch},
            ) from exc

    def get_commit_log(self) -> List[Dict[str, Any]]:
        """Return up to 50 commits by walking the branch HEAD via boto3."""
        try:
            # Determine the default branch
            repo_info = self._client.get_repository(repositoryName=self._repo_name)[
                "repositoryMetadata"
            ]
            default_branch = repo_info.get("defaultBranch", "main")

            branch_info = self._client.get_branch(
                repositoryName=self._repo_name,
                branchName=default_branch,
            )
            current_id: Optional[str] = branch_info["branch"]["commitId"]

            commits: List[Dict[str, Any]] = []
            limit = 50
            while current_id and len(commits) < limit:
                commit_data = self._client.get_commit(
                    repositoryName=self._repo_name,
                    commitId=current_id,
                )["commit"]

                authored_date = commit_data.get("author", {}).get("date", "")
                ts = self._parse_aws_date(authored_date)

                commits.append(
                    {
                        "sha": current_id,
                        "short_sha": current_id[:8],
                        "author": commit_data.get("author", {}).get("name", ""),
                        "email": commit_data.get("author", {}).get("email", ""),
                        "message": commit_data.get("message", "").strip(),
                        "timestamp": ts,
                        "files_changed": 0,
                        "insertions": 0,
                        "deletions": 0,
                    }
                )
                parents = commit_data.get("parents", [])
                current_id = parents[0] if parents else None

            return commits
        except Exception as exc:
            logger.warning("AWS get_commit_log failed: {exc}", exc=exc)
            raise RepositoryAdapterError(
                f"AWS get_commit_log failed: {redact_git_credentials(str(exc))}"
            ) from exc

    def set_local_path(self, path: Path) -> None:
        """Set the local workspace path for git push/pull operations."""
        self._local_path = path

    def _auth_env(self) -> Dict[str, str]:
        """Git config env vars authenticating with the configured HTTPS Git credentials.

        Empty when none are configured (some CodeCommit setups authenticate
        via IAM/`git-remote-codecommit` instead of HTTPS Git credentials).
        See `http_auth_env` for why this is env-based rather than URL-embedded.
        """
        if not (self._https_username and self._https_password):
            return {}
        return http_auth_env(self._https_username, self._https_password)

    @staticmethod
    def _parse_aws_date(date_str: str) -> str:
        """Convert AWS epoch-based date string to ISO-8601."""
        if not date_str:
            return datetime.now(tz=timezone.utc).isoformat()
        try:
            # AWS CodeCommit returns dates as "Fri Jan 01 00:00:00 UTC 2021"
            dt = datetime.strptime(date_str, "%a %b %d %H:%M:%S %Z %Y")
            return dt.replace(tzinfo=timezone.utc).isoformat()
        except (ValueError, TypeError):
            return date_str

    def _require_local_path(self, operation: str) -> None:
        if not self._local_path:
            raise RepositoryAdapterError(
                f"No local path set for {operation}. Call clone() or set_local_path() first."
            )
