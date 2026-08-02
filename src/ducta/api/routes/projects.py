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

import uuid
from datetime import datetime, timezone
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ducta.api.dependencies import (
    CurrentUserDep,
    ExecutionManagerDep,
    NodeServiceDep,
    SourcePathDep,
    WorkspaceManagerDep,
    require_permission,
)
from ducta.api.exceptions import NodeNotFoundError, PipelineNotFoundError
from ducta.api.models.execution import (
    ExecuteRequest,
    ExecutionResponse,
    ExecutionStatus,
    SweepRequest,
    SweepResponse,
)
from ducta.api.models.node_schema import PipelineNodeSchemaResponse
from ducta.api.models.project import (
    ImportProjectRequest,
    ProjectCreateRequest,
    ProjectListResponse,
    ProjectResponse,
    ProjectUpdateRequest,
)
from ducta.api.services.node_schema_service import NodeSchemaService
from ducta.api.services.project import ProjectService

router = APIRouter(prefix="/projects", tags=["Projects"])


def _project_svc(source_path: SourcePathDep) -> ProjectService:
    return ProjectService(source_path)


ProjectServiceDep = Annotated[ProjectService, Depends(_project_svc)]


# ═══════════════════════════════════════════════════════════
# PROJECT CRUD
# ═══════════════════════════════════════════════════════════


@router.get(
    "",
    response_model=ProjectListResponse,
    dependencies=[Depends(require_permission("project.read"))],
)
async def list_projects(
    svc: ProjectServiceDep,
    skip: int = 0,
    limit: int = 50,
) -> ProjectListResponse:
    return svc.list_projects_paginated(skip=skip, limit=limit)


@router.post(
    "",
    response_model=ProjectResponse,
    status_code=201,
    dependencies=[Depends(require_permission("project.write"))],
)
async def create_project(body: ProjectCreateRequest, svc: ProjectServiceDep) -> ProjectResponse:
    return svc.create_project(body)


@router.post(
    "/import",
    response_model=ProjectResponse,
    dependencies=[Depends(require_permission("project.write"))],
)
async def import_project(body: ImportProjectRequest, svc: ProjectServiceDep) -> ProjectResponse:
    return svc.import_project(body)


@router.get(
    "/{project_id}",
    response_model=ProjectResponse,
    dependencies=[Depends(require_permission("project.read"))],
)
async def get_project(project_id: str, svc: ProjectServiceDep) -> ProjectResponse:
    return svc.get_project(project_id)


@router.patch(
    "/{project_id}",
    response_model=ProjectResponse,
    dependencies=[Depends(require_permission("project.write"))],
)
async def update_project(
    project_id: str, body: ProjectUpdateRequest, svc: ProjectServiceDep
) -> ProjectResponse:
    return svc.update_project(project_id, body)


@router.delete(
    "/{project_id}", status_code=204, dependencies=[Depends(require_permission("project.write"))]
)
async def delete_project(project_id: str, svc: ProjectServiceDep, force: bool = False) -> None:
    svc.delete_project(project_id, force=force)


# ═══════════════════════════════════════════════════════════
# PIPELINE CRUD (nested under project)
# ═══════════════════════════════════════════════════════════


class ProjectPipelineResponse(BaseModel):
    name: str
    spec: Dict[str, Any]
    project_id: str


class ProjectPipelinesListResponse(BaseModel):
    project_id: str
    pipelines: Dict[str, Any]
    count: int


class ProjectPipelineCreateRequest(BaseModel):
    name: str = Field(description="Pipeline identifier")
    spec: Dict[str, Any] = Field(description="Pipeline specification")


class ProjectPipelineUpdateRequest(BaseModel):
    spec: Dict[str, Any] = Field(description="Pipeline specification")


@router.get(
    "/{project_id}/pipelines",
    response_model=ProjectPipelinesListResponse,
    dependencies=[Depends(require_permission("pipeline.read"))],
)
async def list_project_pipelines(
    project_id: str, svc: ProjectServiceDep
) -> ProjectPipelinesListResponse:
    pipelines = svc.list_project_pipelines(project_id)
    return ProjectPipelinesListResponse(
        project_id=project_id, pipelines=pipelines, count=len(pipelines)
    )


# ═══════════════════════════════════════════════════════════
# DEPENDENCY GRAPH
# ═══════════════════════════════════════════════════════════


class DependencyEdge(BaseModel):
    from_pipeline: str
    from_node: str
    to_pipeline: str
    to_node: str
    dataset: Optional[str] = Field(
        default=None, description="Shared dataset name for dataset-derived edges"
    )
    kind: str = Field(description="'explicit' (node dependencies) or 'dataset' (output→input)")


class ProjectDependenciesResponse(BaseModel):
    project_id: str
    pipelines: Dict[str, List[str]] = Field(description="Pipeline name → node names")
    edges: List[DependencyEdge]


def _as_name_list(value: Any) -> List[str]:
    """Normalize a node-spec input/output/dependencies value to a list of names."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [n if isinstance(n, str) else str(n.get("name") or n.get("id") or "") for n in value]
    return []


@router.get(
    "/{project_id}/dependencies",
    response_model=ProjectDependenciesResponse,
    dependencies=[Depends(require_permission("pipeline.read"))],
    summary="Dependency graph across the project's pipelines (explicit deps + shared datasets)",
)
async def get_project_dependencies(
    project_id: str, svc: ProjectServiceDep, node_svc: NodeServiceDep
) -> ProjectDependenciesResponse:
    pipelines = svc.list_project_pipelines(project_id)
    node_specs: Dict[str, Any] = node_svc.list_nodes()

    # pipeline name → node names (as declared in the pipeline spec)
    pipeline_nodes: Dict[str, List[str]] = {
        name: _as_name_list((spec or {}).get("nodes"))
        for name, spec in pipelines.items()
        if isinstance(spec, dict)
    }
    # node name → pipeline (first pipeline that declares it wins)
    node_pipeline: Dict[str, str] = {}
    for pipe, names in pipeline_nodes.items():
        for n in names:
            node_pipeline.setdefault(n, pipe)

    edges: List[DependencyEdge] = []
    seen: set = set()

    def add_edge(src: str, dst: str, dataset: Optional[str], kind: str) -> None:
        key = (src, dst, dataset if kind == "dataset" else None)
        if src == dst or key in seen:
            return
        seen.add(key)
        edges.append(
            DependencyEdge(
                from_pipeline=node_pipeline[src],
                from_node=src,
                to_pipeline=node_pipeline[dst],
                to_node=dst,
                dataset=dataset,
                kind=kind,
            )
        )

    # dataset name → producing node (only nodes that belong to this project)
    producers: Dict[str, str] = {}
    for node_name in node_pipeline:
        spec = node_specs.get(node_name) or {}
        for out in _as_name_list(spec.get("outputs")):
            if out:
                producers.setdefault(out, node_name)

    for node_name in node_pipeline:
        spec = node_specs.get(node_name) or {}
        for dep in _as_name_list(spec.get("dependencies")):
            if dep in node_pipeline:
                add_edge(dep, node_name, None, "explicit")
        for inp in _as_name_list(spec.get("inputs")):
            producer = producers.get(inp)
            if producer and producer in node_pipeline:
                # Skip dataset edges that shadow an explicit dependency edge.
                if (producer, node_name, None) not in seen:
                    add_edge(producer, node_name, inp, "dataset")

    return ProjectDependenciesResponse(project_id=project_id, pipelines=pipeline_nodes, edges=edges)


@router.post(
    "/{project_id}/pipelines",
    response_model=ProjectPipelineResponse,
    status_code=201,
    dependencies=[Depends(require_permission("pipeline.write"))],
)
async def create_project_pipeline(
    project_id: str, body: ProjectPipelineCreateRequest, svc: ProjectServiceDep
) -> ProjectPipelineResponse:
    svc.get_project(project_id)
    svc.save_project_pipeline(project_id, body.name, body.spec)
    return ProjectPipelineResponse(name=body.name, spec=body.spec, project_id=project_id)


@router.get(
    "/{project_id}/pipelines/{name}",
    response_model=ProjectPipelineResponse,
    dependencies=[Depends(require_permission("pipeline.read"))],
)
async def get_project_pipeline(
    project_id: str, name: str, svc: ProjectServiceDep
) -> ProjectPipelineResponse:
    pipelines = svc.list_project_pipelines(project_id)
    if name not in pipelines:
        raise PipelineNotFoundError(f"Pipeline '{name}' not found in project '{project_id}'")
    return ProjectPipelineResponse(name=name, spec=pipelines[name], project_id=project_id)


@router.put(
    "/{project_id}/pipelines/{name}",
    response_model=ProjectPipelineResponse,
    dependencies=[Depends(require_permission("pipeline.write"))],
)
async def update_project_pipeline(
    project_id: str, name: str, body: ProjectPipelineUpdateRequest, svc: ProjectServiceDep
) -> ProjectPipelineResponse:
    svc.get_project(project_id)
    svc.save_project_pipeline(project_id, name, body.spec)
    return ProjectPipelineResponse(name=name, spec=body.spec, project_id=project_id)


@router.delete(
    "/{project_id}/pipelines/{name}",
    status_code=204,
    dependencies=[Depends(require_permission("pipeline.write"))],
)
async def delete_project_pipeline(project_id: str, name: str, svc: ProjectServiceDep) -> None:
    svc.get_project(project_id)
    svc.delete_project_pipeline(project_id, name)


# ── Deep preflight ────────────────────────────────────────


class PreflightResponse(BaseModel):
    """Structured result of the deep preflight (same checks as `ducta config validate`)."""

    ok: bool = Field(description="True when no blocking errors were found")
    pipeline: str
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


_PREFLIGHT_MARKER = "DUCTA_PREFLIGHT_JSON:"


@router.post(
    "/{project_id}/pipelines/{name}/preflight",
    response_model=PreflightResponse,
    summary="Deep-validate a pipeline before running it",
    description=(
        "Runs the same preflight as `ducta config validate`: imports every node "
        "function and checks its signature, validates I/O catalog keys, intermediate "
        "registration and DAG cycles — without executing anything. Runs in a fresh "
        "subprocess so the API process stays clean."
    ),
    dependencies=[Depends(require_permission("pipeline.read"))],
)
async def preflight_project_pipeline(
    project_id: str,
    name: str,
    source_path: SourcePathDep,
    manager: WorkspaceManagerDep,
    svc: ProjectServiceDep,
    env: str = "base",
) -> PreflightResponse:
    import asyncio
    import json as _json
    import re
    import subprocess
    import sys
    import textwrap

    pipelines = svc.list_project_pipelines(project_id)
    if name not in pipelines:
        raise PipelineNotFoundError(f"Pipeline '{name}' not found in project '{project_id}'")

    # Defense in depth: `env` is interpolated into a subprocess snippet below.
    # `repr()` already escapes it, but validate the shape and, when the workspace
    # declares environments, ensure it is a known one — never trust the raw value.
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", env):
        raise HTTPException(
            status_code=400,
            detail="Invalid 'env': only letters, digits, '_' and '-' are allowed (max 64 chars).",
        )
    try:
        known_envs = manager.list_environments()
    except Exception:
        known_envs = []
    if known_envs and env not in known_envs and env != "base":
        raise HTTPException(
            status_code=400,
            detail=f"Unknown environment '{env}'. Available: {', '.join(sorted(known_envs))}.",
        )

    project_dir = manager.root / "projects" / project_id
    exec_source = project_dir if project_dir.is_dir() else manager.root

    snippet = textwrap.dedent(
        f"""
        import json, sys
        sys.path.insert(0, {str(exec_source)!r})
        from ducta.console.config import ConfigManager
        from ducta.console.execution import ContextInitializer
        from ducta.core.preflight import validate_pipeline
        cm = ConfigManager()
        cm.change_to_config_directory()
        ctx = ContextInitializer(cm).initialize({env!r})
        r = validate_pipeline(ctx, {name!r})
        print({_PREFLIGHT_MARKER!r} + json.dumps(
            {{"ok": r.ok, "errors": r.errors, "warnings": r.warnings}}
        ))
        """
    )

    def _run() -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-c", snippet],
            cwd=str(exec_source),
            capture_output=True,
            text=True,
            timeout=180,
        )

    try:
        proc = await asyncio.to_thread(_run)
    except subprocess.TimeoutExpired:
        return PreflightResponse(ok=False, pipeline=name, errors=["Preflight timed out after 180s"])

    for line in reversed((proc.stdout or "").splitlines()):
        if line.startswith(_PREFLIGHT_MARKER):
            payload = _json.loads(line[len(_PREFLIGHT_MARKER) :])
            return PreflightResponse(pipeline=name, **payload)

    tail = ((proc.stderr or "") + (proc.stdout or ""))[-2000:]
    return PreflightResponse(
        ok=False,
        pipeline=name,
        errors=[f"Preflight subprocess failed (exit {proc.returncode}): {tail.strip()}"],
    )


# ── Execute pipeline ──────────────────────────────────────


@router.post(
    "/{project_id}/pipelines/{name}/execute",
    response_model=ExecutionResponse,
    status_code=202,
    dependencies=[Depends(require_permission("pipeline.execute"))],
)
async def execute_project_pipeline(
    project_id: str,
    name: str,
    body: ExecuteRequest,
    source_path: SourcePathDep,
    exec_manager: ExecutionManagerDep,
    manager: WorkspaceManagerDep,
    svc: ProjectServiceDep,
    current_user: CurrentUserDep,
) -> ExecutionResponse:
    from ducta.api.workspace.preflight import PreflightValidator

    pipelines = svc.list_project_pipelines(project_id)

    if name not in pipelines:
        raise PipelineNotFoundError(f"Pipeline '{name}' not found in project '{project_id}'")

    validator = PreflightValidator(manager.root)
    validator.validate_pipeline(name, pipelines[name])

    # validate_only: return a synthetic completed record without running
    if body.validate_only:
        now = datetime.now(timezone.utc)
        return ExecutionResponse(
            id=str(uuid.uuid4()),
            pipeline_name=name,
            project_id=project_id,
            env=body.env,
            status=ExecutionStatus.SUCCESS,
            dry_run=False,
            started_at=now,
            finished_at=now,
            exit_code=0,
            duration_seconds=0.0,
        )

    project_dir = manager.root / "projects" / project_id
    exec_source = project_dir if project_dir.is_dir() else manager.root

    if body.node_name is not None:
        pipeline_nodes = pipelines[name].get("nodes", [])
        known_names = {
            n if isinstance(n, str) else n.get("name") or n.get("id", "") for n in pipeline_nodes
        }
        if body.node_name not in known_names:
            raise NodeNotFoundError(f"Node '{body.node_name}' not found in pipeline '{name}'")

    return exec_manager.execute(
        source_path=exec_source,
        pipeline_name=name,
        env=body.env,
        node_name=body.node_name,
        dry_run=body.dry_run,
        start_date=body.start_date,
        end_date=body.end_date,
        project_id=project_id,
        user_id=current_user.id,
        model_version=body.model_version,
        hyperparams=body.hyperparams,
        sanity_only=body.sanity_only,
        reuse_upstream=body.reuse_upstream,
        rerun_all=body.rerun_all,
    )


@router.post(
    "/{project_id}/pipelines/{name}/sweep",
    response_model=SweepResponse,
    status_code=202,
    dependencies=[Depends(require_permission("pipeline.execute"))],
    summary="Launch a hyperparameter sweep (one execution per combination)",
)
async def sweep_project_pipeline(
    project_id: str,
    name: str,
    body: SweepRequest,
    source_path: SourcePathDep,
    exec_manager: ExecutionManagerDep,
    manager: WorkspaceManagerDep,
    svc: ProjectServiceDep,
    current_user: CurrentUserDep,
) -> SweepResponse:
    from ducta.api.workspace.preflight import PreflightValidator

    pipelines = svc.list_project_pipelines(project_id)
    if name not in pipelines:
        raise PipelineNotFoundError(f"Pipeline '{name}' not found in project '{project_id}'")

    PreflightValidator(manager.root).validate_pipeline(name, pipelines[name])

    if body.node_name is not None:
        pipeline_nodes = pipelines[name].get("nodes", [])
        known_names = {
            n if isinstance(n, str) else n.get("name") or n.get("id", "") for n in pipeline_nodes
        }
        if body.node_name not in known_names:
            raise NodeNotFoundError(f"Node '{body.node_name}' not found in pipeline '{name}'")

    project_dir = manager.root / "projects" / project_id
    exec_source = project_dir if project_dir.is_dir() else manager.root

    try:
        return exec_manager.execute_sweep(
            source_path=exec_source,
            pipeline_name=name,
            env=body.env,
            sweep=body.sweep,
            node_name=body.node_name,
            start_date=body.start_date,
            end_date=body.end_date,
            model_version=body.model_version,
            base_hyperparams=body.base_hyperparams,
            project_id=project_id,
            user_id=current_user.id,
        )
    except (ValueError, KeyError) as e:
        from fastapi import HTTPException

        raise HTTPException(status_code=422, detail=f"Invalid sweep spec: {e}")


# ═══════════════════════════════════════════════════════════
# NODE SCHEMA (Enriched node information with connectivity)
# ═══════════════════════════════════════════════════════════


@router.get(
    "/{project_id}/pipelines/{pipeline_name}/nodes/{node_id}/schema",
    response_model=PipelineNodeSchemaResponse,
    dependencies=[Depends(require_permission("node.read"))],
    summary="Get enriched node schema with I/O and execution info",
)
async def get_node_schema_in_pipeline(
    project_id: str,
    pipeline_name: str,
    node_id: str,
    svc: ProjectServiceDep,
    node_svc: NodeServiceDep,
    exec_manager: ExecutionManagerDep,
) -> PipelineNodeSchemaResponse:
    """
    Get enriched schema information for a node within a pipeline context.

    Includes:
    - Node metadata (type, module, function, description)
    - Input/output specifications (with required flags derived from edges)
    - File path, size, existence
    - Last execution status, time, and duration
    """
    return NodeSchemaService(svc, node_svc, exec_manager).build(project_id, pipeline_name, node_id)
