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
from typing import Annotated, Any, Callable, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.concurrency import run_in_threadpool
from loguru import logger
from pydantic import BaseModel

from ducta.api.dependencies import SourcePathDep, require_permission
from ducta.api.exceptions import ValidationError
from ducta.api.models.auth import User
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
    #: Recorded in the registry's audit log; required with ``force``.
    reason: Optional[str] = None


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

    docs = _compiled_project(source_path, env, project)
    return dict(docs.get("global_config") or {})


def _compiled_project(
    source_path: Path, env: Optional[str], project: Optional[str] = None
) -> Dict[str, Any]:
    """The project's compiled engine documents, or ``{}`` when it cannot be read."""
    project_root = source_path
    if project:
        from ducta.api.workspace.manager import WorkspaceManager

        project_root = WorkspaceManager(source_path).for_project(project).root
    try:
        from ducta.setting.project.loader import (
            compile_project,
            find_project_root,
            validate_project,
        )

        root = find_project_root(project_root)
        if root is not None:
            return dict(compile_project(validate_project(root, env)))
    except Exception as exc:
        logger.debug("Could not read the project configuration: {}", exc)
    return {}


def serving_references(docs: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """registered model name → the nodes that serve it (``model:`` on a node).

    Read from configuration only: which *version* a stage names is decided when a
    run starts. MLflow models are left out — they are not in this registry.
    """
    pipeline_of = {
        node: pname
        for pname, pcfg in (docs.get("pipelines_config") or {}).items()
        for node in (pcfg.get("nodes") or [])
    }
    out: Dict[str, List[Dict[str, Any]]] = {}
    for node, cfg in (docs.get("nodes_config") or {}).items():
        ref = (cfg or {}).get("model")
        if not isinstance(ref, dict) or ref.get("source", "ducta") != "ducta":
            continue
        out.setdefault(str(ref.get("name")), []).append(
            {
                "pipeline": pipeline_of.get(node),
                "node": node,
                "stage": ref.get("stage"),
                "version": ref.get("version"),
                "streaming": cfg.get("type") == "streaming",
            }
        )
    return out


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
        return str(path)

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
        self.pipeline = pipeline
        self.storage = _resolve_mlops_storage(
            source_path, storage_path, env, pipeline, project=project
        )

    @cached_property
    def global_config(self) -> Dict[str, Any]:
        return _resolve_global_config(self._source_path, self._env, self._project)

    def certificate_dir(self) -> Optional[str]:
        """The run-certificate directory of this scope (the GC reports the runs it
        makes unreproducible), or None when it cannot be resolved."""
        try:
            from pathlib import Path

            from ducta.core.settings import CoreSettings

            runs = Path(CoreSettings.from_context(self.global_config).run_certificate_dir)
            if not runs.is_absolute() and self._source_path:
                runs = Path(str(self._source_path)) / runs
            return str(runs)
        except Exception:  # noqa: BLE001 — the GC still runs, without the warning
            return None

    def certificate_check(self) -> Callable[[str], Optional[bool]]:
        """Whether a run's certificate is on disk (or mirrored) and unaltered.

        Looks where the certificate routes look, so a run table and the Certificates
        view never disagree about the same run.
        """
        from ducta.api.services.run_certificates import load_run_certificate
        from ducta.api.workspace.manager import WorkspaceManager
        from ducta.core.certificate import resolve_signing_key_from_dir, verify_certificate_data

        project_dir = self._source_path
        if self._project:
            project_dir = WorkspaceManager(self._source_path).for_project(self._project).root
        signing_key = resolve_signing_key_from_dir(project_dir)

        def check(run_id: str) -> Optional[bool]:
            try:
                data = load_run_certificate(project_dir, run_id, self._env)
                if data is None:
                    return False
                return bool(verify_certificate_data(data, signing_key=signing_key).ok)
            except Exception as exc:  # noqa: BLE001 — unreadable counts as not intact
                logger.debug("Could not verify the certificate of run {}: {}", run_id, exc)
                return False

        return check

    def serving_references(self) -> Dict[str, List[Dict[str, Any]]]:
        """Which nodes of this project serve each registered model."""
        return serving_references(_compiled_project(self._source_path, self._env, self._project))

    def tracker(self) -> ExperimentTracker:
        storage = LocalStorageBackend(base_path=self.storage)
        return ExperimentTracker(storage=storage, tracking_path=DEFAULT_TRACKING_PATH)

    def registry(self) -> ModelRegistry:
        return _registry_at(self.storage)


def _registry_at(storage_path: str) -> ModelRegistry:
    storage = LocalStorageBackend(base_path=storage_path)
    return ModelRegistry(storage=storage, registry_path=DEFAULT_REGISTRY_PATH)


def resolve_served_models(
    nodes: Dict[str, Dict[str, Any]],
    source_path: Path,
    env: Optional[str],
    project: Optional[str] = None,
) -> None:
    """Add ``model_resolution`` to each planned node with a ``model``: the version its
    stage names in the registry right now — what a run starting now would pin.

    Reads registry metadata only; nothing is downloaded or loaded.
    """
    from ducta.mlrun.serving import ServingError, resolve_model
    from ducta.setting.project.schema import ModelRef

    registry: Optional[ModelRegistry] = None
    for item in nodes.values():
        raw = item.get("model")
        if not raw:
            continue
        try:
            ref = ModelRef.model_validate(raw)
            if ref.source != "ducta":
                item["model_resolution"] = {
                    "status": "at_run_time",
                    "message": "an MLflow model is resolved when the run starts",
                }
                continue
            if registry is None:
                registry = _registry_at(
                    _resolve_mlops_storage(source_path, None, env, project=project)
                )
            resolved = resolve_model(ref, registry=registry)
            item["model_resolution"] = {
                "status": "resolved",
                "version": resolved.version,
                "stage": resolved.stage_at_resolution,
                "framework": resolved.framework,
                "artifact_sha256": resolved.registered_sha256,
            }
        except ServingError as e:
            item["model_resolution"] = {"status": "unresolved", "message": str(e)}
        except Exception as e:  # noqa: BLE001 — a plan must render even without a registry
            item["model_resolution"] = {
                "status": "unknown",
                "message": f"could not read the model registry: {e}",
            }


MLOpsScopeDep = Annotated[MLOpsScope, Depends()]


# ── Status endpoint ──────────────────────────────────────────────────────────

# Directories the tracker and registry own inside the storage path; anything else
# holding a ``latest.txt`` is a model persisted without a registry.
_RESERVED_STORAGE_DIRS = {DEFAULT_TRACKING_PATH, DEFAULT_REGISTRY_PATH}


def unregistered_models(storage_path: str) -> List[Dict[str, Any]]:
    """Models written as plain files (``<name>/<stamp>/model.*`` + ``latest.txt``).

    That is what ``persist_model`` falls back to when MLOps is off for a run: the
    model exists and can be served, but has no experiment and no registry entry,
    so neither tab can list it.
    """
    from datetime import datetime, timezone

    root = Path(storage_path)
    if not root.is_dir():
        return []
    found: List[Dict[str, Any]] = []
    for entry in sorted(root.iterdir()):
        pointer = entry / "latest.txt"
        if entry.name in _RESERVED_STORAGE_DIRS or not entry.is_dir() or not pointer.is_file():
            continue
        stamps = [d for d in entry.iterdir() if d.is_dir()]
        found.append(
            {
                "name": entry.name,
                "versions": len(stamps),
                "latest": pointer.read_text(encoding="utf-8").strip() or None,
                "updated_at": datetime.fromtimestamp(
                    max((d.stat().st_mtime for d in stamps), default=pointer.stat().st_mtime),
                    tz=timezone.utc,
                ).isoformat(),
            }
        )
    return found


def _policy_view(global_config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """``mlops.promotion_policy`` as the UI shows it: None when there is none, and
    ``{"error": …}`` when it cannot be used (a Production promotion is then refused)."""
    try:
        policy = PromotionPolicy.from_settings(global_config.get("mlops"))
    except ValueError as exc:
        return {"error": str(exc)}
    if policy is None:
        return None
    from dataclasses import asdict

    return asdict(policy)


@router.get("/status", dependencies=[Depends(require_permission("execution.read"))])
async def mlops_status(scope: MLOpsScopeDep) -> Dict[str, Any]:
    """Why the experiments / registry views are empty, or that they are not.

    ``mlops_enabled`` is the setting runs of this environment use; the tracker and
    registry only exist on disk once a run with it on has written to them.
    """
    from ducta.core.settings import CoreSettings

    def _run() -> Dict[str, Any]:
        gs = scope.global_config
        storage = Path(scope.storage)
        return {
            "storage_path": scope.storage,
            "mlops_enabled": CoreSettings._resolve_mlops_enabled(gs, gs.get("mlops") or {}),
            "tracking_present": (storage / DEFAULT_TRACKING_PATH).is_dir(),
            "registry_present": (storage / DEFAULT_REGISTRY_PATH).is_dir(),
            "unregistered_models": unregistered_models(scope.storage),
            "promotion_policy": _policy_view(gs),
        }

    return await run_in_threadpool(_run)


# ── Experiment endpoints ─────────────────────────────────────────────────────


def _present_run(run: Dict[str, Any]) -> Dict[str, Any]:
    """A run as the UI shows it: ``parameters`` are the user's hyperparameters; the ones
    Ducta records for itself (a leading ``_``: environment snapshot, input fingerprints,
    code hash) are apart in ``internal_parameters``, so they never bury the user's."""
    params = run.get("parameters") or {}
    return {
        **run,
        "parameters": {k: v for k, v in params.items() if not str(k).startswith("_")},
        "internal_parameters": {k: v for k, v in params.items() if str(k).startswith("_")},
    }


@router.get("/experiments", dependencies=[Depends(require_permission("execution.read"))])
async def list_experiments(scope: MLOpsScopeDep) -> List[Dict[str, Any]]:
    """List MLOps experiments (most recent first) — only the scoped pipeline's
    when ``pipeline`` is given: the tracking store is shared by every pipeline."""

    def _run() -> List[Dict[str, Any]]:
        experiments = scope.tracker().list_experiments()
        if scope.pipeline:
            experiments = [e for e in experiments if e.get("name") == scope.pipeline]
        return experiments

    return await run_in_threadpool(_run)


@router.get(
    "/experiments/{experiment_id}",
    dependencies=[Depends(require_permission("execution.read"))],
)
async def get_experiment(experiment_id: str, scope: MLOpsScopeDep) -> Dict[str, Any]:
    """Get an experiment and its runs."""

    def _run() -> Dict[str, Any]:
        tracker = scope.tracker()
        exp = tracker.get_experiment(experiment_id)
        return {
            "experiment_id": exp.experiment_id,
            "name": exp.name,
            "created_at": exp.created_at,
            "artifact_location": exp.artifact_location,
            "runs": [_present_run(r) for r in tracker.list_runs(experiment_id, with_metrics=True)],
        }

    return await run_in_threadpool(_run)


@router.get("/run-table", dependencies=[Depends(require_permission("execution.read"))])
async def run_table(
    scope: MLOpsScopeDep,
    sort_by: Optional[str] = Query(
        None, description="Column to order by (newest first if omitted)"
    ),
    ascending: bool = Query(False, description="Direction for sort_by"),
    verify_certificates: bool = Query(
        False, description="Check each run's certificate; reads one file per run"
    ),
) -> Dict[str, Any]:
    """One row per tracked run, joined with the model it registered and its certificate:
    the same table ``run_summary`` writes from a pipeline node.

    ``columns`` lists the keys in order (``param_*`` are hyperparameters, ``metric_*``
    final metrics); a column no run has a value for is left out.
    """

    def _run() -> Dict[str, Any]:
        import json

        from ducta.mlrun.summary import run_summary

        try:
            frame = run_summary(
                mlops_path=scope.storage,
                pipeline=scope.pipeline,
                certificate_check=scope.certificate_check() if verify_certificates else None,
                sort_by=sort_by,
                ascending=ascending,
            )
        except ValueError as exc:
            raise ValidationError(str(exc), detail={"sort_by": sort_by}) from exc
        # to_json writes NaN/NaT as null and numpy scalars as plain numbers.
        rows = json.loads(frame.to_json(orient="records", date_format="iso"))
        return {"columns": [str(c) for c in frame.columns], "rows": rows}

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


def _production_and_refusal(registry: ModelRegistry, model: Dict[str, Any]) -> Dict[str, Any]:
    """The version in Production (and its metrics), and why the latest version was
    refused if it was.

    ``stage`` is the *latest* version's: after a retrain the policy refused, v1 is in
    Production and v2 in Staging, and the UI filed the model under Staging with no
    sign of what was serving.
    """
    name = str(model.get("name"))
    out: Dict[str, Any] = {
        "production_version": None,
        "production_metrics": None,
        "latest_refusal": None,
    }
    try:
        production = [
            v["version"]
            for v in registry.list_model_versions_lite(name)
            if str(v.get("stage")) == ModelStage.PRODUCTION.value
        ]
        if production:
            out["production_version"] = max(production)
            out["production_metrics"] = registry.get_model_version(
                name, out["production_version"]
            ).metadata.metrics
        latest = model.get("latest_version")
        if model.get("stage") == ModelStage.STAGING.value:
            for entry in registry.audit_history(name):
                if entry.get("version") != latest:
                    continue
                if entry.get("event") == "PROMOTE_REFUSED":
                    out["latest_refusal"] = {
                        "timestamp": entry.get("timestamp"),
                        "reason": (entry.get("details") or {}).get("refusal"),
                    }
                break
    except Exception as exc:  # noqa: BLE001 — the list renders without the extras
        logger.debug("Could not read the stages of model {}: {}", name, exc)
    return out


@router.get("/models", dependencies=[Depends(require_permission("execution.read"))])
async def list_models(scope: MLOpsScopeDep) -> List[Dict[str, Any]]:
    """List all registered models (latest version per model).

    Each carries ``served_by``: the project's serving nodes that name it, with the
    stage or version they ask for.
    """

    def _run() -> List[Dict[str, Any]]:
        registry = scope.registry()
        served = scope.serving_references()
        return [
            {
                **m,
                "served_by": served.get(str(m.get("name")), []),
                **_production_and_refusal(registry, m),
            }
            for m in registry.list_models()
        ]

    return await run_in_threadpool(_run)


@router.get("/models/{name}", dependencies=[Depends(require_permission("execution.read"))])
async def get_model_versions(name: str, scope: MLOpsScopeDep) -> List[Dict[str, Any]]:
    """Get all versions of a model."""
    return await run_in_threadpool(lambda: scope.registry().list_model_versions(name))


def _promotion_policy(
    scope: Any, target_stage: ModelStage, *, force: bool
) -> Optional[PromotionPolicy]:
    """``mlops.promotion_policy`` for a promotion, as the CLI reads it.

    An invalid policy, or one that names no metric, was ignored with a warning and
    the version promoted without its gate. It now refuses a Production promotion
    unless ``force`` (whose bypass the registry audit-logs).
    """
    if target_stage != ModelStage.PRODUCTION:
        return None
    try:
        return PromotionPolicy.from_settings(scope.global_config.get("mlops"))
    except ValueError as exc:
        if not force:
            raise ValidationError(
                f"Cannot check the promotion gate: {exc}. "
                "Fix it, or promote with force (the bypass is audit-logged).",
                detail={"promotion_policy": "invalid"},
            ) from exc
        logger.warning("Promotion gate not checked (invalid policy: {}); force=true", exc)
        return None


@router.get(
    "/models/{name}/history",
    dependencies=[Depends(require_permission("execution.read"))],
)
async def model_history(name: str, scope: MLOpsScopeDep) -> List[Dict[str, Any]]:
    """The model's audit log, newest first: registrations, promotions (and refused
    ones), deletions, with who did it and why."""
    return await run_in_threadpool(lambda: scope.registry().audit_history(name))


@router.get(
    "/models/{name}/versions/{version}/promotion-check",
    dependencies=[Depends(require_permission("execution.read"))],
)
async def promotion_check(name: str, version: int, scope: MLOpsScopeDep) -> Dict[str, Any]:
    """Would promoting *version* to Production pass the project's policy? Changes
    nothing; the same check the promotion runs."""

    def _run() -> Dict[str, Any]:
        registry = scope.registry()
        registry.get_model_version(name, version)  # 404 for an unknown version
        production = [
            v["version"]
            for v in registry.list_model_versions_lite(name)
            if str(v.get("stage")) == ModelStage.PRODUCTION.value
        ]
        policy_view = _policy_view(scope.global_config)
        out: Dict[str, Any] = {
            "policy": policy_view,
            "production_version": max(production) if production else None,
            "served_by": scope.serving_references().get(name, []),
            "passes": True,
            "reason": None,
        }
        if policy_view and "error" in policy_view:
            out.update(passes=False, reason=f"the policy cannot be used: {policy_view['error']}")
        elif policy_view:
            policy = PromotionPolicy.from_settings(scope.global_config.get("mlops"))
            assert policy is not None  # _policy_view saw a valid one
            refusal = registry.check_promotion_gate(name, version, policy)
            out.update(passes=refusal is None, reason=refusal)
        return out

    return await run_in_threadpool(_run)


@router.post("/models/{name}/promote")
async def promote_model(
    name: str,
    body: PromoteModelRequest,
    scope: MLOpsScopeDep,
    user: Annotated[User, Depends(require_permission("model.promote"))],
) -> Dict[str, Any]:
    """Promote a model version to a new stage, as the signed-in user (audit-logged)."""
    target_stage = ModelStage(body.stage.capitalize())
    reason = (body.reason or "").strip() or None
    if body.force and not reason:
        raise ValidationError(
            "A forced promotion needs a reason: it is recorded in the audit log.",
            detail={"reason": "required with force"},
        )

    policy = _promotion_policy(scope, target_stage, force=body.force)

    def _run() -> Dict[str, Any]:
        registry = scope.registry()
        demoted: List[int] = []
        if target_stage == ModelStage.PRODUCTION:
            demoted = [
                v["version"]
                for v in registry.list_model_versions_lite(name)
                if str(v.get("stage")) == ModelStage.PRODUCTION.value
                and v["version"] != body.version
            ]
        registry.promote_model(
            name,
            body.version,
            target_stage,
            user=user.username,
            reason=reason,
            policy=policy,
            force=body.force,
        )
        return {
            "name": name,
            "version": body.version,
            "stage": target_stage.value,
            "promoted": True,
            # Archived by this promotion: only one version is in Production.
            "demoted_versions": demoted,
        }

    return await run_in_threadpool(_run)


@router.delete("/models/{name}/versions/{version}", status_code=204)
async def delete_model_version(
    name: str,
    version: int,
    scope: MLOpsScopeDep,
    user: Annotated[User, Depends(require_permission("model.delete"))],
) -> None:
    """Delete a specific model version and its artifact (audit-logged). A version in
    Production is refused: archive it first by promoting another."""
    await run_in_threadpool(
        lambda: scope.registry().delete_model_version(name, version, user=user.username)
    )


# Garbage collection deletes old model versions: the same right as deleting one.
@router.post("/gc")
async def run_gc(
    body: GcRequest,
    scope: MLOpsScopeDep,
    user: Annotated[User, Depends(require_permission("model.delete"))],
) -> Dict[str, Any]:
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
            certificate_dir=scope.certificate_dir(),
        ).run(dry_run=body.dry_run, user=user.username)
        return {
            "dry_run": body.dry_run,
            "models_processed": stats.get("models_processed", 0),
            "versions_removed": stats.get("versions_removed", 0),
            "bytes_freed": stats.get("bytes_freed", 0),
            # Removed (or, on a dry run, that would be): a run that used one of these
            # can no longer be reproduced.
            "versions": stats.get("versions", []),
            "storage_path": scope.storage,
        }

    return await run_in_threadpool(_run)
