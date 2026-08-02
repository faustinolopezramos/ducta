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

from pathlib import Path
from typing import List, Set

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger

from ducta.api.dependencies import ExecutionManagerDep, WorkspaceManagerDep, require_permission
from ducta.api.models.ingestion import (
    ConnectionCreateRequest,
    ConnectionInfo,
    ConnectionListResponse,
    ConnectionTestRequest,
    ConnectionTestResponse,
    ConnectionUsageItem,
    ConnectionUsageResponse,
)
from ducta.gate.gateway import ConnectionSpec, IngestionService, IngestionServiceError

router = APIRouter(prefix="/ingestion", tags=["Ingestion"])


def _service(manager: WorkspaceManagerDep) -> IngestionService:
    return IngestionService(manager.root)


def _find_pipelines_using_connection(root: Path, connection_name: str) -> List[str]:
    """Best-effort discovery of pipelines that reference a named connection.

    Connections are consumed from arbitrary node source code (``ConnectionManager
    (...).get("name")``), not a declarative config field, so there is no exact
    static answer. This scans node source files for the connection name literal
    and maps hits back to pipelines that include the matching node — good enough
    to point users at relevant execution history, not a guarantee of coverage.
    """
    from ducta.api.services.node_service import NodeService
    from ducta.api.services.project import ProjectService

    node_svc = NodeService(root)
    project_svc = ProjectService(root)

    matching_nodes: Set[str] = set()
    for name in node_svc.list_nodes():
        try:
            info = node_svc.get_node_python_file(name)
        except Exception:
            continue
        if info.exists and connection_name in info.code:
            matching_nodes.add(name)

    if not matching_nodes:
        return []

    pipelines_found: Set[str] = set()
    try:
        all_projects = project_svc.list_projects_paginated(limit=0).projects
    except Exception as exc:
        logger.debug("Could not list projects while resolving connection usage: {}", exc)
        return []

    for project in all_projects:
        try:
            pipelines = project_svc.list_project_pipelines(project.id)
        except Exception:
            continue
        for pipeline_name, spec in pipelines.items():
            node_ids = {
                (n.get("id") or n.get("name")) if isinstance(n, dict) else n
                for n in spec.get("nodes", [])
            }
            if node_ids & matching_nodes:
                pipelines_found.add(pipeline_name)

    return sorted(pipelines_found)


@router.get(
    "/connections",
    response_model=ConnectionListResponse,
    dependencies=[Depends(require_permission("ingestion.read"))],
    summary="List configured database connections",
)
async def list_connections(manager: WorkspaceManagerDep) -> ConnectionListResponse:
    conns = _service(manager).list_connections()
    return ConnectionListResponse(connections=[ConnectionInfo(**c) for c in conns])


@router.get(
    "/connections/{name}",
    response_model=ConnectionInfo,
    dependencies=[Depends(require_permission("ingestion.read"))],
    summary="Show connection details (no credentials)",
)
async def get_connection(name: str, manager: WorkspaceManagerDep) -> ConnectionInfo:
    try:
        return ConnectionInfo(**_service(manager).get_connection(name))
    except IngestionServiceError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get(
    "/connections/{name}/usage",
    response_model=ConnectionUsageResponse,
    dependencies=[Depends(require_permission("ingestion.read"))],
    summary="Show pipelines/executions that (heuristically) use this connection",
)
async def get_connection_usage(
    name: str, manager: WorkspaceManagerDep, exec_manager: ExecutionManagerDep
) -> ConnectionUsageResponse:
    try:
        _service(manager).get_connection(name)
    except IngestionServiceError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    pipelines = _find_pipelines_using_connection(manager.root, name)
    executions: List[ConnectionUsageItem] = []
    for pipeline_name in pipelines:
        recent, _total = exec_manager.list_executions_paginated(
            pipeline_name=pipeline_name, limit=5
        )
        executions.extend(
            ConnectionUsageItem(
                execution_id=e.id,
                pipeline_name=e.pipeline_name,
                project_id=e.project_id,
                status=e.status.value if hasattr(e.status, "value") else str(e.status),
                started_at=e.started_at.isoformat() if e.started_at else None,
            )
            for e in recent
        )
    executions.sort(key=lambda e: e.started_at or "", reverse=True)
    return ConnectionUsageResponse(pipelines=pipelines, executions=executions[:20])


@router.post(
    "/connections/{name}/test",
    response_model=ConnectionTestResponse,
    dependencies=[Depends(require_permission("ingestion.read"))],
    summary="Re-test a saved connection using its stored credentials",
)
async def retest_connection(name: str, manager: WorkspaceManagerDep) -> ConnectionTestResponse:
    try:
        ok = _service(manager).test_connection(name)
    except IngestionServiceError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return ConnectionTestResponse(
        ok=ok,
        message="Connection verified" if ok else "Connection test inconclusive (Spark unavailable)",
    )


@router.post(
    "/connections/test",
    response_model=ConnectionTestResponse,
    dependencies=[Depends(require_permission("ingestion.read"))],
    summary="Test a connection without saving it",
)
async def test_connection(
    body: ConnectionTestRequest, manager: WorkspaceManagerDep
) -> ConnectionTestResponse:
    spec = ConnectionSpec(
        name="__test__",
        source_type=body.type,
        host=body.host,
        port=body.port,
        database=body.database,
        username=body.username,
        password=body.password,
    )
    try:
        ok = _service(manager).test_spec(spec)
    except IngestionServiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return ConnectionTestResponse(
        ok=ok,
        message="Connection verified" if ok else "Connection test inconclusive (Spark unavailable)",
    )


@router.post(
    "/connections",
    response_model=ConnectionInfo,
    status_code=201,
    dependencies=[Depends(require_permission("ingestion.write"))],
    summary="Create or overwrite a database connection",
)
async def create_connection(
    body: ConnectionCreateRequest, manager: WorkspaceManagerDep
) -> ConnectionInfo:
    spec = ConnectionSpec(
        name=body.name,
        source_type=body.type,
        host=body.host,
        port=body.port,
        database=body.database,
        username=body.username,
        password=body.password,
        description=body.description,
    )
    try:
        info = _service(manager).create_connection(spec, overwrite=body.overwrite)
    except IngestionServiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return ConnectionInfo(**info)


@router.delete(
    "/connections/{name}",
    status_code=204,
    dependencies=[Depends(require_permission("ingestion.write"))],
    summary="Remove a database connection",
)
async def delete_connection(name: str, manager: WorkspaceManagerDep) -> None:
    try:
        _service(manager).delete_connection(name)
    except IngestionServiceError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
