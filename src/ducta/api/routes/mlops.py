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
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from loguru import logger
from pydantic import BaseModel

from ducta.api.dependencies import SourcePathDep, require_permission
from ducta.mlrun.config import DEFAULT_REGISTRY_PATH, DEFAULT_TRACKING_PATH
from ducta.mlrun.exceptions import ExperimentNotFoundError, ModelNotFoundError, RunNotFoundError
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
    real ``Context`` (see ``_resolve_workspace_context``) over the flat-file
    heuristic below. Shared by ``_resolve_mlops_storage`` and the promotion
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
    for candidate in ("global_config.toml", "global_config.yaml", "global_config.yml"):
        cfg_file = project_root / candidate
        if cfg_file.is_file():
            try:
                from ducta.setting.loaders import ConfigLoaderFactory

                data = ConfigLoaderFactory(allow_python=False).load_config(str(cfg_file))
                if isinstance(data, dict):
                    return data
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
    """Resolve mlops storage path from workspace or explicit override."""
    if override:
        return override

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


def _make_tracker(storage_path: str) -> ExperimentTracker:
    storage = LocalStorageBackend(base_path=storage_path)
    return ExperimentTracker(storage=storage, tracking_path=DEFAULT_TRACKING_PATH)


def _make_registry(storage_path: str) -> ModelRegistry:
    storage = LocalStorageBackend(base_path=storage_path)
    return ModelRegistry(storage=storage, registry_path=DEFAULT_REGISTRY_PATH)


# ── Experiment endpoints ─────────────────────────────────────────────────────


@router.get(
    "/experiments",
    dependencies=[Depends(require_permission("execution.read"))],
)
async def list_experiments(
    source_path: SourcePathDep,
    storage_path: Optional[str] = Query(None, description="Override MLOps storage path"),
    env: Optional[str] = Query(None, description="Environment to resolve the storage path from"),
    pipeline: Optional[str] = Query(
        None, description="Pipeline name (schema.pipeline) to scope to"
    ),
    project: Optional[str] = _PROJECT_QUERY,
) -> List[Dict[str, Any]]:
    """List all MLOps experiments (most recent first)."""
    resolved = _resolve_mlops_storage(source_path, storage_path, env, pipeline, project=project)

    def _run():
        return _make_tracker(resolved).list_experiments()

    try:
        return await run_in_threadpool(_run)
    except Exception as exc:
        logger.error("Failed to list experiments: {}", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get(
    "/experiments/{experiment_id}",
    dependencies=[Depends(require_permission("execution.read"))],
)
async def get_experiment(
    experiment_id: str,
    source_path: SourcePathDep,
    storage_path: Optional[str] = Query(None),
    env: Optional[str] = Query(None, description="Environment to resolve the storage path from"),
    pipeline: Optional[str] = Query(
        None, description="Pipeline name (schema.pipeline) to scope to"
    ),
    project: Optional[str] = _PROJECT_QUERY,
) -> Dict[str, Any]:
    """Get an experiment and its runs."""
    resolved = _resolve_mlops_storage(source_path, storage_path, env, pipeline, project=project)

    def _run():
        tracker = _make_tracker(resolved)
        # Get experiment metadata
        exp = tracker._get_experiment(experiment_id)
        runs = tracker.list_runs(experiment_id)
        return {
            "experiment_id": exp.experiment_id,
            "name": exp.name,
            "created_at": exp.created_at,
            "artifact_location": exp.artifact_location,
            "runs": runs,
        }

    try:
        return await run_in_threadpool(_run)
    except ExperimentNotFoundError:
        raise HTTPException(status_code=404, detail=f"Experiment '{experiment_id}' not found")
    except Exception as exc:
        logger.error("Failed to get experiment {}: {}", experiment_id, exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post(
    "/experiments/{experiment_id}/runs/{run_id}/close",
    dependencies=[Depends(require_permission("execution.write"))],
)
async def close_run(
    experiment_id: str,
    run_id: str,
    body: CloseRunRequest,
    source_path: SourcePathDep,
    storage_path: Optional[str] = Query(None),
    env: Optional[str] = Query(None, description="Environment to resolve the storage path from"),
    pipeline: Optional[str] = Query(
        None, description="Pipeline name (schema.pipeline) to scope to"
    ),
    project: Optional[str] = _PROJECT_QUERY,
) -> Dict[str, Any]:
    """Force a run stuck in RUNNING to a terminal status."""
    resolved = _resolve_mlops_storage(source_path, storage_path, env, pipeline, project=project)

    def _run():
        tracker = _make_tracker(resolved)
        run = tracker.close_run(run_id, status=RunStatus(body.status))
        return {"run_id": run.run_id, "status": run.status.value}

    try:
        return await run_in_threadpool(_run)
    except RunNotFoundError:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    except Exception as exc:
        logger.error("Failed to close run {}: {}", run_id, exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete(
    "/experiments/{experiment_id}/runs/{run_id}",
    status_code=204,
    dependencies=[Depends(require_permission("execution.write"))],
)
async def delete_run(
    experiment_id: str,
    run_id: str,
    source_path: SourcePathDep,
    storage_path: Optional[str] = Query(None),
    env: Optional[str] = Query(None, description="Environment to resolve the storage path from"),
    pipeline: Optional[str] = Query(
        None, description="Pipeline name (schema.pipeline) to scope to"
    ),
    project: Optional[str] = _PROJECT_QUERY,
) -> None:
    resolved = _resolve_mlops_storage(source_path, storage_path, env, pipeline, project=project)

    def _run():
        _make_tracker(resolved).delete_run(run_id)

    try:
        await run_in_threadpool(_run)
    except RunNotFoundError:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    except Exception as exc:
        logger.error("Failed to delete run {}: {}", run_id, exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── Model endpoints ──────────────────────────────────────────────────────────


@router.get(
    "/models",
    dependencies=[Depends(require_permission("execution.read"))],
)
async def list_models(
    source_path: SourcePathDep,
    storage_path: Optional[str] = Query(None),
    env: Optional[str] = Query(None, description="Environment to resolve the storage path from"),
    pipeline: Optional[str] = Query(
        None, description="Pipeline name (schema.pipeline) to scope to"
    ),
    project: Optional[str] = _PROJECT_QUERY,
) -> List[Dict[str, Any]]:
    """List all registered models (latest version per model)."""
    resolved = _resolve_mlops_storage(source_path, storage_path, env, pipeline, project=project)

    def _run():
        return _make_registry(resolved).list_models()

    try:
        return await run_in_threadpool(_run)
    except Exception as exc:
        logger.error("Failed to list models: {}", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get(
    "/models/{name}",
    dependencies=[Depends(require_permission("execution.read"))],
)
async def get_model_versions(
    name: str,
    source_path: SourcePathDep,
    storage_path: Optional[str] = Query(None),
    env: Optional[str] = Query(None, description="Environment to resolve the storage path from"),
    pipeline: Optional[str] = Query(
        None, description="Pipeline name (schema.pipeline) to scope to"
    ),
    project: Optional[str] = _PROJECT_QUERY,
) -> List[Dict[str, Any]]:
    """Get all versions of a model."""
    resolved = _resolve_mlops_storage(source_path, storage_path, env, pipeline, project=project)

    def _run():
        return _make_registry(resolved).list_model_versions(name)

    try:
        return await run_in_threadpool(_run)
    except ModelNotFoundError:
        raise HTTPException(status_code=404, detail=f"Model '{name}' not found")
    except Exception as exc:
        logger.error("Failed to get model versions for {}: {}", name, exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post(
    "/models/{name}/promote",
    dependencies=[Depends(require_permission("execution.write"))],
)
async def promote_model(
    name: str,
    body: PromoteModelRequest,
    source_path: SourcePathDep,
    storage_path: Optional[str] = Query(None),
    env: Optional[str] = Query(None, description="Environment to resolve the storage path from"),
    pipeline: Optional[str] = Query(
        None, description="Pipeline name (schema.pipeline) to scope to"
    ),
    project: Optional[str] = _PROJECT_QUERY,
) -> Dict[str, Any]:
    """Promote a model version to a new stage."""
    gs = _resolve_global_config(source_path, env, project)
    resolved = _resolve_mlops_storage(
        source_path, storage_path, env, pipeline, global_config=gs, project=project
    )

    try:
        target_stage = ModelStage(body.stage.capitalize())
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid stage '{body.stage}'. Valid values: staging, production, archived",
        )

    policy_cfg = (gs.get("mlops") or {}).get("promotion_policy")
    policy: Optional[PromotionPolicy] = None
    if isinstance(policy_cfg, dict) and policy_cfg.get("metric"):
        try:
            policy = PromotionPolicy.from_dict(policy_cfg)
        except Exception as exc:
            logger.warning("Invalid mlops.promotion_policy ignored: {}", exc)

    def _run():
        registry = _make_registry(resolved)
        registry.promote_model(name, body.version, target_stage, policy=policy, force=body.force)
        return {
            "name": name,
            "version": body.version,
            "stage": target_stage.value,
            "promoted": True,
        }

    try:
        return await run_in_threadpool(_run)
    except ModelNotFoundError:
        raise HTTPException(status_code=404, detail=f"Model '{name}' v{body.version} not found")
    except Exception as exc:
        logger.error("Failed to promote model {} v{}: {}", name, body.version, exc)
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete(
    "/models/{name}/versions/{version}",
    status_code=204,
    dependencies=[Depends(require_permission("execution.write"))],
)
async def delete_model_version(
    name: str,
    version: int,
    source_path: SourcePathDep,
    storage_path: Optional[str] = Query(None),
    env: Optional[str] = Query(None, description="Environment to resolve the storage path from"),
    pipeline: Optional[str] = Query(
        None, description="Pipeline name (schema.pipeline) to scope to"
    ),
    project: Optional[str] = _PROJECT_QUERY,
) -> None:
    """Delete a specific model version and its artifact."""
    resolved = _resolve_mlops_storage(source_path, storage_path, env, pipeline, project=project)

    def _run():
        _make_registry(resolved).delete_model_version(name, version)

    try:
        await run_in_threadpool(_run)
    except ModelNotFoundError:
        raise HTTPException(status_code=404, detail=f"Model '{name}' v{version} not found")
    except Exception as exc:
        logger.error("Failed to delete model {} v{}: {}", name, version, exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post(
    "/gc",
    dependencies=[Depends(require_permission("execution.write"))],
)
async def run_gc(
    body: GcRequest,
    source_path: SourcePathDep,
    storage_path: Optional[str] = Query(None),
    env: Optional[str] = Query(None, description="Environment to resolve the storage path from"),
    pipeline: Optional[str] = Query(
        None, description="Pipeline name (schema.pipeline) to scope to"
    ),
    project: Optional[str] = _PROJECT_QUERY,
) -> Dict[str, Any]:
    """Garbage-collect old model versions."""
    gs = _resolve_global_config(source_path, env, project)
    resolved = _resolve_mlops_storage(
        source_path, storage_path, env, pipeline, global_config=gs, project=project
    )

    def _run():
        from ducta.mlrun.config import MLOpsConfig
        from ducta.mlrun.gc import ModelGarbageCollector

        gc_cfg = (gs.get("mlops") or {}).get("gc")
        mlops_config = MLOpsConfig.from_env()
        if isinstance(gc_cfg, dict):
            mlops_config = mlops_config.with_overrides(gc_cfg)
        gc = ModelGarbageCollector(
            storage_path=resolved,
            max_versions_per_model=mlops_config.max_versions_per_model,
            model_retention_days=mlops_config.model_retention_days,
        )
        stats = gc.run(dry_run=body.dry_run)
        return {
            "dry_run": body.dry_run,
            "models_processed": stats.get("models_processed", 0),
            "versions_removed": stats.get("versions_removed", 0),
            "bytes_freed": stats.get("bytes_freed", 0),
            "storage_path": resolved,
        }

    try:
        return await run_in_threadpool(_run)
    except Exception as exc:
        logger.error("GC failed: {}", exc)
        raise HTTPException(status_code=500, detail=str(exc))
