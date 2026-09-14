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

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

from loguru import logger

try:
    from git import InvalidGitRepositoryError, NoSuchPathError, Repo

    GIT_AVAILABLE = True
except ImportError:  # pragma: no cover
    GIT_AVAILABLE = False
    logger.debug("GitPython not installed — git operations will be unavailable.")


def is_git_repo(path: Path) -> bool:
    """Return True if *path* is inside a git repository."""
    if not GIT_AVAILABLE:
        return False
    try:
        Repo(str(path), search_parent_directories=True)
        return True
    except (InvalidGitRepositoryError, NoSuchPathError):
        return False


def get_repo(path: Path) -> "Repo":
    """Return a GitPython Repo object for the given path."""
    if not GIT_AVAILABLE:
        raise RuntimeError(
            "GitPython is required for git operations. Install it with: pip install gitpython"
        )
    return Repo(str(path), search_parent_directories=True)


def safe_path(base: Path, untrusted: str) -> Path:
    """Resolve untrusted relative to base and guard against path traversal."""
    resolved = (base / untrusted).resolve()
    try:
        resolved.relative_to(base.resolve())
    except ValueError:
        raise ValueError(
            f"Path traversal detected: '{untrusted}' resolves outside workspace '{base}'"
        )
    return resolved


def http_auth_env(username: str, token: str) -> dict:
    """Return GIT_CONFIG_* env vars injecting an HTTP Basic auth header."""
    import base64

    basic = base64.b64encode(f"{username}:{token}".encode()).decode()
    return {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "http.extraHeader",
        "GIT_CONFIG_VALUE_0": f"Authorization: Basic {basic}",
    }


def sanitize_git_remote_url(url: str) -> str:
    """Remove embedded credentials from an HTTP(S) git remote URL."""
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return url
    if parsed.username is None and parsed.password is None:
        return url

    netloc = parsed.hostname or ""
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    return urlunparse(parsed._replace(netloc=netloc))


_URL_CREDENTIALS_RE = re.compile(r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.-]*://)(?P<userinfo>[^/@\s]+@)")


def redact_git_credentials(text: str) -> str:
    """Redact credentials embedded in any git URL substring within *text*."""
    redacted = _URL_CREDENTIALS_RE.sub(r"\g<scheme>", text)
    return redacted


# ── Shared utilities for repositories ────────────────────────────────────────


def commit_files(root: Path, files: list, message: str) -> str:
    """Stage *files* and create a git commit with *message* in *root*."""
    from ducta.api.utils.platform_utils import posix_relative  # avoid circular at module level

    if not GIT_AVAILABLE or not is_git_repo(root):
        logger.warning("Git not available — skipping commit: {msg}", msg=message)
        return ""
    try:
        repo = get_repo(root)
        repo.index.add([posix_relative(Path(p), root) for p in files])
        commit = repo.index.commit(message)
        short_sha = commit.hexsha[:8]
        logger.info("Git commit {sha}: {msg}", sha=short_sha, msg=message)
        return short_sha
    except Exception as exc:
        logger.warning("Git commit failed ({msg}): {exc}", msg=message, exc=exc)
        return ""


def file_commit_sha(root: Path, file_path: Path) -> str:
    """Return the short SHA of the latest commit that touched *file_path*."""
    from ducta.api.utils.platform_utils import posix_relative

    if not GIT_AVAILABLE or not is_git_repo(root):
        return ""
    try:
        repo = get_repo(root)
        commits = list(repo.iter_commits(max_count=1, paths=[posix_relative(file_path, root)]))
        return commits[0].hexsha[:8] if commits else ""
    except Exception as exc:
        logger.warning("Could not get commit SHA for {path}: {exc}", path=file_path, exc=exc)
        return ""


def validate_occ(root: Path, file_path: Path, expected_sha: str | None) -> None:
    """Raise :exc:`~ducta.api.exceptions.ConcurrencyError` if *file_path* has been
    modified since *expected_sha* (Optimistic Concurrency Control)..
    """
    if not expected_sha:
        return
    current = file_commit_sha(root, file_path)
    if current and current != expected_sha:
        from ducta.api.exceptions import ConcurrencyError
        from ducta.api.utils.platform_utils import posix_relative

        raise ConcurrencyError(
            f"Concurrent modification detected on {file_path.name}",
            detail={
                "path": posix_relative(file_path, root),
                "expected_sha": expected_sha,
                "current_sha": current,
                "message": "Another user may have modified this file. Please refresh and try again.",
            },
        )


def format_commit(commit: Any) -> dict:
    """Serialize a GitPython Commit object to a plain dict."""
    stats = commit.stats.total
    return {
        "sha": commit.hexsha,
        "short_sha": commit.hexsha[:8],
        "author": commit.author.name,
        "email": commit.author.email,
        "message": commit.message.strip(),
        "timestamp": datetime.fromtimestamp(commit.authored_date, tz=timezone.utc).isoformat(),
        "files_changed": stats.get("files", 0),
        "insertions": stats.get("insertions", 0),
        "deletions": stats.get("deletions", 0),
    }
