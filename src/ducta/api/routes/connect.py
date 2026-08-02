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

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger

from ducta.api.dependencies import require_permission
from ducta.api.models.workspace import ConnectRequest, StructureInfo
from ducta.api.source.models import SourceInfo
from ducta.api.source.resolver import SourceResolver
from ducta.api.workspace.structure_detector import StructureDetector

router = APIRouter(prefix="/connect", tags=["Connect"])


@router.post(
    "",
    response_model=SourceInfo,
    summary="Connect to a local directory or Git repository",
    dependencies=[Depends(require_permission("workspace.read"))],
)
async def connect(body: ConnectRequest) -> SourceInfo:
    """Accept local path or Git URL and return source metadata.

    This is a stateless operation — no connection history is persisted.
    """
    if not body.path and not body.git_url:
        raise HTTPException(
            status_code=400,
            detail="Provide either 'path' (local directory) or 'git_url' (Git URL).",
        )

    if body.path and body.git_url:
        raise HTTPException(
            status_code=400,
            detail="Provide only one of 'path' or 'git_url', not both.",
        )

    source = body.path or body.git_url
    assert source is not None  # guaranteed by the checks above

    try:
        info = SourceResolver.get_info(source)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    logger.info(
        "Connected to {path} (type={stype})",
        path=info.path,
        stype=info.source_type,
    )

    return info


@router.get(
    "/structure",
    response_model=StructureInfo,
    summary="Detect directory structure",
    dependencies=[Depends(require_permission("workspace.read"))],
)
async def detect_structure(
    path: Annotated[str, Query(description="Local directory path to analyse")],
) -> StructureInfo:
    """Analyse a directory and return its detected structure type."""
    try:
        resolved = SourceResolver.resolve(path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    structure = StructureDetector.detect(resolved.path)
    return StructureInfo(**structure)
