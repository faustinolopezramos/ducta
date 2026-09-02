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


class RepositoryAdapter(ABC):
    """Abstraction layer for interacting with remote Git repositories."""

    @abstractmethod
    def clone(self, url: str, local_path: Path) -> None:
        """Clone a remote repository to *local_path*."""

    @abstractmethod
    def get_remote_url(self) -> str:
        """Return the configured remote URL (or empty string for local)."""

    @abstractmethod
    def push(self, branch: str = "main") -> None:
        """Push current commits to remote *branch*."""

    @abstractmethod
    def pull(self, branch: str = "main") -> None:
        """Pull latest commits from remote *branch*."""

    @abstractmethod
    def get_commit_log(self) -> List[Dict[str, Any]]:
        """Return a list of commit info dicts from the remote (or local git)."""

    def set_local_path(self, path: "Path") -> None:
        """Set the local workspace path for git operations."""

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
