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

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List

from loguru import logger

from ducta.api.exceptions import RepositoryAdapterError
from ducta.api.utils.git_utils import GIT_AVAILABLE, get_repo, redact_git_credentials


class RepositoryAdapter(ABC):
    """Abstraction layer for interacting with remote Git repositories."""

    _provider_name: str = "Repository"
    _GIT_REQUIRED_ERROR: str = "GitPython required. Install: pip install gitpython"

    @abstractmethod
    def clone(self, url: str, local_path: Path) -> None:
        """Clone a remote repository to *local_path*."""

    @abstractmethod
    def get_remote_url(self) -> str:
        """Return the configured remote URL (or empty string for local)."""

    @abstractmethod
    def get_commit_log(self) -> List[Dict[str, Any]]:
        """Return a list of commit info dicts from the remote (or local git)."""

    def set_local_path(self, path: "Path") -> None:
        """Set the local workspace path for git operations."""

    def _auth_env(self) -> Dict[str, str]:
        """Git config env vars authenticating remote operations.

        Empty by default (no credentials needed, e.g. local repos);
        subclasses that talk to an authenticated remote override this.
        """
        return {}

    def _secret_values(self) -> List[str]:
        """Raw secret strings (tokens/keys/passwords) to scrub from error text,
        independent of whether they appear embedded in a URL. Empty by default;
        subclasses list every credential value they hold.
        """
        return []

    def _safe_error(self, exc: Exception) -> str:
        """Redact credentials from an exception message before it's user-facing."""
        msg = redact_git_credentials(str(exc))
        for secret in self._secret_values():
            if secret:
                msg = msg.replace(secret, "***")
        return msg

    def _require_local_path(self, operation: str) -> None:
        if not self._local_path:  # type: ignore[attr-defined]
            raise RepositoryAdapterError(
                f"No local path set for {operation}. Call clone() or set_local_path() first."
            )

    def push(self, branch: str = "main") -> None:
        """Push current commits to remote *branch*."""
        self._require_local_path("push")
        if not GIT_AVAILABLE:
            raise RuntimeError(self._GIT_REQUIRED_ERROR)
        try:
            repo = get_repo(self._local_path)  # type: ignore[attr-defined]
            with repo.git.custom_environment(**self._auth_env()):
                repo.git.push(self.get_remote_url(), f"HEAD:{branch}")
            logger.info(
                "Pushed to {provider} branch: {branch}",
                provider=self._provider_name,
                branch=branch,
            )
        except Exception as exc:
            raise RepositoryAdapterError(
                f"{self._provider_name} push failed: {self._safe_error(exc)}",
                detail={"branch": branch},
            ) from exc

    def pull(self, branch: str = "main") -> None:
        """Pull latest commits from remote *branch*."""
        self._require_local_path("pull")
        if not GIT_AVAILABLE:
            raise RuntimeError(self._GIT_REQUIRED_ERROR)
        try:
            repo = get_repo(self._local_path)  # type: ignore[attr-defined]
            with repo.git.custom_environment(**self._auth_env()):
                repo.git.pull(self.get_remote_url(), branch)
            logger.info(
                "Pulled from {provider} branch: {branch}",
                provider=self._provider_name,
                branch=branch,
            )
        except Exception as exc:
            raise RepositoryAdapterError(
                f"{self._provider_name} pull failed: {self._safe_error(exc)}",
                detail={"branch": branch},
            ) from exc

    @staticmethod
    def from_config(config: Dict[str, Any]) -> "RepositoryAdapter":
        """Instantiate the appropriate adapter from a config dict."""
        from ducta.api.vcs.local import LocalAdapter  # type: ignore

        adapter_type = config.get("type", "local")

        if adapter_type == "local":
            return LocalAdapter(config)

        # Fase 2 adapters — imports deferred to avoid hard dependency failures
        if adapter_type == "github":
            from ducta.api.vcs.github import GitHubAdapter  # type: ignore

            return GitHubAdapter(config)

        if adapter_type == "azure":
            from ducta.api.vcs.azure import AzureAdapter  # type: ignore

            return AzureAdapter(config)

        if adapter_type == "aws":
            from ducta.api.vcs.aws import AWSAdapter  # type: ignore

            return AWSAdapter(config)

        raise ValueError(
            f"Unknown repository type: '{adapter_type}'. "
            "Supported types: local, github, azure, aws."
        )
