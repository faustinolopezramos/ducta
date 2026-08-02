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

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from loguru import logger  # type: ignore


def _serialize(model: Any, path: Path) -> str:
    """Serialize ``model`` to ``path``; prefer joblib, fall back to pickle."""
    try:
        import joblib  # type: ignore

        joblib.dump(model, path)
        return "joblib"
    except Exception:
        import pickle

        with open(path, "wb") as handle:
            pickle.dump(model, handle)
        return "pickle"


def _ctx_get(ml_context: Any, key: str, default: Any = None) -> Any:
    """Read a key from an MLNodeContext, a Mapping, or any attribute holder."""
    if ml_context is None:
        return default
    if isinstance(ml_context, Mapping):
        return ml_context.get(key, default)
    return getattr(ml_context, key, default)


def persist_model(
    model: Any,
    ml_context: Any,
    name: str,
    *,
    framework: str = "sklearn",
    metrics: Optional[Dict[str, float]] = None,
    hyperparameters: Optional[Dict[str, Any]] = None,
    description: str = "",
    base_dir: str = "models",
) -> Dict[str, Any]:
    """Persist a trained model reproducibly and return ``{"artifact_uri": ...}``.

    Prefers the MLOps model registry (versioned by design). When no registry is
    available it writes a run/version-stamped local file with a ``latest`` pointer,
    never overwriting a previous version.

    Args:
        model: The trained model object.
        ml_context: The node's ``ml_context`` (used for run id, version, registry).
        name: Logical model name (registry key / local subfolder).
        framework: Model framework (e.g. ``"sklearn"``, ``"xgboost"``).
        metrics: Evaluation metrics to record alongside the version.
        hyperparameters: Hyperparameters to record alongside the version.
        description: Optional human-readable description.
        base_dir: Base directory for the local fallback.
    """
    mlops_context = _ctx_get(ml_context, "mlops_context")
    run_id = _ctx_get(ml_context, "mlops_run_id")
    model_version = _ctx_get(ml_context, "model_version")
    registry = getattr(mlops_context, "model_registry", None) if mlops_context else None

    stamp = str(run_id or model_version or datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"))

    # --- Preferred path: the versioned model registry -----------------------
    if registry is not None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / f"{name}.pkl"
            _serialize(model, artifact)
            try:
                version = registry.register_model(
                    name=name,
                    artifact_path=str(artifact),
                    artifact_type="pickle",
                    framework=framework,
                    description=description,
                    hyperparameters=hyperparameters,
                    metrics=metrics,
                    experiment_run_id=run_id,
                )
                logger.info(
                    "Registered model '{}' v{} in registry (uri={})",
                    name,
                    version.version,
                    version.artifact_uri,
                )
                return {"artifact_uri": version.artifact_uri, "version": version.version}
            except Exception as error:
                logger.warning(
                    "Model registry registration failed ({}); falling back to local "
                    "versioned file.",
                    error,
                )

    # --- Fallback: run/version-stamped local file with a 'latest' pointer ----
    dest_dir = Path(base_dir) / name / stamp
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "model.pkl"
    serializer = _serialize(model, dest)

    # Portable 'latest' pointer (no symlink dependency): a text file with the path.
    pointer = Path(base_dir) / name / "latest.txt"
    pointer.write_text(str(dest.resolve()), encoding="utf-8")

    logger.info("Persisted model '{}' to {} ({}); latest -> {}", name, dest, serializer, pointer)
    # file:// URI so the executor recognizes it as an artifact and skips DataFrame save.
    return {"artifact_uri": dest.resolve().as_uri(), "version": stamp}
