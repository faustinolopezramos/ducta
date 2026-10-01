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

import os
from pathlib import Path
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ducta.api.dependencies import require_permission, resolve_source
from ducta.api.exceptions import http_error_on
from ducta.api.source.models import ResolvedSource, SourceInfo
from ducta.api.source.resolver import SourceResolver

router = APIRouter(prefix="/workspace", tags=["Source"])


def _source_summary(resolved: ResolvedSource) -> dict:
    return {
        "path": str(resolved.path),
        "name": resolved.path.name,
        "source_type": resolved.source_type,
        "has_git": resolved.has_git,
        "has_project": resolved.has_project,
    }


class SourceValidateRequest(BaseModel):
    """Request body for POST /api/workspace/select."""

    path_or_url: str


@router.get(
    "/auto-detect",
    summary="Auto-detect workspace from server CWD or DUCTA_WORKSPACE env var",
    dependencies=[Depends(require_permission("workspace.read"))],
)
async def auto_detect_workspace() -> dict:
    """Return the workspace the server was launched from."""
    source = os.environ.get("DUCTA_WORKSPACE")
    auto_detected = False

    if not source:
        try:
            from ducta.console.ui import _detect_ducta_workspace

            source = _detect_ducta_workspace()
            auto_detected = bool(source)
        except Exception:
            pass

    if not source:
        raise HTTPException(
            status_code=404,
            detail=(
                "No workspace auto-detected. Run `ducta ui` from inside a Ducta project "
                "directory or pass --source <path> to the command."
            ),
        )

    return {**_source_summary(resolve_source(source)), "auto_detected": auto_detected}


@router.get(
    "",
    response_model=SourceInfo,
    summary="Get source info",
    dependencies=[Depends(require_permission("workspace.read"))],
)
async def get_source_info(
    source: Annotated[str, Query(description="Source path (local directory or Git URL)")],
) -> SourceInfo:
    """Resolve a source path/URL and return its metadata."""
    with http_error_on(400, ValueError), http_error_on(500, RuntimeError):
        return SourceResolver.get_info(source)


class BrowseEntry(BaseModel):
    """One directory the caller may descend into or open as a workspace."""

    name: str
    path: str
    is_workspace: bool = False
    has_git: bool = False


class BrowseResponse(BaseModel):
    """A directory listing, plus where the caller is inside the reachable tree."""

    path: str
    parent: Optional[str] = None
    root: str
    entries: list[BrowseEntry]


#: Directories never worth showing in a workspace picker.
_BROWSE_SKIP = frozenset(
    {
        ".git",
        "__pycache__",
        ".venv",
        "venv",
        "node_modules",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "dist",
        "build",
        ".idea",
        ".vscode",
    }
)


@router.get(
    "/browse",
    response_model=BrowseResponse,
    summary="List directories the server can open as a source",
    dependencies=[Depends(require_permission("workspace.read"))],
)
async def browse_directories(
    path: Annotated[Optional[str], Query(description="Directory to list")] = None,
) -> BrowseResponse:
    """Back the local-folder picker in the connect screen."""
    root = SourceResolver._confinement_base()
    target = root if not path or not path.strip() else Path(path.strip())

    try:
        target = target.resolve()
    except (OSError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid path: {exc}") from exc

    if not target.is_relative_to(root):
        raise HTTPException(
            status_code=400,
            detail=(
                f"'{target}' is outside the directory this server can reach "
                f"('{root}'). Restart the server from there to browse it."
            ),
        )
    if not target.is_dir():
        raise HTTPException(status_code=400, detail=f"Not a directory: {target}")

    entries: list[BrowseEntry] = []
    try:
        for item in sorted(target.iterdir(), key=lambda p: p.name.lower()):
            if not item.is_dir() or item.name.startswith(".") or item.name in _BROWSE_SKIP:
                continue
            entries.append(
                BrowseEntry(
                    name=item.name,
                    path=str(item),
                    is_workspace=SourceResolver._looks_like_workspace(item),
                    has_git=(item / ".git").exists(),
                )
            )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=f"Cannot read {target}: {exc}") from exc

    return BrowseResponse(
        path=str(target),
        parent=str(target.parent) if target != root else None,
        root=str(root),
        entries=entries,
    )


@router.post(
    "/select",
    response_model=dict,
    summary="Resolve a source (local or Git clone)",
    dependencies=[Depends(require_permission("workspace.write"))],
)
async def select_source(request: SourceValidateRequest) -> dict:
    """Resolve a local path or clone a Git repo and return its info."""
    resolved = resolve_source(request.path_or_url.strip())
    return {
        "status": "success",
        "source": _source_summary(resolved),
        "message": f"Source resolved: {resolved.path}",
    }
