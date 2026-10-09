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

from ducta.api.config import get_settings
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
from ducta.api.models.problems import ProblemModel, problem_models
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
from ducta.api.utils.validators import validate_environment_name, validate_identifier
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


@router.get(
    "/{project_id}/schema",
    summary="JSON Schema of the project's files",
    description=(
        "The format-2 JSON Schema (`ducta.yaml`, catalog entries, pipeline files, "
        "quality profiles) — what `.ducta/schema/*.json` holds — for editor completion "
        "and client-side validation."
    ),
    dependencies=[Depends(require_permission("project.read"))],
)
async def get_project_schema(project_id: str, svc: ProjectServiceDep) -> Dict[str, Any]:
    from ducta.setting.project_schema import json_schema

    svc.get_project(project_id)  # 404 for an unknown project
    return json_schema()


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
        description="Version token of the project's pipelines/ directory right after "
        "this write (a content hash; saving does not commit) — pass it back as "
        "`expected_sha` on the next update/delete to detect a concurrent edit "
        "instead of silently overwriting it.",
    )


class ProjectPipelinesListResponse(BaseModel):
    project_id: str
    pipelines: Dict[str, PipelineSpec] = Field(description="Pipeline name → specification")
    count: int
    commit_sha: Optional[str] = Field(
        default=None,
        description="Version token (content hash) of this project's pipelines/ "
        "directory as a whole, so OCC is project-scoped, not per-pipeline. Pass "
        "back as `expected_sha` on update/delete.",
    )


class ProjectPipelineCreateRequest(BaseModel):
    name: str = Field(description="Pipeline identifier")
    spec: Dict[str, Any] = Field(description="Pipeline specification")


class ProjectPipelineUpdateRequest(BaseModel):
    spec: Dict[str, Any] = Field(description="Pipeline specification")
    expected_sha: Optional[str] = Field(
        default=None,
        description="Version token the caller last saw (from a previous "
        "ProjectPipelineResponse.commit_sha). If the pipelines changed since, "
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
        description="Version token the caller last saw. If the pipelines changed "
        "since, the delete is rejected with 409 instead of dropping it blind.",
    ),
) -> None:
    svc.get_project(project_id)
    # 404 when the pipeline is absent; 409 on a stale `expected_sha`.
    svc.delete_project_pipeline(project_id, name, expected_sha=expected_sha)


# ── A pipeline file as text; validating drafts ───────────


class PipelineSourceResponse(BaseModel):
    pipeline: str
    file: str = Field(description="Relative to the project root")
    workspace_file: str = Field(description="Relative to the workspace root")
    content: str
    version: str = Field(description="Pass back as `expected_version` to detect a concurrent edit")


class PipelineSourceUpdate(BaseModel):
    content: str = Field(max_length=5 * 1024 * 1024)
    expected_version: Optional[str] = None


class ValidateRequest(BaseModel):
    files: Dict[str, str] = Field(
        default_factory=dict,
        description="Unsaved edits: project-relative path → full text. Validated as if saved.",
    )


class ValidateResponse(BaseModel):
    ok: bool = Field(description="No errors (warnings allowed)")
    problems: List[ProblemModel]


def _pipeline_file(svc: ProjectService, project_id: str, name: str) -> Path:
    """The file itself — found without loading the project, so a project whose
    configuration is broken can still be opened and fixed."""
    from ducta.api.exceptions import PipelineNotFoundError

    with http_error_on(400):
        validate_identifier(name, field="pipeline")
    path = svc.store(project_id).pipeline_path(name)
    if not path.is_file():
        raise PipelineNotFoundError(f"Pipeline '{name}' not found", detail={"pipeline": name})
    return path


def _relative(path: Path, base: Path) -> str:
    try:
        return path.resolve().relative_to(Path(base).resolve()).as_posix()
    except ValueError:
        return path.as_posix()


@router.get(
    "/{project_id}/pipelines/{name}/source",
    response_model=PipelineSourceResponse,
    summary="A pipeline's file, as written",
    description="The YAML file itself — comments and order included — for editing as text.",
    dependencies=[Depends(require_permission("pipeline.read"))],
)
async def get_pipeline_source(
    project_id: str, name: str, svc: ProjectServiceDep
) -> PipelineSourceResponse:
    from ducta.api.utils.git_utils import content_version

    path = _pipeline_file(svc, project_id, name)
    store = svc.store(project_id)
    return PipelineSourceResponse(
        pipeline=name,
        file=_relative(path, store.root),
        workspace_file=_relative(path, svc.workspace_path),
        content=path.read_text(encoding="utf-8") if path.exists() else "",
        version=content_version(path),
    )


@router.put(
    "/{project_id}/pipelines/{name}/source",
    response_model=PipelineSourceResponse,
    summary="Replace a pipeline's file",
    description=(
        "Written as given, kept only if the whole project still validates in every "
        "environment (400 with the problems otherwise; the file is restored). Not committed."
    ),
    dependencies=[Depends(require_permission("pipeline.write"))],
)
async def put_pipeline_source(
    project_id: str, name: str, body: PipelineSourceUpdate, svc: ProjectServiceDep
) -> PipelineSourceResponse:
    path = _pipeline_file(svc, project_id, name)
    store = svc.store(project_id)
    version = await asyncio.to_thread(store.write_text, path, body.content, body.expected_version)
    return PipelineSourceResponse(
        pipeline=name,
        file=_relative(path, store.root),
        workspace_file=_relative(path, svc.workspace_path),
        content=body.content,
        version=version,
    )


@router.post(
    "/{project_id}/validate",
    response_model=ValidateResponse,
    summary="Validate the project, with unsaved edits, without writing",
    description=(
        "The format-2 loader in every environment, then each node's `run:` against its "
        "function's signature (read from the syntax tree; nothing is imported). Every "
        "problem carries its file, line, node and, when there is one, a fix."
    ),
    dependencies=[Depends(require_permission("project.read"))],
)
async def validate_project_draft(
    project_id: str, body: ValidateRequest, svc: ProjectServiceDep
) -> ValidateResponse:
    from ducta.api.services.draft_validation import validate_draft

    # Not get_project(): that loads the configuration, and a project whose
    # configuration is broken is exactly the one that needs validating.
    with http_error_on(400):
        problems = await asyncio.to_thread(validate_draft, svc.store(project_id), body.files)
    models = [ProblemModel.from_problem(p) for p in problems]
    return ValidateResponse(ok=not any(m.severity == "error" for m in models), problems=models)


# ── Freshness: what changed since the last good run ──────


class NodeFreshnessModel(BaseModel):
    node: str
    pipeline: Optional[str] = None
    state: str = Field(description="fresh | stale | never")
    reasons: List[str] = Field(default_factory=list)
    last_run_id: Optional[str] = None
    last_run_at: Optional[str] = None


@router.get(
    "/{project_id}/staleness",
    response_model=List[NodeFreshnessModel],
    summary="Which nodes changed since their last successful run",
    description=(
        "Per node, in `env`: stale when its function changed since its pipeline's last "
        "successful run, or when it reads from a stale node; never when no successful run "
        "included it. Computed from the source and the run certificates; nothing is imported."
    ),
    dependencies=[Depends(require_permission("execution.read"))],
)
async def get_staleness(
    project_id: str, svc: ProjectServiceDep, manager: WorkspaceManagerDep, env: str = "dev"
) -> List[NodeFreshnessModel]:
    from ducta.api.services.run_certificates import latest_successful
    from ducta.api.services.staleness import freshness_dicts, node_freshness

    with http_error_on(400):
        validate_environment_name(env)
    store = svc.store(project_id)

    def compute() -> List[Dict[str, Any]]:
        last_ok = latest_successful(manager.for_project(project_id).root, env)
        return freshness_dicts(node_freshness(store, last_ok))

    return [NodeFreshnessModel(**d) for d in await asyncio.to_thread(compute)]


# ── A node's settings, per environment, with their origin ─


class EffectiveConfigRow(BaseModel):
    key: str
    values: Dict[str, Any]
    sources: Dict[str, str] = Field(
        description="node | pipeline defaults | project defaults | framework default"
    )
    overridden: Dict[str, bool] = Field(description="Per environment: differs from base")


class EffectiveConfigResponse(BaseModel):
    environments: List[str]
    rows: List[EffectiveConfigRow]


@router.get(
    "/{project_id}/pipelines/{name}/nodes/{node}/effective-config",
    response_model=EffectiveConfigResponse,
    summary="A node's settings as they apply in each environment, and where each comes from",
    dependencies=[Depends(require_permission("pipeline.read"))],
)
async def get_node_effective_config(
    project_id: str, name: str, node: str, svc: ProjectServiceDep
) -> EffectiveConfigResponse:
    from ducta.api.exceptions import NodeNotFoundError as _NodeNotFound
    from ducta.setting.node_effective_config import effective_node_config

    store = svc.store(project_id)
    try:
        result = await asyncio.to_thread(effective_node_config, store.root, name, node)
    except KeyError as e:
        raise _NodeNotFound(str(e), detail={"node": node}) from e
    return EffectiveConfigResponse.model_validate(result)


# ── Dataset preview ──────────────────────────────────────


class DatasetColumn(BaseModel):
    name: str
    type: str


class DatasetPreviewResponse(BaseModel):
    dataset: str
    env: str
    available: bool
    reason: Optional[str] = Field(
        default=None, description="Why there is no preview, when there is none"
    )
    path: Optional[str] = None
    format: Optional[str] = None
    columns: List[DatasetColumn] = Field(default_factory=list)
    rows: List[Dict[str, Any]] = Field(default_factory=list)
    total_rows: Optional[int] = None


@router.get(
    "/{project_id}/datasets/{dataset}/preview",
    response_model=DatasetPreviewResponse,
    summary="The first rows and the columns of a dataset, as materialized in an environment",
    dependencies=[Depends(require_permission("execution.read"))],
)
async def preview_dataset(
    project_id: str,
    dataset: str,
    manager: WorkspaceManagerDep,
    env: str = "dev",
    limit: int = Query(default=100, ge=1, le=1000),
    scratch: bool = Query(default=False, description="Read what the last sample run wrote"),
) -> DatasetPreviewResponse:
    from ducta.api.services.dataset_preview import PreviewUnavailable, dataset_location, preview

    with http_error_on(400):
        validate_environment_name(env)
    project_dir = manager.for_project(project_id).root

    def read() -> Dict[str, Any]:
        path, fmt = dataset_location(project_dir, env, dataset, scratch=scratch)
        return preview(path, fmt, limit)

    try:
        data = await asyncio.to_thread(read)
    except KeyError as e:
        raise HTTPException(
            status_code=404, detail=f"No dataset '{dataset}' in this project"
        ) from e
    except PreviewUnavailable as e:
        return DatasetPreviewResponse(dataset=dataset, env=env, available=False, reason=str(e))
    return DatasetPreviewResponse(dataset=dataset, env=env, available=True, **data)


# ── Lint configuration for the editor ────────────────────


@router.get(
    "/{project_id}/ruff-config",
    summary="The project's Ruff settings, for linting and formatting in the editor",
    description="`[tool.ruff]` from pyproject.toml, or ruff.toml / .ruff.toml, as JSON; {} if none.",
    dependencies=[Depends(require_permission("project.read"))],
)
async def get_ruff_config(project_id: str, svc: ProjectServiceDep) -> Dict[str, Any]:
    try:
        import tomllib
    except ImportError:  # Python 3.10
        import tomli as tomllib  # type: ignore[no-redef]

    root = svc.store(project_id).root
    for candidate in (root / "ruff.toml", root / ".ruff.toml"):
        if candidate.is_file():
            with http_error_on(400):
                return tomllib.loads(candidate.read_text(encoding="utf-8"))
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        with http_error_on(400):
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        ruff = (data.get("tool") or {}).get("ruff")
        return ruff if isinstance(ruff, dict) else {}
    return {}


# ── The last successful run of a pipeline ────────────────


class LastSuccessResponse(BaseModel):
    pipeline: str
    env: str
    run_id: Optional[str] = None
    started_at: Optional[str] = None
    git_commit: Optional[str] = Field(
        default=None, description="The commit the run's code was at, when it ran inside git"
    )
    git_dirty: Optional[bool] = Field(default=None, description="It ran uncommitted changes")


@router.get(
    "/{project_id}/pipelines/{name}/last-success",
    response_model=LastSuccessResponse,
    summary="A pipeline's last successful run in an environment, and the commit it ran",
    dependencies=[Depends(require_permission("execution.read"))],
)
async def get_last_success(
    project_id: str, name: str, manager: WorkspaceManagerDep, env: str = "dev"
) -> LastSuccessResponse:
    from ducta.api.services.run_certificates import latest_successful

    with http_error_on(400):
        validate_environment_name(env)
    found = await asyncio.to_thread(latest_successful, manager.for_project(project_id).root, env)
    cert = found.get(name)
    if cert is None:
        return LastSuccessResponse(pipeline=name, env=env)
    environment = cert.get("environment") or {}
    return LastSuccessResponse(
        pipeline=name,
        env=env,
        run_id=cert.get("run_id"),
        started_at=cert.get("started_at"),
        git_commit=environment.get("git_commit"),
        git_dirty=environment.get("git_dirty"),
    )


# ── Metrics and freshness ────────────────────────────────


@router.get(
    "/{project_id}/metrics",
    summary="Runs, success rate, durations and SLA freshness, per pipeline and node",
    description=(
        "Read from the run certificates of `env` over the last `days` days: per pipeline its "
        "runs, success rate, p50/p95 duration, recent trend and whether its last success meets "
        "`metadata.sla`; per node its durations and failures."
    ),
    dependencies=[Depends(require_permission("execution.read"))],
)
async def get_project_metrics(
    project_id: str,
    svc: ProjectServiceDep,
    manager: WorkspaceManagerDep,
    env: str = "dev",
    days: int = Query(default=30, ge=1, le=365),
) -> Dict[str, Any]:
    from ducta.api.services.metrics import project_metrics
    from ducta.api.services.run_certificates import certificates

    with http_error_on(400):
        validate_environment_name(env)
    store = svc.store(project_id)

    def compute() -> Dict[str, Any]:
        slas: Dict[str, Optional[str]] = {}
        try:
            for name, pipeline in store.project().pipelines.items():
                sla = (pipeline.metadata or {}).get("sla")
                slas[name] = str(sla) if sla else None
        except Exception:  # noqa: BLE001 — a project that does not load still has its history
            pass
        root = manager.for_project(project_id).root
        certs = [data for _env, data in certificates(root, env)]
        return project_metrics(certs, slas, days=days)

    return await asyncio.to_thread(compute)


# ── Node templates ───────────────────────────────────────


@router.get(
    "/{project_id}/templates/nodes",
    summary="The project's node templates (templates/nodes/*.yaml)",
    dependencies=[Depends(require_permission("project.read"))],
)
async def list_node_templates(project_id: str, svc: ProjectServiceDep) -> Dict[str, Any]:
    from ducta.setting.project_defaults import NODE_TEMPLATES_DIR, _param_values
    from ducta.setting.project_files import load

    root = svc.store(project_id).root
    out = []
    folder = root / NODE_TEMPLATES_DIR
    for path in sorted(folder.glob("*.y*ml")) if folder.is_dir() else []:
        try:
            doc = load(path)
        except Exception as e:  # noqa: BLE001 — a broken template is listed as broken
            out.append({"name": path.stem, "file": str(path.relative_to(root)), "error": str(e)})
            continue
        declared = (doc.get("params") or {}) if isinstance(doc, dict) else {}
        defaults = _param_values(declared) if isinstance(declared, dict) else {}
        out.append(
            {
                "name": path.stem,
                "file": str(path.relative_to(root)),
                "description": doc.get("description") if isinstance(doc, dict) else None,
                "params": [
                    {
                        "name": k,
                        "required": v in (None, "<required>"),
                        "default": None if v in (None, "<required>") else v,
                    }
                    for k, v in defaults.items()
                ],
                "run": (doc.get("node") or {}).get("run") if isinstance(doc, dict) else None,
            }
        )
    return {"templates": out}


@router.get(
    "/{project_id}/templates/pipelines",
    summary="The project's subpipelines (templates/pipelines/*.yaml)",
    dependencies=[Depends(require_permission("project.read"))],
)
async def list_pipeline_templates(project_id: str, svc: ProjectServiceDep) -> Dict[str, Any]:
    from ducta.setting.project_defaults import PIPELINE_TEMPLATES_DIR, _param_values
    from ducta.setting.project_files import load

    root = svc.store(project_id).root
    folder = root / PIPELINE_TEMPLATES_DIR
    out = []
    for path in sorted(folder.glob("*.y*ml")) if folder.is_dir() else []:
        try:
            doc = load(path)
        except Exception as e:  # noqa: BLE001 — a broken subpipeline is listed as broken
            out.append({"name": path.stem, "file": str(path.relative_to(root)), "error": str(e)})
            continue
        declared = (doc.get("params") or {}) if isinstance(doc, dict) else {}
        defaults = _param_values(declared) if isinstance(declared, dict) else {}
        out.append(
            {
                "name": path.stem,
                "file": str(path.relative_to(root)),
                "description": doc.get("description") if isinstance(doc, dict) else None,
                "nodes": list((doc.get("nodes") or {}).keys()) if isinstance(doc, dict) else [],
                "params": [
                    {
                        "name": k,
                        "required": v in (None, "<required>"),
                        "default": None if v in (None, "<required>") else v,
                    }
                    for k, v in defaults.items()
                ],
            }
        )
    return {"templates": out}


class ExtractSubpipelineRequest(BaseModel):
    template: str = Field(min_length=1, max_length=80)
    nodes: List[str] = Field(min_length=1)
    expected_sha: Optional[str] = None


@router.post(
    "/{project_id}/pipelines/{pipeline_name}/extract-subpipeline",
    summary="Move nodes into a subpipeline and use it in their place",
    description="Writes templates/pipelines/<template>.yaml with the nodes as they are and "
    "replaces them with one `use: pipeline:<template>` node. The expanded pipeline is the same "
    "(names and datasets kept). One validated transaction.",
    dependencies=[Depends(require_permission("pipeline.write"))],
)
async def extract_subpipeline(
    project_id: str, pipeline_name: str, body: ExtractSubpipelineRequest, svc: ProjectServiceDep
) -> Dict[str, Any]:
    store = svc.store(project_id)
    path = await asyncio.to_thread(
        store.extract_subpipeline, pipeline_name, body.nodes, body.template, body.expected_sha
    )
    return {"template": body.template, "file": str(path.relative_to(store.root))}


class ExtractTemplateRequest(BaseModel):
    template: str = Field(min_length=1, max_length=80)
    params: List[str] = Field(default_factory=list, description="Node keys that become parameters")
    expected_sha: Optional[str] = None


@router.post(
    "/{project_id}/pipelines/{pipeline_name}/nodes/{node_name}/extract-template",
    summary="Move a node's configuration into a reusable node template",
    description=(
        "Writes templates/nodes/<template>.yaml with the node's configuration and rewrites "
        "the node as `use: <template>` (its inputs, outputs and depends_on stay). Each key "
        "in `params` becomes a template parameter set by the node's `with`. One validated "
        "transaction: if the project would not load afterwards, nothing changes."
    ),
    dependencies=[Depends(require_permission("pipeline.write"))],
)
async def extract_node_template(
    project_id: str,
    pipeline_name: str,
    node_name: str,
    body: ExtractTemplateRequest,
    svc: ProjectServiceDep,
) -> Dict[str, Any]:
    store = svc.store(project_id)
    path = await asyncio.to_thread(
        store.extract_node_template,
        pipeline_name,
        node_name,
        body.template,
        body.params,
        body.expected_sha,
    )
    return {"template": body.template, "file": str(path.relative_to(store.root))}


# ── Tests from a run ─────────────────────────────────────


def _code_entry(svc: Any, project_id: str, node: str) -> Dict[str, Any]:
    from ducta.api.services.code_index import build_code_index

    index = build_code_index(svc.store(project_id), svc.workspace_path)
    entry = next((n for n in index["nodes"] if n["node"] == node), None)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Node '{node}' runs no project function")
    return entry


class SnapshotTestRequest(BaseModel):
    env: str = "dev"
    rows: int = Field(default=20, ge=1, le=1000)
    overwrite: bool = False


@router.post(
    "/{project_id}/nodes/{node_name}/tests/snapshot",
    summary="Generate a snapshot test for a node from its materialized inputs",
    description=(
        "Writes the first `rows` rows of each input (as materialized in `env`) to "
        "tests/fixtures/<node>/ and tests/test_<node>_snapshot.py, which runs the node's "
        "function on them and pins the output's columns. Refuses to overwrite an existing "
        "test unless `overwrite`."
    ),
    dependencies=[Depends(require_permission("pipeline.write"))],
)
async def generate_node_snapshot_test(
    project_id: str, node_name: str, body: SnapshotTestRequest, svc: ProjectServiceDep
) -> Dict[str, Any]:
    from ducta.api.services.node_tests import generate_snapshot_test

    with http_error_on(400):
        validate_environment_name(body.env)

    def make() -> Dict[str, Any]:
        entry = _code_entry(svc, project_id, node_name)
        store = svc.store(project_id)
        outputs: List[str] = []
        for p in store.project().pipelines.values():
            if node_name in p.nodes:
                outputs = list(getattr(p.nodes[node_name], "outputs", None) or [])
        return generate_snapshot_test(
            project_root=store.root,
            env=body.env,
            node=node_name,
            module=entry["module"],
            function=entry["function"],
            source_file=store.root / entry["file"],
            inputs=entry.get("inputs") or {},
            output=outputs[0] if outputs else None,
            rows=body.rows,
            overwrite=body.overwrite,
        )

    try:
        return await asyncio.to_thread(make)
    except FileExistsError as e:
        raise HTTPException(status_code=409, detail=f"{e} exists — regenerate to replace it") from e
    except LookupError as e:
        raise HTTPException(
            status_code=409,
            detail=f"Not materialized: {e}. Run the pipeline in this environment first.",
        ) from e


@router.get(
    "/{project_id}/nodes/{node_name}/tests",
    summary="The test files that cover a node",
    dependencies=[Depends(require_permission("node.read"))],
)
async def list_node_tests(
    project_id: str, node_name: str, svc: ProjectServiceDep
) -> Dict[str, Any]:
    from ducta.api.services.node_tests import tests_for

    entry = await asyncio.to_thread(_code_entry, svc, project_id, node_name)
    return {"files": tests_for(svc.store(project_id).root, node_name, entry["function"])}


class RunTestsRequest(BaseModel):
    node: Optional[str] = Field(default=None, description="Run the tests that cover this node")
    paths: List[str] = Field(default_factory=list, description="Or these test files / node ids")


@router.post(
    "/{project_id}/tests/run",
    summary="Run the project's tests (for one node, some files, or all) with pytest",
    description=(
        "Runs pytest in the project directory with the API's Python and returns each test's "
        "outcome with the file:line where it failed. Tests run project code: it needs "
        "`pipeline.execute`."
    ),
    dependencies=[Depends(require_permission("pipeline.execute"))],
)
async def run_project_tests(
    project_id: str, body: RunTestsRequest, svc: ProjectServiceDep
) -> Dict[str, Any]:
    from ducta.api.services.node_tests import run_tests, tests_for

    root = svc.store(project_id).root
    targets = list(body.paths)
    if body.node:
        entry = await asyncio.to_thread(_code_entry, svc, project_id, body.node)
        targets += tests_for(root, body.node, entry["function"])
        if not targets:
            return {
                "ok": True,
                "tests": [],
                "summary": {},
                "output": "No tests cover this node yet.",
            }
    for t in targets:
        target = (root / t.split("::")[0]).resolve()
        if root.resolve() not in target.parents:
            raise HTTPException(status_code=400, detail=f"{t} is outside the project")
    return await asyncio.to_thread(run_tests, root, targets)


# ── Quality: a node's checks, tried on its data ──────────


@router.get(
    "/{project_id}/pipelines/{pipeline_name}/nodes/{node_name}/quality",
    summary="A node's quality block as written, and the datasets it writes",
    dependencies=[Depends(require_permission("node.read"))],
)
async def get_node_quality(
    project_id: str, pipeline_name: str, node_name: str, svc: ProjectServiceDep
) -> Dict[str, Any]:
    from ducta.setting.project_loader import read_project

    root = svc.store(project_id).root

    def read() -> Dict[str, Any]:
        located = read_project(root, expand=False)
        node = ((located.pipelines.get(pipeline_name) or {}).get("nodes") or {}).get(node_name)
        if not isinstance(node, dict):
            raise HTTPException(
                status_code=404, detail=f"Node '{node_name}' is not written in '{pipeline_name}'"
            )
        outputs = node.get("outputs") or []
        return {
            "quality": node.get("quality"),
            "outputs": list(outputs) if isinstance(outputs, list) else [],
            "uses_template": node.get("use"),
            "kind": node.get("kind", "transform"),
            "ingest": node.get("ingest"),
        }

    return await asyncio.to_thread(read)


_SQL_DIALECTS = {
    "sqlserver": "tsql",
    "postgresql": "postgres",
    "mysql": "mysql",
    "mariadb": "mysql",
    "oracle": "oracle",
    "snowflake": "snowflake",
}


@router.get(
    "/{project_id}/pipelines/{pipeline_name}/nodes/{node_name}/column-lineage",
    summary="Which source columns each column an ingest node writes comes from",
    description="From the node's query (parsed with sqlglot, in its connection's dialect) or "
    "its table and columns. Python transforms are not analysed.",
    dependencies=[Depends(require_permission("node.read"))],
)
async def get_column_lineage(
    project_id: str, pipeline_name: str, node_name: str, svc: ProjectServiceDep
) -> Dict[str, Any]:
    from ducta.api.services.column_lineage import ingest_column_lineage
    from ducta.gate.gateway.service import IngestionService
    from ducta.setting.project_loader import read_project

    root = svc.store(project_id).root

    def run() -> Dict[str, Any]:
        located = read_project(root, expand=False)
        node = ((located.pipelines.get(pipeline_name) or {}).get("nodes") or {}).get(node_name)
        if not isinstance(node, dict) or not isinstance(node.get("ingest"), dict):
            return {"columns": [], "note": "Only ingest nodes (SQL) have column lineage here"}
        ingest = node["ingest"]
        dialect = None
        try:
            kind = IngestionService(root).get_connection(str(ingest.get("source"))).get("type")
            dialect = _SQL_DIALECTS.get(str(kind or "").lower())
        except Exception:  # noqa: BLE001 — unknown connection: generic SQL
            pass
        return {**ingest_column_lineage(ingest, dialect), "dialect": dialect}

    return await asyncio.to_thread(run)


class TryChecksRequest(BaseModel):
    dataset: str
    env: str = "dev"
    checks: Dict[str, Any] = Field(description="check name → its parameters, as in a quality block")
    rows: int = Field(default=10_000, ge=1, le=1_000_000)


@router.post(
    "/{project_id}/quality/try",
    summary="Try quality checks on a dataset's data, without saving them or a report",
    description=(
        "Reads up to `rows` rows of `dataset` as materialized in `env` and runs `checks` on "
        "them: what a draft of a quality block would say about the data there now."
    ),
    dependencies=[Depends(require_permission("quality.run"))],
)
async def try_quality_checks(
    project_id: str, body: TryChecksRequest, svc: ProjectServiceDep
) -> Dict[str, Any]:
    from ducta.api.services.dataset_preview import PreviewUnavailable, dataset_location, read_frame

    with http_error_on(400):
        validate_environment_name(body.env)
    root = svc.store(project_id).root

    def run() -> Dict[str, Any]:
        import tempfile

        from ducta.check import ValidationPhaseRunner

        try:
            path, fmt = dataset_location(root, body.env, body.dataset)
            df, _cols, total = read_frame(path, fmt, body.rows)
        except KeyError as e:
            raise HTTPException(status_code=404, detail=f"No dataset '{body.dataset}'") from e
        except PreviewUnavailable as e:
            raise HTTPException(status_code=409, detail=str(e)) from e
        # A scratch workspace: trying checks must not leave reports behind.
        from ducta.check.core import QualityChecksFailed

        with tempfile.TemporaryDirectory(prefix="ducta-try-") as tmp:
            runner = ValidationPhaseRunner(workspace_path=tmp, fail_fast=False)
            try:
                report = runner.run(
                    dataset_name=body.dataset, df=df, config={"checks": body.checks}
                )
                results = report.to_dict().get("results") or []
            except QualityChecksFailed as failed:  # failing checks are the answer, not an error
                results = failed.to_dict()["results"]
        for r in results:
            # Trying runs on pandas; a check that needs Spark (SQL rules) was not
            # tried — reporting it as failed would blame the data for the engine.
            errors = ((r.get("details") or {}).get("rule_errors") or {}).values()
            if errors and all("only supported for spark" in str(e).lower() for e in errors):
                params = body.checks.get(r.get("check_name"), {}) or {}
                try:
                    from ducta.api.services.failing_rows import failing_mask

                    failing = int(failing_mask(df, "business_rules", params).sum())
                except Exception:  # noqa: BLE001 — a rule sqlglot cannot evaluate
                    r["passed"] = None
                    r["not_tried"] = True
                    r["message"] = (
                        "Not tried here: these SQL rules run on Spark, in a real or sample run"
                    )
                    continue
                allowed = int(params.get("max_failures_allowed") or 0)
                r["passed"] = failing <= allowed
                r["message"] = (
                    f"{failing} row(s) break the rules"
                    + (f" (up to {allowed} allowed)" if allowed else "")
                    + " — evaluated here with sqlglot"
                )
        return {
            "dataset": body.dataset,
            "env": body.env,
            "passed": all(r.get("passed") is not False for r in results),
            "results": results,
            "sampled_rows": len(df),
            "total_rows": total,
        }

    with http_error_on(422, ValueError):
        return await asyncio.to_thread(run)


class FailingRowsRequest(BaseModel):
    dataset: str
    env: str = "dev"
    check: str
    params: Dict[str, Any] = Field(default_factory=dict)
    rows: int = Field(default=100_000, ge=1, le=1_000_000, description="Rows to scan")
    limit: int = Field(default=50, ge=1, le=1000, description="Failing rows to return")


@router.post(
    "/{project_id}/quality/failing-rows",
    summary="The rows a quality check fails on",
    description="For checks whose verdict is about rows (null_rate, range, duplicates, "
    "prediction_contract, SQL business_rules): the failing rows of `dataset` as materialized "
    "in `env`, up to `limit`, and how many there are among the rows scanned.",
    dependencies=[Depends(require_permission("quality.read"))],
)
async def get_failing_rows(
    project_id: str, body: FailingRowsRequest, svc: ProjectServiceDep
) -> Dict[str, Any]:
    from ducta.api.services.dataset_preview import PreviewUnavailable, dataset_location, read_frame
    from ducta.api.services.failing_rows import failing_rows

    with http_error_on(400):
        validate_environment_name(body.env)
    root = svc.store(project_id).root

    def run() -> Dict[str, Any]:
        try:
            path, fmt = dataset_location(root, body.env, body.dataset)
            df, _cols, _total = read_frame(path, fmt, body.rows)
        except KeyError as e:
            raise HTTPException(status_code=404, detail=f"No dataset '{body.dataset}'") from e
        except PreviewUnavailable as e:
            raise HTTPException(status_code=409, detail=str(e)) from e
        try:
            return failing_rows(df, body.check, body.params, body.limit)
        except (ValueError, KeyError) as e:
            raise HTTPException(status_code=422, detail=str(e)) from e

    return await asyncio.to_thread(run)


# ── Where things are written ─────────────────────────────


def _split_location(loc: str) -> Dict[str, Any]:
    file, _, line = loc.rpartition(":")
    return {"file": file, "line": int(line)} if line.isdigit() else {"file": loc, "line": None}


@router.get(
    "/{project_id}/locations",
    summary="Where each dataset, pipeline and node is written (file:line)",
    description="For go-to-definition in the editor: a dataset to its catalog entry, a node to "
    "its block in the pipeline file. Read without loading the project's code.",
    dependencies=[Depends(require_permission("project.read"))],
)
async def get_locations(project_id: str, svc: ProjectServiceDep) -> Dict[str, Any]:
    from ducta.setting.project_loader import read_project

    root = svc.store(project_id).root

    def read() -> Dict[str, Any]:
        located = read_project(root, expand=False)
        datasets: Dict[str, Any] = {}
        nodes: Dict[str, Any] = {}
        pipelines: Dict[str, Any] = {}
        for key, loc in located.where.items():
            if len(key) == 2 and key[0] == "catalog":
                datasets[key[1]] = _split_location(loc)
            elif len(key) == 4 and key[0] == "pipelines" and key[2] == "nodes":
                nodes[key[3]] = {**_split_location(loc), "pipeline": key[1]}
        for name, path in located.pipeline_files.items():
            pipelines[name] = {"file": path.relative_to(root).as_posix(), "line": 1}
        return {"datasets": datasets, "nodes": nodes, "pipelines": pipelines}

    with http_error_on(400, Exception):
        return await asyncio.to_thread(read)


# ── Governance ───────────────────────────────────────────


@router.get(
    "/{project_id}/governance",
    summary="Protected environments, and whether the current user may run in them",
    dependencies=[Depends(require_permission("project.read"))],
)
async def get_governance(
    project_id: str, svc: ProjectServiceDep, current_user: CurrentUserDep
) -> Dict[str, Any]:
    from ducta.api.services.governance import PROTECTED_PERMISSION, protected_environments

    protected = await asyncio.to_thread(protected_environments, svc.store(project_id).root)
    return {
        "protected_environments": protected,
        "can_run_protected": current_user.has_permission(PROTECTED_PERMISSION),
        "permission": PROTECTED_PERMISSION,
    }


# ── Comments ─────────────────────────────────────────────


def _comment_store(svc: Any, project_id: str) -> Any:
    from ducta.api.services.comments import LocalCommentStore

    return LocalCommentStore(svc.store(project_id).root)


def _author(user: Any, root: Path) -> str:
    """Who is commenting: the signed-in user, or — on a local server without
    accounts — the name git knows the developer by."""
    if get_settings().auth_enabled:
        return user.username
    try:
        from git import Repo

        with Repo(root, search_parent_directories=True) as repo:
            return str(repo.config_reader().get_value("user", "name", user.username))
    except Exception:  # noqa: BLE001 — no repo, no name: the account name will do
        return user.username


class CommentRequest(BaseModel):
    anchor: Dict[str, Any] = Field(
        description="{pipeline, node} for a node, or {file, line} for a line of code"
    )
    body: str = Field(min_length=1, max_length=10_000)


class ReplyRequest(BaseModel):
    body: str = Field(min_length=1, max_length=10_000)


class ResolveRequest(BaseModel):
    resolved: bool = True


@router.get(
    "/{project_id}/comments",
    summary="Comment threads on the project's nodes and code",
    dependencies=[Depends(require_permission("project.read"))],
)
async def list_comments(
    project_id: str,
    svc: ProjectServiceDep,
    node: Optional[str] = None,
    pipeline: Optional[str] = None,
    file: Optional[str] = None,
    include_resolved: bool = True,
) -> Dict[str, Any]:
    threads = _comment_store(svc, project_id).list(node=node, pipeline=pipeline, file=file)
    if not include_resolved:
        threads = [t for t in threads if not t.resolved]
    return {"threads": [t.to_dict() for t in threads]}


@router.post(
    "/{project_id}/comments",
    summary="Start a comment thread on a node or a line of code",
    dependencies=[Depends(require_permission("pipeline.write"))],
)
async def add_comment(
    project_id: str, body: CommentRequest, svc: ProjectServiceDep, current_user: CurrentUserDep
) -> Dict[str, Any]:
    store = _comment_store(svc, project_id)
    with http_error_on(400, ValueError):
        thread = store.add(body.anchor, _author(current_user, store.dir.parent.parent), body.body)
    return thread.to_dict()


@router.post(
    "/{project_id}/comments/{thread_id}/replies",
    summary="Reply to a comment thread",
    dependencies=[Depends(require_permission("pipeline.write"))],
)
async def reply_to_comment(
    project_id: str,
    thread_id: str,
    body: ReplyRequest,
    svc: ProjectServiceDep,
    current_user: CurrentUserDep,
) -> Dict[str, Any]:
    from ducta.api.services.comments import CommentNotFound

    store = _comment_store(svc, project_id)
    try:
        with http_error_on(400, ValueError):
            thread = store.reply(
                thread_id, _author(current_user, store.dir.parent.parent), body.body
            )
    except CommentNotFound as e:
        raise HTTPException(status_code=404, detail="No such comment thread") from e
    return thread.to_dict()


@router.patch(
    "/{project_id}/comments/{thread_id}",
    summary="Resolve or reopen a comment thread",
    dependencies=[Depends(require_permission("pipeline.write"))],
)
async def resolve_comment(
    project_id: str,
    thread_id: str,
    body: ResolveRequest,
    svc: ProjectServiceDep,
    current_user: CurrentUserDep,
) -> Dict[str, Any]:
    from ducta.api.services.comments import CommentNotFound

    store = _comment_store(svc, project_id)
    try:
        thread = store.resolve(
            thread_id, _author(current_user, store.dir.parent.parent), body.resolved
        )
    except CommentNotFound as e:
        raise HTTPException(status_code=404, detail="No such comment thread") from e
    return thread.to_dict()


@router.delete(
    "/{project_id}/comments/{thread_id}",
    summary="Delete a comment thread (its author, or an admin)",
    dependencies=[Depends(require_permission("pipeline.write"))],
)
async def delete_comment(
    project_id: str, thread_id: str, svc: ProjectServiceDep, current_user: CurrentUserDep
) -> Dict[str, Any]:
    from ducta.api.services.comments import CommentNotFound

    store = _comment_store(svc, project_id)
    try:
        thread = store.get(thread_id)
    except CommentNotFound as e:
        raise HTTPException(status_code=404, detail="No such comment thread") from e
    me = _author(current_user, store.dir.parent.parent)
    if thread.author != me and "admin" not in (current_user.roles or []):
        raise HTTPException(status_code=403, detail="Only its author or an admin deletes a thread")
    store.delete(thread_id)
    return {"deleted": thread_id}


# ── Debugger ─────────────────────────────────────────────


def _check_debug_allowed() -> None:
    from ducta.api.services import debugger

    if get_settings().auth_enabled and not get_settings().debug:
        # A shared server: a debugger can read and change anything in the process.
        raise HTTPException(
            status_code=403,
            detail="Debug runs are for a local server (auth off, or DEBUG=true)",
        )
    if not debugger.available():
        raise HTTPException(
            status_code=409,
            detail="debugpy is not installed where the API runs: pip install debugpy",
        )


@router.get(
    "/{project_id}/debugger",
    summary="Whether a run can be debugged, and how to attach an IDE",
    dependencies=[Depends(require_permission("pipeline.execute"))],
)
async def get_debugger(project_id: str, manager: WorkspaceManagerDep) -> Dict[str, Any]:
    from ducta.api.services import debugger

    root = manager.for_project(project_id).root
    port = debugger.DEFAULT_PORT  # each debug run has its own; this is the IDE example's
    allowed = not (get_settings().auth_enabled and not get_settings().debug)
    return {
        "available": debugger.available() and allowed,
        "reason": None
        if debugger.available() and allowed
        else ("Debug runs are for a local server" if not allowed else "pip install debugpy"),
        "host": debugger.HOST,
        "port": port,
        "root": str(root.resolve()),
        "vscode": debugger.attach_config(root, port),
    }


# ── Alerts ───────────────────────────────────────────────


@router.get(
    "/{project_id}/alerts",
    summary="The project's alert rules (`alerts:` in ducta.yaml)",
    dependencies=[Depends(require_permission("project.read"))],
)
async def get_alert_rules(project_id: str, svc: ProjectServiceDep) -> Dict[str, Any]:
    import os

    rules = svc.store(project_id).project().project.alerts
    out = []
    for rule in rules:
        channels = []
        for c in rule.channels:
            var = c.webhook_env or c.url_env
            channels.append(
                {
                    **c.model_dump(),
                    # Whether the secret is there — never its value.
                    "configured": bool(os.environ.get(var))
                    if var
                    else bool(os.environ.get("DUCTA_SMTP_HOST")),
                }
            )
        out.append({"when": list(rule.when), "pipelines": rule.pipelines, "channels": channels})
    return {"rules": out}


class AlertTestRequest(BaseModel):
    rule: int = Field(ge=0, description="Index of the rule in `alerts:`")


@router.post(
    "/{project_id}/alerts/test",
    summary="Send a test message through one rule's channels",
    dependencies=[Depends(require_permission("project.write"))],
)
async def test_alert_rule(
    project_id: str, body: AlertTestRequest, svc: ProjectServiceDep
) -> Dict[str, Any]:
    from ducta.api.services.alerts import AlertEvent, deliver

    rules = svc.store(project_id).project().project.alerts
    if body.rule >= len(rules):
        raise HTTPException(status_code=404, detail=f"There is no alert rule #{body.rule}")
    rule = rules[body.rule]
    event = AlertEvent(
        kind=rule.when[0],
        project=project_id,
        pipeline=rule.pipelines[0].replace("*", "example"),
        env="test",
        summary="This is a test alert from Ducta — nothing failed.",
    )
    return {"results": await asyncio.to_thread(deliver, event, [rule])}


@router.post(
    "/{project_id}/alerts/check",
    summary="Alert on pipelines late for their SLA (call it from a schedule)",
    description=(
        "For every pipeline with `metadata.sla` whose last success in `env` is too old, "
        "send the rules listening for `sla_miss`. Meant to be called periodically — a "
        "schedule, cron — since nothing else notices that a run did not happen."
    ),
    dependencies=[Depends(require_permission("pipeline.execute"))],
)
async def check_alerts(
    project_id: str, svc: ProjectServiceDep, manager: WorkspaceManagerDep, env: str = "prod"
) -> Dict[str, Any]:
    from ducta.api.services.alerts import check_sla

    with http_error_on(400):
        validate_environment_name(env)
    store = svc.store(project_id)
    return await asyncio.to_thread(check_sla, project_id, store, env)


# ── Canvas edits ──────────────────────────────────────────


class PipelineOpsRequest(BaseModel):
    ops: List[Dict[str, Any]] = Field(
        min_length=1,
        max_length=200,
        description="connect | disconnect | add_output | remove_output | add_node | "
        "remove_node | set — applied in order, all or none",
    )
    expected_version: Optional[str] = Field(
        default=None, description="The pipelines' version this edit was made against (OCC)"
    )
    new_datasets: Dict[str, Dict[str, Any]] = Field(
        default_factory=dict,
        description="Datasets the edit introduces: name → catalog entry. Added to the catalog "
        "file their layer belongs in; existing names are left alone.",
    )


class PipelineOpsResponse(BaseModel):
    version: str = Field(description="The pipelines' new version — the next expected_version")
    inverse: List[Dict[str, Any]] = Field(description="Operations that undo this edit, in order")


@router.post(
    "/{project_id}/pipelines/{name}/ops",
    response_model=PipelineOpsResponse,
    summary="Edit a pipeline the way the canvas does",
    description=(
        "Small edits to the pipeline's file — connect a dataset to a node, add or remove a "
        "node, set one of its keys — applied to the YAML in place (comments and order kept), "
        "validated with the whole project, not committed. The response carries the inverse "
        "operations, which undo it."
    ),
    dependencies=[Depends(require_permission("pipeline.write"))],
)
async def apply_pipeline_ops(
    project_id: str, name: str, body: PipelineOpsRequest, svc: ProjectServiceDep
) -> PipelineOpsResponse:
    store = svc.store(project_id)
    version, inverse = await asyncio.to_thread(
        store.apply_pipeline_ops, name, body.ops, body.expected_version, body.new_datasets
    )
    return PipelineOpsResponse(version=version, inverse=inverse)


# ── Environments, side by side ───────────────────────────


class EnvironmentRow(BaseModel):
    key: str = Field(description="Dotted path, e.g. settings.max_parallel_nodes")
    values: Dict[str, Any] = Field(description="Effective value per environment ('base' first)")
    differs: bool = Field(description="Some environment changes it")
    overridden: Dict[str, bool] = Field(description="Per environment: differs from base")


class EnvironmentsCompareResponse(BaseModel):
    environments: List[str]
    rows: List[EnvironmentRow]


@router.get(
    "/{project_id}/environments/compare",
    response_model=EnvironmentsCompareResponse,
    summary="Effective configuration per environment, side by side",
    description=(
        "Every `paths` and `settings` value in force in each environment, plus the catalog "
        "and pipeline values an environment changes."
    ),
    dependencies=[Depends(require_permission("project.read"))],
)
async def compare_project_environments(
    project_id: str, svc: ProjectServiceDep
) -> EnvironmentsCompareResponse:
    from ducta.setting.environment_compare import compare_environments

    svc.get_project(project_id)
    result = await asyncio.to_thread(compare_environments, svc.store(project_id).root)
    return EnvironmentsCompareResponse.model_validate(result)


# ── Code index ────────────────────────────────────────────


class CodeFunction(BaseModel):
    name: str
    line: int
    params: List[str] = Field(default_factory=list)
    docstring: Optional[str] = None


class CodeIndexNode(BaseModel):
    node: str
    pipeline: Optional[str] = None
    module: str
    function: str
    file: str = Field(description="Relative to the project root")
    workspace_file: str = Field(description="Relative to the workspace root (/workspace/files)")
    line: Optional[int] = Field(default=None, description="Line of `def function`; null if absent")
    exists: bool
    params: List[str] = Field(default_factory=list)
    inputs: Dict[str, str] = Field(default_factory=dict)


class CodeIndexResponse(BaseModel):
    nodes: List[CodeIndexNode]
    files: Dict[str, List[CodeFunction]] = Field(
        description="Top-level functions of every file a node runs, by project-relative path"
    )


@router.get(
    "/{project_id}/code-index",
    response_model=CodeIndexResponse,
    summary="Which function each node runs, and where",
    description=(
        "For every node that runs project code: its module, function, file and the line of "
        "its `def`; and every top-level function of those files. Read from the syntax tree — "
        "no project module is imported."
    ),
    dependencies=[Depends(require_permission("node.read"))],
)
async def get_code_index(project_id: str, svc: ProjectServiceDep) -> CodeIndexResponse:
    from ducta.api.services.code_index import build_code_index

    svc.get_project(project_id)
    index = await asyncio.to_thread(build_code_index, svc.store(project_id), svc.workspace_path)
    return CodeIndexResponse.model_validate(index)


# ── Deep preflight ────────────────────────────────────────


class PreflightResponse(BaseModel):
    """Structured result of the deep preflight (same checks as `ducta config validate`)."""

    ok: bool = Field(description="True when no blocking errors were found")
    pipeline: str
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    problems: list[ProblemModel] = Field(
        default_factory=list,
        description="errors then warnings, each split into file, line, node, dataset and fix",
    )


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
    problems = problem_models(result.get("errors", []), result.get("warnings", []), "preflight")
    return PreflightResponse(pipeline=name, problems=problems, **result)


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

    from ducta.api.services.governance import check_can_run

    check_can_run(current_user, body.env, svc.store(project_id).root)
    if body.debug:
        _check_debug_allowed()
    node_names = await asyncio.to_thread(_scope_nodes, svc, manager, project_id, name, body)
    if body.sample_rows and body.node_name and not node_names:
        # A sample run of one node is that node alone, reading its inputs as
        # materialized — never a re-run of the pipelines upstream of it.
        node_names = [body.node_name]
    return exec_manager.execute(
        source_path=exec_source,
        pipeline_name=name,
        env=body.env,
        node_name=body.node_name,
        node_names=node_names,
        sample_rows=body.sample_rows,
        debug=body.debug,
        pause_after=body.pause_after,
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


def _scope_nodes(
    svc: ProjectService, manager: Any, project_id: str, name: str, body: ExecuteRequest
) -> Optional[List[str]]:
    """The nodes a scoped run covers; None for the whole pipeline (or one `node_name`)."""
    from ducta.api.services.run_scope import resolve_scope

    if not body.scope and not body.nodes:
        return None
    store = svc.store(project_id)
    members = list((store.pipelines().get(name) or {}).get("nodes") or [])
    not_fresh = None
    if body.scope == "stale":
        from ducta.api.services.run_certificates import latest_successful
        from ducta.api.services.staleness import node_freshness

        last_ok = latest_successful(manager.for_project(project_id).root, body.env)
        not_fresh = [n for n, f in node_freshness(store, last_ok).items() if f.state != "fresh"]
    with http_error_on(400):
        return resolve_scope(body.scope, body.nodes, members, store.nodes(), not_fresh)


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
