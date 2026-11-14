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
    # string in memory (and on disk) — 10 MB is a reasonable ceiling for a
    # single text file.
    content: str = Field(description="File text content to write", max_length=10 * 1024 * 1024)
    expected_version: Optional[str] = Field(
        default=None,
        description="The version this edit was made on. If the file has changed since "
        "(someone else, git, another editor), the write is refused with 409 and the "
        "current content — nothing is overwritten unseen.",
    )
