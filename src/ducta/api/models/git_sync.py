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

from typing import List, Optional

from pydantic import BaseModel, Field


class GitSyncStatus(BaseModel):
    """Current Git repository status (for sync operations)."""

    staged: List[str] = Field(default_factory=list, description="Files staged for commit")
    unstaged: List[str] = Field(default_factory=list, description="Modified files not staged")
    untracked: List[str] = Field(
        default_factory=list, description="Untracked files (only in config/)"
    )
    branch: str = Field(description="Current branch name")
    head: str = Field(description="Current commit hash (short)")
    available: bool = Field(description="Git is available and repo is valid")
    error: Optional[str] = Field(default=None, description="Error message if status failed")


# Alias for backward compatibility
GitStatusResponse = GitSyncStatus


class GitCommitInfo(BaseModel):
    """Information about a single commit."""

    sha: str = Field(description="Commit hash (short)")
    message: str = Field(description="Commit message")
    author: str = Field(description="Author name")
    date: str = Field(description="Commit date (ISO format)")


class GitHistoryResponse(BaseModel):
    """Recent commit history."""

    commits: List[GitCommitInfo] = Field(default_factory=list, description="List of recent commits")
    count: int = Field(description="Number of commits returned")
    available: bool = Field(description="Git is available")


class GitStageRequest(BaseModel):
    """Request to stage changes."""

    paths: Optional[List[str]] = Field(
        default=None, description="Specific paths to stage. If None, stages all config/"
    )
    force: bool = Field(default=False, description="Force staging even if files don't exist")


class GitStageResponse(BaseModel):
    """Response from staging operation."""

    success: bool = Field(description="Whether staging succeeded")
    staged_count: int = Field(description="Number of files staged")
    message: str = Field(description="Status message")
    git_status: GitStatusResponse = Field(description="Current git status")


class GitCommitRequest(BaseModel):
    """Request to commit staged changes."""

    paths: Optional[List[str]] = Field(
        default=None,
        description="Stage exactly these workspace-relative paths first, then commit. "
        "Omitted: commit whatever is already staged.",
    )
    message: Optional[str] = Field(
        default=None, description="Commit message. If None, uses default."
    )
    author_name: Optional[str] = Field(
        default=None, description="Author name. If None, uses configured author."
    )
    author_email: Optional[str] = Field(
        default=None, description="Author email. If None, uses configured email."
    )


class GitCommitResponse(BaseModel):
    """Response from commit operation."""

    success: bool = Field(description="Whether commit succeeded")
    commit_hash: Optional[str] = Field(
        default=None, description="Commit hash (short) if successful"
    )
    message: str = Field(description="Status message")
    git_status: GitStatusResponse = Field(description="Current git status")


class GitExternalChangesResponse(BaseModel):
    """Response from external change detection."""

    has_changes: bool = Field(
        description="True if external changes detected (remote != local HEAD)"
    )
    local_commit: Optional[str] = Field(default=None, description="Local HEAD commit hash")
    remote_commit: Optional[str] = Field(default=None, description="Remote HEAD commit hash")
    force_fetched: bool = Field(description="Whether this check forced a git fetch")


class GitChange(BaseModel):
    """One uncommitted change in the working tree."""

    path: str = Field(description="Workspace-relative path")
    status: str = Field(description="modified | added | deleted | untracked | renamed")
    staged: bool = Field(description="In the index (will be in the next commit)")


class GitChangesResponse(BaseModel):
    available: bool
    branch: str
    changes: List[GitChange] = Field(default_factory=list)


class GitWorkingDiffResponse(BaseModel):
    path: str
    original: str = Field(description="The file at HEAD; empty when it is new")
    modified: str = Field(description="The file on disk; empty when it was deleted")
