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

from ducta.mlrun.config import DEFAULT_REGISTRY_PATH, DEFAULT_TRACKING_PATH
from ducta.mlrun.experiment_tracking import ExperimentTracker
from ducta.mlrun.model_registry import ModelRegistry, ModelStage, PromotionPolicy
from ducta.mlrun.storage import LocalStorageBackend


def _discover_global_settings() -> Dict[str, Any]:
    """Best-effort discovery of global settings from the current project."""
    try:
        from ducta.setting.context_loader import discover_context

        ctx = discover_context()
        if ctx and hasattr(ctx, "global_settings"):
            gs = ctx.global_settings
            return gs if isinstance(gs, dict) else {}
    except Exception as e:
        logger.debug(f"Context discovery failed: {e}")
    return {}


def _resolve_storage_path(provided_path: Optional[str]) -> str:
    """Resolve storage path: uses override if provided, else tries context discovery."""
    if provided_path:
        return provided_path
    gs = _discover_global_settings()
    mlops_cfg = gs.get("mlops") or {}
    return mlops_cfg.get("storage_path") or gs.get("mlops_storage_path") or "./mlops_data"


def _build_tracker(storage_path: str) -> ExperimentTracker:
    storage = LocalStorageBackend(base_path=storage_path)
    return ExperimentTracker(storage=storage, tracking_path=DEFAULT_TRACKING_PATH)


def _build_registry(storage_path: str) -> ModelRegistry:
    storage = LocalStorageBackend(base_path=storage_path)
    return ModelRegistry(storage=storage, registry_path=DEFAULT_REGISTRY_PATH)


def _resolve_promotion_policy() -> Optional[PromotionPolicy]:
    """Read mlops.promotion_policy from global settings, if configured.
    """
    gs = _discover_global_settings()
    policy_cfg = (gs.get("mlops") or {}).get("promotion_policy")
    if not isinstance(policy_cfg, dict) or not policy_cfg.get("metric"):
        return None
    try:
        return PromotionPolicy.from_dict(policy_cfg)
    except Exception as e:
        logger.warning(f"Invalid mlops.promotion_policy ignored: {e}")
        return None


def experiment_list(storage_path: Optional[str]) -> int:
    """List recent MLOps experiments."""
    resolved_path = _resolve_storage_path(storage_path)
    try:
        tracker = _build_tracker(resolved_path)
        exps = tracker.list_experiments()
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
) -> int:
    """Promote a model version to a new stage.
    """
    resolved_path = _resolve_storage_path(storage_path)
    try:
        target_stage = ModelStage(stage.capitalize())
    except ValueError:
        logger.error(f"Invalid stage '{stage}'. Valid: staging, production, archived")
        return 1

    try:
        registry = _build_registry(resolved_path)
        policy = _resolve_promotion_policy()
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
    except Exception as e:
        logger.error(f"Failed to promote model: {e}")
        return 1


def model_gc(storage_path: Optional[str], dry_run: bool = False) -> int:
    """Garbage collect old models."""
    resolved_path = _resolve_storage_path(storage_path)
    try:
        from ducta.mlrun.gc import ModelGarbageCollector

        gc = ModelGarbageCollector(storage_path=resolved_path)
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
