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

import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ducta.api.dependencies import (
    CurrentUserDep,
    ExecutionManagerDep,
    NodeServiceDep,
    SourcePathDep,
    WorkspaceManagerDep,
    require_permission,
)
from ducta.api.exceptions import NodeNotFoundError, http_error_on
from ducta.api.models.dataset import DatasetListResponse
from ducta.api.models.execution import (
    ExecuteRequest,
    ExecutionResponse,
    ExecutionStatus,
    SweepRequest,
    SweepResponse,
)
from ducta.api.models.node_schema import PipelineNodeSchemaResponse, PipelineNodesSchemaResponse
from ducta.api.models.project import (
    ImportProjectRequest,
    ProjectCreateRequest,
    ProjectListResponse,
    ProjectResponse,
    ProjectUpdateRequest,
)
from ducta.api.models.spec import PipelineSpec, pipeline_node_names, validate_pipeline
from ducta.api.services.dataset_service import DatasetService
from ducta.api.services.dependency_graph import DependencyEdge, build_dependency_graph
from ducta.api.services.node_schema_service import NodeSchemaService
from ducta.api.services.project import ProjectService
from ducta.api.utils.validators import validate_environment_name
from ducta.api.workspace.manager import WorkspaceManager
from ducta.api.workspace.preflight import PreflightValidator, run_deep_preflight

router = APIRouter(prefix="/projects", tags=["Projects"])


def _project_svc(source_path: SourcePathDep) -> ProjectService:
    return ProjectService(source_path)


ProjectServiceDep = Annotated[ProjectService, Depends(_project_svc)]


def _dataset_svc(
    source_path: SourcePathDep,
    project_svc: ProjectServiceDep,
    node_svc: NodeServiceDep,
) -> DatasetService:
    return DatasetService(source_path, project_svc, node_svc)


DatasetServiceDep = Annotated[DatasetService, Depends(_dataset_svc)]


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
    spec: PipelineSpec = Field(
        description="Pipeline specification. Documented fields mirror the runtime "
        "schema; unknown keys are preserved verbatim so the YAML round-trip is lossless."
    )
    project_id: str
    commit_sha: Optional[str] = Field(
        default=None,
        description="Commit SHA of pipelines.yaml right after this write — pass it "
        "back as `expected_sha` on the next update/delete to detect a concurrent "
        "edit instead of silently overwriting it.",
    )


class ProjectPipelinesListResponse(BaseModel):
    project_id: str
    pipelines: Dict[str, PipelineSpec] = Field(description="Pipeline name → specification")
    count: int
    commit_sha: Optional[str] = Field(
        default=None,
        description="Commit SHA of this project's pipelines.yaml as a whole — all "
        "pipelines in one project share one file, so OCC is file-scoped, not "
        "per-pipeline. Pass back as `expected_sha` on update/delete.",
    )


class ProjectPipelineCreateRequest(BaseModel):
    name: str = Field(description="Pipeline identifier")
    spec: Dict[str, Any] = Field(description="Pipeline specification")


class ProjectPipelineUpdateRequest(BaseModel):
    spec: Dict[str, Any] = Field(description="Pipeline specification")
    expected_sha: Optional[str] = Field(
        default=None,
        description="Commit SHA the caller last saw (from a previous "
        "ProjectPipelineResponse.commit_sha). If the file changed since, "
        "the update is rejected with 409 instead of overwriting it.",
    )


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
        project_id=project_id,
        pipelines=pipelines,
        count=len(pipelines),
        commit_sha=svc.get_pipelines_commit_sha(project_id),
    )


# ═══════════════════════════════════════════════════════════
# DEPENDENCY GRAPH
# ═══════════════════════════════════════════════════════════


class ProjectDependenciesResponse(BaseModel):
    project_id: str
    pipelines: Dict[str, List[str]] = Field(description="Pipeline name → node names")
    edges: List[DependencyEdge]


@router.get(
    "/{project_id}/dependencies",
    response_model=ProjectDependenciesResponse,
    dependencies=[Depends(require_permission("pipeline.read"))],
    summary="Dependency graph across the project's pipelines (explicit deps + shared datasets)",
)
async def get_project_dependencies(
    project_id: str, svc: ProjectServiceDep, node_svc: NodeServiceDep
) -> ProjectDependenciesResponse:
    pipelines, edges = build_dependency_graph(
        svc.list_project_pipelines(project_id), node_svc.list_nodes()
    )
    return ProjectDependenciesResponse(project_id=project_id, pipelines=pipelines, edges=edges)


# ═══════════════════════════════════════════════════════════
# DATASET REGISTRY
# ═══════════════════════════════════════════════════════════


@router.get(
    "/{project_id}/datasets",
    response_model=DatasetListResponse,
    dependencies=[Depends(require_permission("pipeline.read"))],
    summary="Datasets referenced by a project's pipelines, with their wiring resolved",
    description=(
        "A node declares its I/O as reference names into `input_config` / "
        "`output_config`; this resolves those references and returns the dataset "
        "as a first-class resource — format, filepath, write mode, schema, plus "
        "the node that produces it and every node that consumes it (possibly in "
        "another pipeline of the same project).\n\n"
        "A field is `null` when the registry does not declare it, and "
        "`declared_in` is empty when the reference is dangling. Those are "
        "answers, not gaps to paper over with a default."
    ),
)
async def list_project_datasets(
    project_id: str, svc: ProjectServiceDep, dataset_svc: DatasetServiceDep
) -> DatasetListResponse:
    svc.get_project(project_id)
    return dataset_svc.list_for_project(project_id)


@router.post(
    "/{project_id}/pipelines",
    response_model=ProjectPipelineResponse,
    status_code=201,
    dependencies=[Depends(require_permission("pipeline.write"))],
)
async def create_project_pipeline(
    project_id: str,
    body: ProjectPipelineCreateRequest,
    svc: ProjectServiceDep,
    node_svc: NodeServiceDep,
) -> ProjectPipelineResponse:
    svc.get_project(project_id)
    validate_pipeline(body.name, body.spec, node_svc.list_nodes())
    commit_sha = svc.save_project_pipeline(project_id, body.name, body.spec)
    return ProjectPipelineResponse(
        name=body.name, spec=body.spec, project_id=project_id, commit_sha=commit_sha or None
    )


@router.get(
    "/{project_id}/pipelines/{name}",
    response_model=ProjectPipelineResponse,
    dependencies=[Depends(require_permission("pipeline.read"))],
)
async def get_project_pipeline(
    project_id: str, name: str, svc: ProjectServiceDep
) -> ProjectPipelineResponse:
    spec = svc.get_pipeline(project_id, name)
    return ProjectPipelineResponse(
        name=name,
        spec=spec,
        project_id=project_id,
        commit_sha=svc.get_pipelines_commit_sha(project_id),
    )


@router.put(
    "/{project_id}/pipelines/{name}",
    response_model=ProjectPipelineResponse,
    dependencies=[Depends(require_permission("pipeline.write"))],
)
async def update_project_pipeline(
    project_id: str,
    name: str,
    body: ProjectPipelineUpdateRequest,
    svc: ProjectServiceDep,
    node_svc: NodeServiceDep,
) -> ProjectPipelineResponse:
    svc.get_project(project_id)
    validate_pipeline(name, body.spec, node_svc.list_nodes())
    # A stale `expected_sha` raises ConcurrencyError (409) rather than
    # silently overwriting a concurrent edit.
    commit_sha = svc.save_project_pipeline(
        project_id, name, body.spec, expected_sha=body.expected_sha
    )
    return ProjectPipelineResponse(
        name=name, spec=body.spec, project_id=project_id, commit_sha=commit_sha or None
    )


@router.delete(
    "/{project_id}/pipelines/{name}",
    status_code=204,
    dependencies=[Depends(require_permission("pipeline.write"))],
)
async def delete_project_pipeline(
    project_id: str,
    name: str,
    svc: ProjectServiceDep,
    expected_sha: Optional[str] = Query(
        default=None,
        description="Commit SHA the caller last saw. If pipelines.yaml changed "
        "since, the delete is rejected with 409 instead of dropping it blind.",
    ),
) -> None:
    svc.get_project(project_id)
    # 404 when the pipeline is absent; 409 on a stale `expected_sha`.
    svc.delete_project_pipeline(project_id, name, expected_sha=expected_sha)


# ── Deep preflight ────────────────────────────────────────


class PreflightResponse(BaseModel):
    """Structured result of the deep preflight (same checks as `ducta config validate`)."""

    ok: bool = Field(description="True when no blocking errors were found")
    pipeline: str
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


@router.post(
    "/{project_id}/pipelines/{name}/preflight",
    response_model=PreflightResponse,
    summary="Deep-validate a pipeline before running it",
    description=(
        "Runs the same preflight as `ducta config validate`: imports every node "
        "function and checks its signature, validates I/O catalog keys, intermediate "
        "registration and DAG cycles, in a fresh subprocess so the API process stays "
        "clean. Importing a module runs its top-level code, so this needs the same "
        "permission as running the pipeline."
    ),
    dependencies=[Depends(require_permission("pipeline.execute"))],
)
async def preflight_project_pipeline(
    project_id: str,
    name: str,
    manager: WorkspaceManagerDep,
    svc: ProjectServiceDep,
    env: str = "base",
) -> PreflightResponse:
    svc.get_pipeline(project_id, name)

    # Defense in depth: `env` reaches a subprocess snippet. Validate its shape
    # and, when the workspace declares environments, that it is a known one.
    with http_error_on(400):
        validate_environment_name(env)
    try:
        known_envs = manager.list_environments()
    except Exception:
        known_envs = []
    if known_envs and env not in known_envs and env != "base":
        raise HTTPException(
            status_code=400,
            detail=f"Unknown environment '{env}'. Available: {', '.join(sorted(known_envs))}.",
        )

    exec_source = manager.for_project(project_id).root
    result = await asyncio.to_thread(run_deep_preflight, exec_source, name, env)
    return PreflightResponse(pipeline=name, **result)


# ── ML plan ───────────────────────────────────────────────


class MLPlanResponse(BaseModel):
    """What each ML node of a pipeline will be given (`ducta config show --ml`)."""

    pipeline: str
    env: str
    type: Optional[str] = None
    split_enforcement: Optional[str] = None
    split: Optional[Dict[str, Any]] = None
    hyperparams_config: Optional[Any] = None
    nodes: Dict[str, Dict[str, Any]] = Field(default_factory=dict)


@router.get(
    "/{project_id}/pipelines/{name}/ml-plan",
    response_model=MLPlanResponse,
    summary="What each ML node of a pipeline will be given",
    description=(
        "Per node: its ML stage, the train/test split it receives and where it was "
        "declared, whether it must apply it, its merged hyperparameters and model version — "
        "resolved as the engine resolves them. A serving node's `model_resolution` is the "
        "registered version its stage names right now. Reads configuration and registry "
        "metadata only; no project code is imported. A pipeline without ML returns no nodes."
    ),
    dependencies=[Depends(require_permission("pipeline.read"))],
)
async def ml_plan_project_pipeline(
    project_id: str,
    name: str,
    manager: WorkspaceManagerDep,
    svc: ProjectServiceDep,
    env: str = "base",
) -> MLPlanResponse:
    from ducta.setting.project_inspect import ml_plan
    from ducta.setting.project_loader import ProjectConfigError

    svc.get_pipeline(project_id, name)  # 404 for an unknown project or pipeline
    with http_error_on(400):
        validate_environment_name(env)
    root = manager.for_project(project_id).root
    try:
        plan = ml_plan(root, None if env == "base" else env, name)
    except ProjectConfigError as e:
        raise HTTPException(status_code=400, detail={"problems": e.problems}) from e
    entry = plan.get(name, {})
    nodes = entry.get("nodes") or {}
    if any(item.get("model") for item in nodes.values()):
        from ducta.api.routes.mlops import resolve_served_models

        resolve_served_models(
            nodes, manager.root, None if env == "base" else env, project=project_id
        )
    return MLPlanResponse(pipeline=name, env=env, **entry)


# ── Execute pipeline ──────────────────────────────────────


def _prepare_run(
    project_id: str,
    name: str,
    node_name: Optional[str],
    svc: ProjectService,
    manager: WorkspaceManager,
) -> Path:
    """Checks shared by execute and sweep; returns the directory to run from."""
    spec = svc.get_pipeline(project_id, name)
    PreflightValidator(manager.root).validate_pipeline(name, spec)
    if node_name is not None and node_name not in pipeline_node_names(spec):
        raise NodeNotFoundError(f"Node '{node_name}' not found in pipeline '{name}'")
    return manager.for_project(project_id).root


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
    exec_manager: ExecutionManagerDep,
    manager: WorkspaceManagerDep,
    svc: ProjectServiceDep,
    current_user: CurrentUserDep,
) -> ExecutionResponse:
    exec_source = _prepare_run(project_id, name, body.node_name, svc, manager)

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
    exec_manager: ExecutionManagerDep,
    manager: WorkspaceManagerDep,
    svc: ProjectServiceDep,
    current_user: CurrentUserDep,
) -> SweepResponse:
    exec_source = _prepare_run(project_id, name, body.node_name, svc, manager)
    with http_error_on(422, ValueError, KeyError):
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


# ═══════════════════════════════════════════════════════════
# NODE SCHEMA (Enriched node information with connectivity)
# ═══════════════════════════════════════════════════════════


@router.get(
    "/{project_id}/pipelines/{pipeline_name}/nodes/schema",
    response_model=PipelineNodesSchemaResponse,
    dependencies=[Depends(require_permission("node.read"))],
    summary="Get the enriched schema of every node in a pipeline",
)
def get_pipeline_node_schemas(
    project_id: str,
    pipeline_name: str,
    svc: ProjectServiceDep,
    node_svc: NodeServiceDep,
    exec_manager: ExecutionManagerDep,
    dataset_svc: DatasetServiceDep,
) -> PipelineNodesSchemaResponse:
    """
    Same detail as the per-node schema endpoint, for all of a pipeline's nodes in
    one request, plus the pipeline's latest run.

    A plain ``def`` on purpose: it reads the pipelines file, the node specs and
    each node's source file, so FastAPI runs it in the threadpool instead of on
    the event loop.
    """
    return NodeSchemaService(svc, node_svc, exec_manager, dataset_svc).build_all(
        project_id, pipeline_name
    )


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
    dataset_svc: DatasetServiceDep,
) -> PipelineNodeSchemaResponse:
    """
    Get enriched schema information for a node within a pipeline context.

    Includes:
    - Node metadata (type, module, function, description)
    - Input/output datasets, resolved against ``input_config`` / ``output_config``
      so each carries its real format, filepath, write mode and schema
    - File path, size, existence
    - Quality checks and gate behavior
    - Last execution status, time, and duration
    """
    return NodeSchemaService(svc, node_svc, exec_manager, dataset_svc).build(
        project_id, pipeline_name, node_id
    )
