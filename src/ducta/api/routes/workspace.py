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
import subprocess
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ducta.api.dependencies import require_permission
from ducta.api.source.models import SourceInfo
from ducta.api.source.resolver import SourceResolver
from ducta.api.utils.git_utils import sanitize_git_remote_url

router = APIRouter(prefix="/workspace", tags=["Source"])


class SourceValidateRequest(BaseModel):
    """Request body for POST /api/workspace/validate."""

    path_or_url: str


class SourceValidateResponse(BaseModel):
    path: str
    exists: bool = True
    is_directory: bool = True
    has_git: bool = False
    has_environment_yaml: bool = False
    git_remote: Optional[str] = None
    environments: list[str] = []
    warning: Optional[str] = None


@router.get(
    "/auto-detect",
    summary="Auto-detect workspace from server CWD or DUCTA_WORKSPACE env var",
    dependencies=[Depends(require_permission("workspace.read"))],
)
async def auto_detect_workspace() -> dict:
    """Return the workspace the server was launched from.

    Checks (in order):
      1. ``DUCTA_WORKSPACE`` environment variable — set by ``ducta ui`` when it
         auto-detects or receives an explicit ``--source`` argument.
      2. ``_detect_ducta_workspace()`` — walks up from the server's CWD looking
         for ``environment.yaml`` / ``config/`` directories (same logic the CLI uses).

    Returns 200 with ``{ path, auto_detected }`` when a workspace is found, or
    404 when the server has no context about which workspace to use.
    """
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

    try:
        resolved = SourceResolver.resolve(source)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {
        "path": str(resolved.path),
        "name": resolved.path.name,
        "source_type": resolved.source_type,
        "has_git": resolved.has_git,
        "has_environment_yaml": resolved.has_environment_yaml,
        "auto_detected": auto_detected,
    }


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
    try:
        return SourceResolver.get_info(source)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get(
    "/select-path",
    summary="Validate and resolve a source path",
    dependencies=[Depends(require_permission("workspace.read"))],
)
async def select_source_path(
    path: Annotated[str, Query(description="Local path or Git URL")],
) -> dict:
    """Accept a path or URL and return resolution info without workspace requirements."""
    raw_path = path.strip()
    if not raw_path:
        raise HTTPException(status_code=400, detail="Path cannot be empty")

    try:
        resolved = SourceResolver.resolve(raw_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "path": str(resolved.path),
        "exists": True,
        "is_directory": True,
        "source_type": resolved.source_type,
        "has_git": resolved.has_git,
        "has_environment_yaml": resolved.has_environment_yaml,
        "message": "Source path resolved successfully",
    }


@router.post(
    "/validate",
    response_model=SourceValidateResponse,
    summary="Validate a source path or Git URL",
    dependencies=[Depends(require_permission("workspace.read"))],
)
async def validate_source(request: SourceValidateRequest) -> SourceValidateResponse:
    """Validate whether a path/URL can be used as a Ducta source."""
    path_or_url = request.path_or_url.strip()

    is_git_url = path_or_url.startswith(("http://", "https://", "git@", "git://"))

    if is_git_url:
        if not SourceResolver.is_git_url(path_or_url):
            return SourceValidateResponse(
                path=path_or_url,
                exists=False,
                is_directory=False,
                warning="Invalid Git URL format",
            )
        # Don't clone for validation — just confirm URL format is valid
        return SourceValidateResponse(
            path=path_or_url,
            exists=False,
            is_directory=False,
            has_git=True,
            warning="Git URL accepted. Will be cloned on first use.",
        )

    try:
        resolved = SourceResolver.resolve_local(path_or_url)
    except ValueError as exc:
        return SourceValidateResponse(
            path=path_or_url,
            exists=False,
            is_directory=False,
            warning=str(exc),
        )

    has_git = (resolved / ".git").exists()
    has_env = (resolved / "environment.yaml").exists() or (resolved / "environment.yml").exists()

    git_remote: Optional[str] = None
    if has_git:
        try:
            result = subprocess.run(
                ["git", "config", "--get", "remote.origin.url"],
                cwd=str(resolved),
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                git_remote = sanitize_git_remote_url(result.stdout.strip())
        except Exception:
            pass

    return SourceValidateResponse(
        path=str(resolved),
        has_git=has_git,
        has_environment_yaml=has_env,
        git_remote=git_remote,
    )


@router.post(
    "/select",
    response_model=dict,
    summary="Resolve a source (local or Git clone)",
    dependencies=[Depends(require_permission("workspace.write"))],
)
async def select_source(request: SourceValidateRequest) -> dict:
    """Resolve a local path or clone a Git repo and return its info."""
    path_or_url = request.path_or_url.strip()

    try:
        resolved = SourceResolver.resolve(path_or_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "status": "success",
        "source": {
            "path": str(resolved.path),
            "name": resolved.path.name,
            "source_type": resolved.source_type,
            "has_git": resolved.has_git,
            "has_environment_yaml": resolved.has_environment_yaml,
        },
        "message": f"Source resolved: {resolved.path}",
    }
