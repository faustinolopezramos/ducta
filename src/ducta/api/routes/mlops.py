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

from functools import cached_property
from pathlib import Path
from typing import Annotated, Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.concurrency import run_in_threadpool
from loguru import logger
from pydantic import BaseModel

from ducta.api.dependencies import SourcePathDep, require_permission
from ducta.api.exceptions import ValidationError
from ducta.api.utils.git_utils import safe_path
from ducta.mlrun.config import DEFAULT_REGISTRY_PATH, DEFAULT_TRACKING_PATH
from ducta.mlrun.experiment_tracking import ExperimentTracker, RunStatus
from ducta.mlrun.model_registry import ModelRegistry, ModelStage, PromotionPolicy
from ducta.mlrun.storage import LocalStorageBackend

router = APIRouter(prefix="/mlops", tags=["MLOps"])

_PROJECT_QUERY = Query(
    default=None,
    description="Project id to browse, within the connected workspace, instead of "
    "whichever project the connected source itself belongs to.",
)


# ── Pydantic schemas ─────────────────────────────────────────────────────────


class PromoteModelRequest(BaseModel):
    version: int
    stage: Literal["staging", "production", "archived"]
    force: bool = False


class GcRequest(BaseModel):
    dry_run: bool = True


class CloseRunRequest(BaseModel):
    status: Literal["COMPLETED", "FAILED"] = "FAILED"


# ── Helpers ──────────────────────────────────────────────────────────────────


def _resolve_workspace_context(
    source_path: Path, env: Optional[str], project: Optional[str] = None
) -> Optional[Any]:
    """Build a real project ``Context`` for this workspace/env, the same way
    ``api/execution/runner.py`` does when actually running a pipeline.
    """
    if not env:
        return None
    try:
        from ducta.api.execution.runner import normalize_execution_context_paths
        from ducta.api.workspace.manager import WorkspaceManager

        manager = WorkspaceManager(source_path)
        if project:
            manager = manager.for_project(project)
        context = manager.load_context(env)
        normalize_execution_context_paths(context, manager.root)
        return context
    except Exception as exc:
        logger.debug("Context-based mlops resolution failed for env='{}': {}", env, exc)
        return None


def _resolve_global_config(
    source_path: Path, env: Optional[str], project: Optional[str] = None
) -> Dict[str, Any]:
    """Best-effort ``global_config`` dict for this workspace, preferring a
    real ``Context`` (see ``_resolve_workspace_context``) over compiling the
    project's files directly. Shared by ``_resolve_mlops_storage`` and the promotion
    policy lookup in ``promote_model`` so both agree on the same settings —
    previously ``promote_model`` resolved its policy via
    ``console.mlops_commands._resolve_promotion_policy()``, which discovers a
    project from the CLI process's current working directory: meaningless
    inside a long-running API server juggling requests for many workspaces,
    so the promotion policy was silently never applied here.
    """
    context = _resolve_workspace_context(source_path, env, project)
    if context is not None:
        gs = getattr(context, "global_config", {})
        if isinstance(gs, dict):
            return gs

    project_root = source_path
    if project:
        from ducta.api.workspace.manager import WorkspaceManager

        project_root = WorkspaceManager(source_path).for_project(project).root
    try:
        from ducta.setting.project_loader import (
            compile_project,
            find_project_root,
            validate_project,
        )

        root = find_project_root(project_root)
        if root is not None:
            return dict(compile_project(validate_project(root, env))["global_config"])
    except Exception as exc:
        logger.debug("Could not read global config: {}", exc)

    return {}


def _resolve_mlops_storage(
    source_path: Path,
    override: Optional[str],
    env: Optional[str] = None,
    pipeline_name: Optional[str] = None,
    global_config: Optional[Dict[str, Any]] = None,
    project: Optional[str] = None,
) -> str:
    """Resolve mlops storage path from workspace or explicit override.

    An explicit *override* comes straight from the request, so it is confined
    to the workspace: these endpoints delete runs, model versions and GC'd
    artifacts under it.
    """
    if override:
        try:
            return str(safe_path(source_path, override))
        except ValueError as exc:
            raise ValidationError(str(exc), detail={"storage_path": override}) from exc

    context = _resolve_workspace_context(source_path, env, project)
    if context is not None:
        from ducta.mlrun.config import StorageBackendFactory

        resolved = StorageBackendFactory._resolve_mlops_path(context, pipeline_name=pipeline_name)
        if resolved:
            return resolved

    gs = (
        global_config
        if global_config is not None
        else _resolve_global_config(source_path, env, project)
    )
    mlops_cfg = gs.get("mlops") or {}
    path = mlops_cfg.get("storage_path") or gs.get("mlops_storage_path")
    if path:
        return path

    # Fall back to a conventional location relative to the workspace
    return str(source_path / "mlops_data")


class MLOpsScope:
    """Where an mlops request reads and writes: the workspace, optionally
    narrowed by env / pipeline / project, or an explicit storage override
    confined to the workspace. Shared by every endpoint below."""

    def __init__(
        self,
        source_path: SourcePathDep,
        storage_path: Optional[str] = Query(
            None, description="Override MLOps storage path (must be inside the workspace)"
        ),
        env: Optional[str] = Query(
            None, description="Environment to resolve the storage path from"
        ),
        pipeline: Optional[str] = Query(
            None, description="Pipeline name (schema.pipeline) to scope to"
        ),
        project: Optional[str] = _PROJECT_QUERY,
    ) -> None:
        self._source_path = source_path
        self._env = env
        self._project = project
        self.storage = _resolve_mlops_storage(
            source_path, storage_path, env, pipeline, project=project
        )

    @cached_property
    def global_config(self) -> Dict[str, Any]:
        return _resolve_global_config(self._source_path, self._env, self._project)

    def tracker(self) -> ExperimentTracker:
        storage = LocalStorageBackend(base_path=self.storage)
        return ExperimentTracker(storage=storage, tracking_path=DEFAULT_TRACKING_PATH)

    def registry(self) -> ModelRegistry:
        storage = LocalStorageBackend(base_path=self.storage)
        return ModelRegistry(storage=storage, registry_path=DEFAULT_REGISTRY_PATH)


MLOpsScopeDep = Annotated[MLOpsScope, Depends()]


# ── Experiment endpoints ─────────────────────────────────────────────────────


@router.get("/experiments", dependencies=[Depends(require_permission("execution.read"))])
async def list_experiments(scope: MLOpsScopeDep) -> List[Dict[str, Any]]:
    """List all MLOps experiments (most recent first)."""
    return await run_in_threadpool(lambda: scope.tracker().list_experiments())


@router.get(
    "/experiments/{experiment_id}",
    dependencies=[Depends(require_permission("execution.read"))],
)
async def get_experiment(experiment_id: str, scope: MLOpsScopeDep) -> Dict[str, Any]:
    """Get an experiment and its runs."""

    def _run() -> Dict[str, Any]:
        tracker = scope.tracker()
        exp = tracker._get_experiment(experiment_id)
        return {
            "experiment_id": exp.experiment_id,
            "name": exp.name,
            "created_at": exp.created_at,
            "artifact_location": exp.artifact_location,
            "runs": tracker.list_runs(experiment_id),
        }

    return await run_in_threadpool(_run)


@router.post(
    "/experiments/{experiment_id}/runs/{run_id}/close",
    dependencies=[Depends(require_permission("execution.write"))],
)
async def close_run(
    experiment_id: str, run_id: str, body: CloseRunRequest, scope: MLOpsScopeDep
) -> Dict[str, Any]:
    """Force a run stuck in RUNNING to a terminal status."""

    def _run() -> Dict[str, Any]:
        run = scope.tracker().close_run(run_id, status=RunStatus(body.status))
        return {"run_id": run.run_id, "status": run.status.value}

    return await run_in_threadpool(_run)


@router.delete(
    "/experiments/{experiment_id}/runs/{run_id}",
    status_code=204,
    dependencies=[Depends(require_permission("execution.write"))],
)
async def delete_run(experiment_id: str, run_id: str, scope: MLOpsScopeDep) -> None:
    await run_in_threadpool(lambda: scope.tracker().delete_run(run_id))


# ── Model endpoints ──────────────────────────────────────────────────────────


@router.get("/models", dependencies=[Depends(require_permission("execution.read"))])
async def list_models(scope: MLOpsScopeDep) -> List[Dict[str, Any]]:
    """List all registered models (latest version per model)."""
    return await run_in_threadpool(lambda: scope.registry().list_models())


@router.get("/models/{name}", dependencies=[Depends(require_permission("execution.read"))])
async def get_model_versions(name: str, scope: MLOpsScopeDep) -> List[Dict[str, Any]]:
    """Get all versions of a model."""
    return await run_in_threadpool(lambda: scope.registry().list_model_versions(name))


@router.post(
    "/models/{name}/promote",
    dependencies=[Depends(require_permission("execution.write"))],
)
async def promote_model(
    name: str, body: PromoteModelRequest, scope: MLOpsScopeDep
) -> Dict[str, Any]:
    """Promote a model version to a new stage."""
    target_stage = ModelStage(body.stage.capitalize())

    policy_cfg = (scope.global_config.get("mlops") or {}).get("promotion_policy")
    policy: Optional[PromotionPolicy] = None
    if isinstance(policy_cfg, dict) and policy_cfg.get("metric"):
        try:
            policy = PromotionPolicy.from_dict(policy_cfg)
        except Exception as exc:
            logger.warning("Invalid mlops.promotion_policy ignored: {}", exc)

    def _run() -> Dict[str, Any]:
        scope.registry().promote_model(
            name, body.version, target_stage, policy=policy, force=body.force
        )
        return {
            "name": name,
            "version": body.version,
            "stage": target_stage.value,
            "promoted": True,
        }

    return await run_in_threadpool(_run)


@router.delete(
    "/models/{name}/versions/{version}",
    status_code=204,
    dependencies=[Depends(require_permission("execution.write"))],
)
async def delete_model_version(name: str, version: int, scope: MLOpsScopeDep) -> None:
    """Delete a specific model version and its artifact."""
    await run_in_threadpool(lambda: scope.registry().delete_model_version(name, version))


@router.post("/gc", dependencies=[Depends(require_permission("execution.write"))])
async def run_gc(body: GcRequest, scope: MLOpsScopeDep) -> Dict[str, Any]:
    """Garbage-collect old model versions."""

    def _run() -> Dict[str, Any]:
        from ducta.mlrun.config import MLOpsConfig
        from ducta.mlrun.gc import ModelGarbageCollector

        gc_cfg = (scope.global_config.get("mlops") or {}).get("gc")
        mlops_config = MLOpsConfig.from_env()
        if isinstance(gc_cfg, dict):
            mlops_config = mlops_config.with_overrides(gc_cfg)
        stats = ModelGarbageCollector(
            storage_path=scope.storage,
            max_versions_per_model=mlops_config.max_versions_per_model,
            model_retention_days=mlops_config.model_retention_days,
        ).run(dry_run=body.dry_run)
        return {
            "dry_run": body.dry_run,
            "models_processed": stats.get("models_processed", 0),
            "versions_removed": stats.get("versions_removed", 0),
            "bytes_freed": stats.get("bytes_freed", 0),
            "storage_path": scope.storage,
        }

    return await run_in_threadpool(_run)
