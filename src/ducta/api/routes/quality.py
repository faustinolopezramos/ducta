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

import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from fastapi import APIRouter, Depends, HTTPException, Query

from ducta.api.dependencies import WorkspaceManagerDep, require_permission
from ducta.api.exceptions import http_error_on
from ducta.api.models.quality import (
    QualityCheckInfo,
    QualityDatasetRef,
    QualityDatasetSummary,
    RunChecksRequest,
    ValidateConfigRequest,
    ValidateConfigResponse,
)
from ducta.api.utils.git_utils import safe_path
from ducta.check.service import QualityService

router = APIRouter(prefix="/quality", tags=["Quality"])

_ENV_QUERY = Query(
    default=None,
    description="Environment to resolve the project's real quality.output storage "
    "from (base, dev, sandbox, prod, ...), instead of the workspace's "
    "standalone <root>/.quality convention. Reads reports a real pipeline "
    "run persisted.",
)

_PIPELINE_QUERY = Query(
    default=None,
    description="Pipeline that owns the dataset's reports. Required (together with "
    "`env`) to reach a real pipeline run's reports; omitted defaults to the "
    "ad-hoc/manual 'Run checks' bucket for single-dataset lookups, or "
    "aggregates across every pipeline for the list/summary endpoints.",
)

_PROJECT_QUERY = Query(
    default=None,
    description="Project id to browse, within the connected workspace, instead of "
    "whichever project the connected source itself belongs to.",
)


def _resolve_storage_from_env(manager: WorkspaceManagerDep, env: Optional[str]) -> Optional[Any]:
    """Mirror of the CLI's ``_resolve_storage_from_env`` (cli/commands/quality_cmds.py).

    Returns ``None`` when *env* isn't supplied — callers fall back to the
    standalone ``FileStorageBackend``/``workspace`` convention unchanged.
    """
    if not env:
        return None

    from ducta.api.execution.runner import normalize_execution_context_paths
    from ducta.check.engine import ValidationPhaseRunner

    context = manager.load_context(env)
    normalize_execution_context_paths(context, manager.root)
    return ValidationPhaseRunner(context=context).storage


def _split_qualified(entry: str, pipeline_name: Optional[str]) -> QualityDatasetRef:
    """Turn one ``storage.list_datasets()`` entry into a structured ref."""
    if pipeline_name is not None:
        return QualityDatasetRef(pipeline_name=pipeline_name, dataset=entry)
    pl, _, ds = entry.partition("/")
    return QualityDatasetRef(pipeline_name=pl, dataset=ds)


@router.get(
    "/checks",
    response_model=List[QualityCheckInfo],
    dependencies=[Depends(require_permission("quality.read"))],
    summary="List all registered quality checks (built-in and custom)",
)
async def list_checks() -> List[QualityCheckInfo]:
    return [QualityCheckInfo(**c) for c in QualityService.list_checks()]


@router.get(
    "/datasets",
    response_model=List[QualityDatasetRef],
    dependencies=[Depends(require_permission("quality.read"))],
    summary="List datasets that have at least one stored quality report",
)
async def list_datasets(
    manager: WorkspaceManagerDep,
    env: Optional[str] = _ENV_QUERY,
    pipeline_name: Optional[str] = _PIPELINE_QUERY,
    project: Optional[str] = _PROJECT_QUERY,
) -> List[QualityDatasetRef]:
    manager = manager.for_project(project)
    storage = _resolve_storage_from_env(manager, env)
    entries = QualityService.list_datasets(
        workspace=str(manager.root), storage=storage, pipeline_name=pipeline_name
    )
    return [_split_qualified(entry, pipeline_name) for entry in entries]


@router.get(
    "/summary",
    response_model=List[QualityDatasetSummary],
    dependencies=[Depends(require_permission("quality.read"))],
    summary="Per-dataset quality overview: latest report status and score trend",
)
async def get_summary(
    manager: WorkspaceManagerDep,
    trend_n: int = Query(default=12, ge=1, le=100, description="Trend points per dataset"),
    env: Optional[str] = _ENV_QUERY,
    pipeline_name: Optional[str] = _PIPELINE_QUERY,
    project: Optional[str] = _PROJECT_QUERY,
) -> List[QualityDatasetSummary]:
    manager = manager.for_project(project)
    storage = _resolve_storage_from_env(manager, env)
    summaries = []
    for item in QualityService.get_summary(
        workspace=str(manager.root), trend_n=trend_n, storage=storage, pipeline_name=pipeline_name
    ):
        ref = _split_qualified(item["dataset"], pipeline_name)
        summaries.append(
            QualityDatasetSummary(
                **{**item, "pipeline_name": ref.pipeline_name, "dataset": ref.dataset}
            )
        )
    return summaries


@router.post(
    "/run",
    dependencies=[Depends(require_permission("quality.run"))],
    summary="Run quality checks on a workspace data file",
)
async def run_checks(body: RunChecksRequest, manager: WorkspaceManagerDep) -> Dict[str, Any]:
    if not body.config_path and not body.checks:
        raise HTTPException(status_code=422, detail="Provide either 'config_path' or 'checks'")

    with http_error_on(400):
        input_abs = safe_path(manager.root, body.input_path)
    if not input_abs.is_file():
        raise HTTPException(status_code=404, detail=f"Input file not found: {body.input_path}")

    tmp_config: Optional[Path] = None
    try:
        if body.config_path:
            with http_error_on(400):
                config_abs = safe_path(manager.root, body.config_path)
            if not config_abs.is_file():
                raise HTTPException(
                    status_code=404, detail=f"Config file not found: {body.config_path}"
                )
            config_path = str(config_abs)
        else:
            # Inline checks — materialise to a temp file for QualityService.
            fd = tempfile.NamedTemporaryFile(
                mode="w", suffix=".yaml", delete=False, encoding="utf-8"
            )
            yaml.safe_dump({"checks": body.checks}, fd)
            fd.close()
            tmp_config = Path(fd.name)
            config_path = str(tmp_config)

        with http_error_on(422):
            return QualityService.run_checks(
                input_path=str(input_abs),
                format=body.format,
                config_path=config_path,
                fail_fast=body.fail_fast,
                workspace=str(manager.root),
                source_config_path=body.config_path,
                source_checks=body.checks,
            )
    finally:
        if tmp_config is not None:
            tmp_config.unlink(missing_ok=True)


@router.get(
    "/reports/{dataset}",
    dependencies=[Depends(require_permission("quality.read"))],
    summary="Show stored quality reports for a dataset",
)
async def get_report(
    dataset: str,
    manager: WorkspaceManagerDep,
    run_id: Optional[str] = Query(default=None, description="Specific run ID (default: latest)"),
    all: bool = Query(default=False, description="List all stored run IDs instead of a report"),
    env: Optional[str] = _ENV_QUERY,
    pipeline_name: Optional[str] = _PIPELINE_QUERY,
    project: Optional[str] = _PROJECT_QUERY,
) -> Dict[str, Any]:
    try:
        manager = manager.for_project(project)
        storage = _resolve_storage_from_env(manager, env)
        return QualityService.get_report(
            dataset=dataset,
            workspace=str(manager.root),
            run_id=run_id,
            all_reports=all,
            storage=storage,
            pipeline_name=pipeline_name,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.delete(
    "/reports/{dataset}/{run_id}",
    status_code=204,
    dependencies=[Depends(require_permission("quality.run"))],
    summary="Delete a stored quality report",
)
async def delete_report(
    dataset: str,
    run_id: str,
    manager: WorkspaceManagerDep,
    env: Optional[str] = _ENV_QUERY,
    pipeline_name: Optional[str] = _PIPELINE_QUERY,
    project: Optional[str] = _PROJECT_QUERY,
) -> None:
    try:
        manager = manager.for_project(project)
        storage = _resolve_storage_from_env(manager, env)
        QualityService.delete_report(
            dataset=dataset,
            run_id=run_id,
            workspace=str(manager.root),
            storage=storage,
            pipeline_name=pipeline_name,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get(
    "/trend/{dataset}",
    dependencies=[Depends(require_permission("quality.read"))],
    summary="Show the quality score trend for a dataset",
)
async def get_trend(
    dataset: str,
    manager: WorkspaceManagerDep,
    last_n: int = Query(default=20, ge=1, le=500, description="Number of recent scores"),
    env: Optional[str] = _ENV_QUERY,
    pipeline_name: Optional[str] = _PIPELINE_QUERY,
    project: Optional[str] = _PROJECT_QUERY,
) -> Dict[str, Any]:
    manager = manager.for_project(project)
    storage = _resolve_storage_from_env(manager, env)
    return QualityService.get_trend(
        dataset=dataset,
        workspace=str(manager.root),
        last_n=last_n,
        storage=storage,
        pipeline_name=pipeline_name,
    )


@router.get(
    "/score/{run_id}",
    dependencies=[Depends(require_permission("quality.read"))],
    summary="Show the composite pipeline quality score for a run",
)
async def get_score(
    run_id: str,
    manager: WorkspaceManagerDep,
    env: Optional[str] = _ENV_QUERY,
    pipeline_name: Optional[str] = _PIPELINE_QUERY,
    project: Optional[str] = _PROJECT_QUERY,
) -> Dict[str, Any]:
    try:
        manager = manager.for_project(project)
        storage = _resolve_storage_from_env(manager, env)
        return QualityService.get_score(
            run_id=run_id, workspace=str(manager.root), storage=storage, pipeline_name=pipeline_name
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post(
    "/validate-config",
    response_model=ValidateConfigResponse,
    dependencies=[Depends(require_permission("quality.read"))],
    summary="Validate a node's quality config without executing",
)
async def validate_config(
    body: ValidateConfigRequest, manager: WorkspaceManagerDep
) -> ValidateConfigResponse:
    from ducta.api.repositories.v2_store import workspace_stores
    from ducta.setting.project_loader import ProjectConfigError

    try:
        store = next(
            (s for s in workspace_stores(manager.root) if body.node_name in s.nodes()), None
        )
        if store is None:
            raise HTTPException(status_code=404, detail=f"Node '{body.node_name}' not found")
        result = QualityService.validate_node_config(
            node_name=body.node_name, project_root=store.root, env=body.env, load_extensions=False
        )
    except ProjectConfigError as exc:
        # The project itself does not validate: those problems are the answer.
        result = {"valid": False, "errors": list(exc.problems), "warnings": []}
    return ValidateConfigResponse(**result)
