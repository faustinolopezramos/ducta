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

import json
from typing import Any, Dict, List, Optional

from loguru import logger  # type: ignore

from ducta.console.core import ExitCode
from ducta.mlrun.config import DEFAULT_REGISTRY_PATH, DEFAULT_STORAGE_PATH, DEFAULT_TRACKING_PATH
from ducta.mlrun.exceptions import (
    ExperimentNotFoundError,
    ModelNotFoundError,
    PromotionGateError,
    RunNotFoundError,
)
from ducta.mlrun.experiment_tracking import ExperimentTracker, RunStatus
from ducta.mlrun.model_registry import ModelRegistry, ModelStage, PromotionPolicy
from ducta.mlrun.storage import LocalStorageBackend


def _discover_context(env: Optional[str]) -> Optional[Any]:
    """Build a real project ``Context`` for ``env``, reusing the same
    ``ConfigManager`` + ``ContextInitializer`` path ``quality`` already uses
    (``console/commands/quality_cmds.py:_resolve_storage_from_env``) — the
    resolver the runtime itself uses, instead of a CLI-only heuristic.
    """
    if not env:
        return None
    try:
        from ducta.console.config import ConfigManager
        from ducta.console.execution import ContextInitializer

        config_manager = ConfigManager(base_path=None, require_config=False)
        config_manager.change_to_config_directory()
        return ContextInitializer(config_manager).initialize(env)
    except Exception as e:
        logger.debug(f"Context discovery failed for env='{env}': {e}")
        return None


def _global_config_of(context: Optional[Any]) -> Dict[str, Any]:
    """Best-effort ``global_config`` dict from a (possibly ``None``) Context."""
    if context is None:
        return {}
    gs = getattr(context, "global_config", {})
    return gs if isinstance(gs, dict) else {}


def _resolve_storage_path(
    provided_path: Optional[str],
    env: Optional[str] = None,
    pipeline_name: Optional[str] = None,
) -> str:
    """Resolve storage path."""
    if provided_path:
        return provided_path

    context = _discover_context(env)
    if context is not None:
        from ducta.mlrun.config import StorageBackendFactory

        resolved = StorageBackendFactory._resolve_mlops_path(context, pipeline_name=pipeline_name)
        if resolved:
            return resolved

    gs = _global_config_of(context)
    mlops_cfg = gs.get("mlops") or {}
    heuristic = mlops_cfg.get("storage_path") or gs.get("mlops_storage_path")
    if heuristic:
        return heuristic

    from ducta.mlrun.config import MLOpsConfig

    env_path = MLOpsConfig._env("Ducta_MLOPS_PATH")
    return env_path or DEFAULT_STORAGE_PATH


def _build_storage(storage_path: str) -> LocalStorageBackend:
    return LocalStorageBackend(base_path=storage_path)


def _build_tracker(storage: LocalStorageBackend) -> ExperimentTracker:
    return ExperimentTracker(storage=storage, tracking_path=DEFAULT_TRACKING_PATH)


def _build_registry(storage: LocalStorageBackend) -> ModelRegistry:
    return ModelRegistry(storage=storage, registry_path=DEFAULT_REGISTRY_PATH)


def _resolve_promotion_policy(env: Optional[str] = None) -> Optional[PromotionPolicy]:
    """Read mlops.promotion_policy from global config, if configured."""
    gs = _global_config_of(_discover_context(env))
    policy_cfg = (gs.get("mlops") or {}).get("promotion_policy")
    if not isinstance(policy_cfg, dict) or not policy_cfg.get("metric"):
        return None
    try:
        return PromotionPolicy.from_dict(policy_cfg)
    except Exception as e:
        logger.warning(f"Invalid mlops.promotion_policy ignored: {e}")
        return None


def experiment_list(
    storage_path: Optional[str],
    env: Optional[str] = None,
    limit: Optional[int] = None,
    pipeline_name: Optional[str] = None,
) -> int:
    """List recent MLOps experiments."""
    resolved_path = _resolve_storage_path(storage_path, env, pipeline_name)
    try:
        tracker = _build_tracker(_build_storage(resolved_path))
        exps = tracker.list_experiments()
        if limit is not None:
            exps = exps[:limit]
        print(f"\nMLOps Experiments (Storage: {resolved_path})")
        print("-" * 60)
        if not exps:
            print("No experiments found.")
            return 0

        for exp in exps:
            print(
                f"ID: {exp.get('experiment_id', 'N/A')} | "
                f"Name: {exp.get('name', 'N/A')} | "
                f"Created: {exp.get('created_at', 'N/A')}"
            )
        print("-" * 60)
        return 0
    except Exception as e:
        logger.error(f"Failed to list experiments: {e}")
        return 1


def _tracker_for(
    storage_path: Optional[str], env: Optional[str], pipeline_name: Optional[str]
) -> "tuple[ExperimentTracker, str]":
    """The tracker a command reads, and the path it was resolved to."""
    resolved_path = _resolve_storage_path(storage_path, env, pipeline_name)
    return _build_tracker(_build_storage(resolved_path)), resolved_path


def _resolve_run_id(tracker: ExperimentTracker, run_id: str) -> str:
    """``run_id`` as typed, or the one run it is a unique prefix of (run ids are UUIDs)."""
    try:
        tracker.get_run(run_id)
        return run_id
    except RunNotFoundError:
        known = [str(r) for r in tracker._load_runs_index()["run_id"]]
        matches = [r for r in known if r.startswith(run_id)]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ValueError(f"'{run_id}' matches {len(matches)} runs; give more characters")
        raise


def _lookup_failed(error: Exception, resolved_path: str) -> int:
    """One exit-code policy for the read-only experiment commands."""
    if isinstance(error, (RunNotFoundError, ExperimentNotFoundError, ValueError)):
        logger.error(f"{error} (searched {resolved_path}; use --env/--pipeline or --storage-path)")
        return ExitCode.VALIDATION_ERROR.value
    logger.error(f"Experiment command failed: {error}")
    return ExitCode.GENERAL_ERROR.value


def _latest_metrics(run: Any) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key in run.metrics:
        latest = run.metric_index.get_latest(key)
        if latest is not None:
            out[key] = latest.value
    return out


def experiment_runs(
    experiment_id: str,
    storage_path: Optional[str],
    env: Optional[str] = None,
    limit: Optional[int] = None,
    pipeline_name: Optional[str] = None,
    status: Optional[str] = None,
    output_format: str = "rich",
) -> int:
    """List the runs of one experiment, newest first."""
    tracker, resolved_path = _tracker_for(storage_path, env, pipeline_name)
    try:
        status_filter = RunStatus(status.upper()) if status else None
        runs: List[Dict[str, Any]] = tracker.list_runs(experiment_id, status_filter=status_filter)
        runs.sort(key=lambda r: str(r.get("created_at", "")), reverse=True)
        if limit is not None:
            runs = runs[:limit]
        if output_format == "json":
            print(json.dumps(runs, indent=2, default=str))
            return 0
        print(f"\nRuns of experiment {experiment_id} (Storage: {resolved_path})")
        print("-" * 60)
        if not runs:
            print("No runs found. `ducta experiment list` shows the experiment ids.")
            return 0
        for run in runs:
            duration = run.get("duration_seconds")
            print(
                f"{run['run_id']} | {run['status']:<9} | {run.get('created_at', 'N/A')} | "
                f"{'-' if duration is None else f'{duration:.1f}s'} | {run.get('name', '')}"
            )
        print("-" * 60)
        return 0
    except Exception as e:  # noqa: BLE001 — mapped to an exit code
        return _lookup_failed(e, resolved_path)


def experiment_show(
    run_id: str,
    storage_path: Optional[str],
    env: Optional[str] = None,
    pipeline_name: Optional[str] = None,
    output_format: str = "rich",
) -> int:
    """Everything one run recorded: parameters, final metrics, tags, artifacts."""
    tracker, resolved_path = _tracker_for(storage_path, env, pipeline_name)
    try:
        run = tracker.get_run(_resolve_run_id(tracker, run_id))
        if output_format == "json":
            print(json.dumps(run.to_dict(), indent=2, default=str))
            return 0
        print(f"\nRun {run.run_id} (Storage: {resolved_path})")
        print("-" * 60)
        print(f"Name:        {run.name}")
        print(f"Experiment:  {run.experiment_id}")
        print(f"Status:      {run.status.value}")
        print(f"Created:     {run.created_at}")
        if run.duration_seconds is not None:
            print(f"Duration:    {run.duration_seconds:.1f}s")
        for title, values in (
            ("Parameters", run.parameters),
            ("Metrics (latest)", _latest_metrics(run)),
            ("Tags", run.tags),
        ):
            print(f"\n{title}:")
            if values:
                width = max(len(str(k)) for k in values)
                for key, value in values.items():
                    print(f"  {str(key):<{width}}  {value}")
            else:
                print("  (none)")
        print(f"\nArtifacts: {len(run.artifacts)}")
        for artifact in run.artifacts:
            print(f"  {artifact}")
        return 0
    except Exception as e:  # noqa: BLE001 — mapped to an exit code
        return _lookup_failed(e, resolved_path)


def experiment_compare(
    run_ids: List[str],
    storage_path: Optional[str],
    env: Optional[str] = None,
    pipeline_name: Optional[str] = None,
    output_format: str = "rich",
) -> int:
    """Parameters and final metrics of several runs side by side."""
    if len(run_ids) < 2:
        logger.error("compare needs at least two run ids")
        return ExitCode.VALIDATION_ERROR.value
    tracker, resolved_path = _tracker_for(storage_path, env, pipeline_name)
    try:
        frame = tracker.compare_runs([_resolve_run_id(tracker, r) for r in run_ids])
        if output_format == "json":
            print(frame.to_json(orient="records", indent=2))
            return 0
        print(f"\nComparison of {len(frame)} runs (Storage: {resolved_path})")
        print("-" * 60)
        # One row per run is wide; one row per field reads better in a terminal.
        print(frame.set_index("run_id").T.to_string(na_rep="-"))
        return 0
    except Exception as e:  # noqa: BLE001 — mapped to an exit code
        return _lookup_failed(e, resolved_path)


def _parse_model_version(text: Any) -> int:
    """``3`` or ``v3`` as 3. A registry version is the integer it was assigned at
    registration, not a semantic version, so ``1.2.0`` is refused with that explanation
    instead of ``invalid literal for int()``."""
    value = str(text).strip().lower()
    number = value[1:] if value.startswith("v") else value
    if not number.isdigit():
        raise ValueError(
            f"'{text}' is not a model version. Registry versions are whole numbers "
            "(1, 2, 3, ... or v1, v2, ...), assigned when the model is registered."
        )
    return int(number)


def model_promote(
    model_name: str,
    version: str,
    stage: str,
    storage_path: Optional[str],
    force: bool = False,
    env: Optional[str] = None,
    pipeline_name: Optional[str] = None,
) -> int:
    """Promote a model version to a new stage."""
    resolved_path = _resolve_storage_path(storage_path, env, pipeline_name)
    try:
        target_stage = ModelStage(stage.capitalize())
    except ValueError:
        logger.error(f"Invalid stage '{stage}'. Valid: staging, production, archived")
        return ExitCode.VALIDATION_ERROR.value
    try:
        version_number = _parse_model_version(version)
    except ValueError as e:
        logger.error(str(e))
        return ExitCode.VALIDATION_ERROR.value

    try:
        registry = _build_registry(_build_storage(resolved_path))
        policy = _resolve_promotion_policy(env)
        if policy and target_stage == ModelStage.PRODUCTION:
            logger.info(
                f"Applying promotion policy: {policy.metric} vs {policy.compare_to} "
                f"(min_delta={policy.min_delta:+})"
            )

        registry.promote_model(
            model_name,
            version_number,
            target_stage,
            policy=policy,
            force=force,
        )
        print(
            f"Model '{model_name}' version '{version}' successfully promoted "
            f"to '{target_stage.value}'."
        )
        return 0
    except ModelNotFoundError as e:
        logger.error(f"Failed to promote model: {e}")
        return ExitCode.VALIDATION_ERROR.value
    except PromotionGateError as e:
        logger.error(f"Promotion refused by gate: {e}")
        return ExitCode.EXECUTION_ERROR.value
    except Exception as e:
        logger.error(f"Failed to promote model: {e}")
        return ExitCode.GENERAL_ERROR.value


def model_gc(
    storage_path: Optional[str],
    dry_run: bool = False,
    env: Optional[str] = None,
    pipeline_name: Optional[str] = None,
) -> int:
    """Garbage collect old models."""
    resolved_path = _resolve_storage_path(storage_path, env, pipeline_name)
    try:
        from ducta.mlrun.config import MLOpsConfig
        from ducta.mlrun.gc import ModelGarbageCollector

        mlops_config = MLOpsConfig.from_env()
        gc = ModelGarbageCollector(
            storage_path=resolved_path,
            max_versions_per_model=mlops_config.max_versions_per_model,
            model_retention_days=mlops_config.model_retention_days,
        )
        stats = gc.run(dry_run=dry_run)

        print("\nModel Garbage Collection Stats")
        print("-" * 60)
        print(f"Dry run: {dry_run}")
        print(f"Models processed: {stats.get('models_processed', 0)}")
        print(f"Versions removed: {stats.get('versions_removed', 0)}")
        print(f"Space freed (bytes): {stats.get('bytes_freed', 0)}")
        print("-" * 60)
        return 0
    except Exception as e:
        logger.error(f"Failed to run garbage collection: {e}")
        return 1
