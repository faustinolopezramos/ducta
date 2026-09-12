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

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class CommitInfo(BaseModel):
    """Summary information for a single git commit."""

    sha: str = Field(description="Full commit SHA")
    short_sha: str = Field(description="Abbreviated commit SHA (8 chars)")
    author: str = Field(description="Commit author name")
    email: str = Field(description="Commit author email")
    message: str = Field(description="Commit message")
    timestamp: datetime = Field(description="Commit authored timestamp")
    files_changed: int = Field(default=0)
    insertions: int = Field(default=0)
    deletions: int = Field(default=0)


class DiffResponse(BaseModel):
    """Response model for a git diff."""

    commit_a: str = Field(description="Base commit SHA")
    commit_b: str = Field(description="Target commit SHA (defaults to HEAD)")
    path: Optional[str] = Field(default=None, description="File path filter (optional)")
    diff: str = Field(description="Unified diff text")


class BlameLine(BaseModel):
    """A single line of git blame output."""

    line_number: int
    content: str
    sha: str
    author: str
    email: str
    timestamp: datetime


class RevertRequest(BaseModel):
    """Request body for POST /api/git/revert."""

    path: str = Field(description="Relative file path within the workspace to revert")
    commit: str = Field(description="SHA of the commit to restore the file to")
    message: Optional[str] = Field(
        default=None,
        description="Custom commit message for the revert commit",
    )


class RevertResponse(BaseModel):
    """Response for POST /api/git/revert."""

    path: str = Field(description="File path that was reverted")
    restored_from: str = Field(description="Commit SHA the file was restored from")
    new_commit_sha: str = Field(description="SHA of the new revert commit (empty if no git)")


class BlameResponse(BaseModel):
    """Response for GET /api/git/blame/{path}."""

    path: str = Field(description="File path that was blamed")
    lines: List[BlameLine] = Field(description="Line-by-line blame information")


class GitIdentityConfig(BaseModel):
    """Request / response body for reading and writing git author identity."""

    name: str = Field(
        min_length=1,
        max_length=120,
        description="Git author name (stored in .git/config as user.name)",
    )
    email: str = Field(
        min_length=1,
        max_length=254,
        description="Git author e-mail (stored in .git/config as user.email)",
    )


class GitIdentityResponse(BaseModel):
    """Response for GET /api/git/config — includes whether identity is configured."""

    name: Optional[str] = Field(default=None)
    email: Optional[str] = Field(default=None)
    configured: bool = Field(description="True when both name and email are present in git config")


class PlatformInfoResponse(BaseModel):
    """Response for GET /health/platform."""

    os: str = Field(description="Operating system name (Windows / macOS / Linux)")
    os_version: Optional[str] = Field(
        default=None, description="Detailed OS version string (loopback callers only)"
    )
    arch: str = Field(description="CPU architecture (e.g. AMD64, arm64)")
    python: Optional[str] = Field(
        default=None, description="Python interpreter version (loopback callers only)"
    )
    git_available: bool = Field(description="True if the git binary is on PATH")
    git_version: Optional[str] = Field(default=None, description="git version string")
    git_path: Optional[str] = Field(default=None, description="Absolute path to git binary")
