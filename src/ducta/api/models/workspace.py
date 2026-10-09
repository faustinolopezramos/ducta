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

from pydantic import BaseModel, Field  # type: ignore


class FileEntry(BaseModel):
    """A single entry in a workspace directory listing."""

    name: str = Field(description="File or directory name")
    path: str = Field(description="Path relative to workspace root")
    type: str = Field(description="'file' or 'dir'")
    size: Optional[int] = Field(default=None, description="File size in bytes (files only)")


class FilesListResponse(BaseModel):
    """Response for GET /workspace/files."""

    path: str = Field(description="Directory path relative to workspace root")
    entries: List[FileEntry] = Field(description="Directory entries sorted (dirs first)")


class FileContentResponse(BaseModel):
    """Response for GET /workspace/files/content."""

    path: str = Field(description="File path relative to workspace root")
    content: str = Field(description="File text content")
    size_bytes: int = Field(description="File size in bytes")
    version: str = Field(
        default="", description="Hash of the content — send it back as expected_version"
    )


class WriteFileRequest(BaseModel):
    """Request body for PUT /workspace/files/content."""

    path: str = Field(description="File path relative to workspace root")
    # Unbounded `content` let a single request buffer an arbitrarily large
    # string in memory (and on disk) — 10 MB matches the limit already
    # enforced for config files (see workspace/loaders.py's
    # _MAX_CONFIG_FILE_SIZE) as a reasonable ceiling for a single text file.
    content: str = Field(description="File text content to write", max_length=10 * 1024 * 1024)
    expected_version: Optional[str] = Field(
        default=None,
        description="The version this edit was made on. If the file has changed since "
        "(someone else, git, another editor), the write is refused with 409 and the "
        "current content — nothing is overwritten unseen.",
    )


class ConnectRequest(BaseModel):
    """Source to resolve: a local path or a Git URL, exactly one of them.

    Kept as part of the public ``ducta.api`` models; the ``/api/connect``
    endpoint that used it was removed (``/api/workspace/select`` resolves a
    source now).
    """

    path: Optional[str] = Field(
        default=None,
        description=(
            "Local directory path. Supports ~, environment variables, "
            "and Windows/macOS/Linux paths."
        ),
    )
    git_url: Optional[str] = Field(
        default=None,
        description="Git repository URL (HTTPS or SSH).",
    )
    alias: Optional[str] = Field(
        default=None,
        description="Optional friendly name for this connection.",
    )


class StructureInfo(BaseModel):
    """Response for GET /api/structure — detected directory structure."""

    structure_type: str = Field(
        description=(
            "Detected type: ducta_workspace | config_only | python_project | generic | empty"
        ),
    )
    root: str = Field(description="Absolute path analysed")
    has_project: bool = Field(default=False)
    has_config_dir: bool = Field(default=False)
    has_git: bool = Field(default=False)
    environments: List[str] = Field(default_factory=list)
    config_files: List[str] = Field(default_factory=list)
    python_files: List[str] = Field(default_factory=list)
    directories: List[str] = Field(default_factory=list)
