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

from typing import Any, Dict, Optional

from loguru import logger  # type: ignore

from ducta.console.core import ExitCode
from ducta.mlrun.config import DEFAULT_REGISTRY_PATH, DEFAULT_STORAGE_PATH, DEFAULT_TRACKING_PATH
from ducta.mlrun.exceptions import ModelNotFoundError, PromotionGateError
from ducta.mlrun.experiment_tracking import ExperimentTracker
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


def _global_settings_of(context: Optional[Any]) -> Dict[str, Any]:
    """Best-effort ``global_settings`` dict from a (possibly ``None``) Context."""
    if context is None:
        return {}
    gs = getattr(context, "global_settings", {})
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

    gs = _global_settings_of(context)
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
    """Read mlops.promotion_policy from global settings, if configured."""
    gs = _global_settings_of(_discover_context(env))
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
        registry = _build_registry(_build_storage(resolved_path))
        policy = _resolve_promotion_policy(env)
        if policy and target_stage == ModelStage.PRODUCTION:
            logger.info(
                f"Applying promotion policy: {policy.metric} vs {policy.compare_to} "
                f"(min_delta={policy.min_delta:+})"
            )

        registry.promote_model(
            model_name,
            int(version),
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
