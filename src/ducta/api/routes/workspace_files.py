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

from fastapi import APIRouter, Depends, Query

from ducta.api.dependencies import WorkspaceManagerDep, require_permission
from ducta.api.exceptions import ConcurrencyError, http_error_on
from ducta.api.models.workspace import FileContentResponse, FilesListResponse, WriteFileRequest
from ducta.api.workspace.manager import FileTooLargeError

router = APIRouter(prefix="/workspace/files", tags=["Files"])


@router.get(
    "",
    response_model=FilesListResponse,
    dependencies=[Depends(require_permission("workspace.read"))],
)
async def list_directory(
    manager: WorkspaceManagerDep,
    path: str = Query(default="", description="Directory path relative to workspace root"),
) -> FilesListResponse:
    """List directory contents inside the workspace."""
    with http_error_on(404):
        entries_raw = manager.list_directory(path)
    return FilesListResponse(path=path, entries=entries_raw)  # type: ignore[arg-type]


@router.get(
    "/content",
    response_model=FileContentResponse,
    dependencies=[Depends(require_permission("workspace.read"))],
)
async def read_file(
    manager: WorkspaceManagerDep,
    path: str = Query(description="File path relative to workspace root"),
) -> FileContentResponse:
    """Read a text file from the workspace."""
    with http_error_on(404), http_error_on(413, FileTooLargeError):
        content = manager.read_file(path)
    return FileContentResponse(
        path=path, content=content, size_bytes=len(content.encode()), version=text_version(content)
    )


@router.put(
    "/content",
    status_code=204,
    dependencies=[Depends(require_permission("workspace.write"))],
)
async def write_file(body: WriteFileRequest, manager: WorkspaceManagerDep) -> None:
    """Create or overwrite a text file in the workspace."""
    if body.expected_version is not None:
        try:
            current = manager.read_file(body.path)
        except Exception:  # noqa: BLE001 — a file that is gone has no version to match
            current = None
        found = text_version(current) if current is not None else ""
        if found != body.expected_version:
            raise ConcurrencyError(
                "The file changed since it was opened",
                detail={"path": body.path, "version": found, "content": current},
            )
    with http_error_on(400):
        manager.write_file(body.path, body.content)


def text_version(text: str) -> str:
    """The optimistic-concurrency token of a text file: a hash of what it holds."""
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


@router.delete(
    "",
    status_code=204,
    dependencies=[Depends(require_permission("workspace.write"))],
)
async def delete_file(
    manager: WorkspaceManagerDep,
    path: str = Query(description="File path relative to workspace root"),
) -> None:
    """Delete a file from the workspace."""
    with http_error_on(404):
        manager.delete_file(path)
