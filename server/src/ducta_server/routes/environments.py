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

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ducta.project_store.errors import WorkspaceNotFoundError
from ducta_server.dependencies import WorkspaceManagerDep, require_permission

router = APIRouter(prefix="/environments", tags=["Environments"])


class EnvironmentsResponse(BaseModel):
    environments: List[str]
    count: int
    #: base plus the environments the project declares; the others run as base.
    declared: List[str] = []


@router.get(
    "",
    response_model=EnvironmentsResponse,
    summary="List environments",
    dependencies=[Depends(require_permission("workspace.read"))],
)
async def list_environments(
    manager: WorkspaceManagerDep,
    project: Optional[str] = Query(
        default=None, description="Project id to scope to, within the connected workspace"
    ),
) -> EnvironmentsResponse:
    """Return all environment names defined by the project (ducta.yaml)."""
    try:
        manager = manager.for_project(project)
        envs = manager.list_environments()
        declared = manager.declared_environments()
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message)
    return EnvironmentsResponse(environments=envs, count=len(envs), declared=declared)
