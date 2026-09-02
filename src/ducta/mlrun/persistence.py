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


def infer_schema(data: Any) -> Optional[Dict[str, str]]:
    """Infer a ``{column: dtype}`` contract from a pandas DataFrame/Series."""
    if data is None:
        return None
    try:
        columns = getattr(data, "columns", None)
        dtypes = getattr(data, "dtypes", None)

        # DataFrame: one entry per column.
        if columns is not None and dtypes is not None:
            return {str(col): str(dtype) for col, dtype in zip(columns, dtypes)}

        if dtypes is not None:
            return {str(getattr(data, "name", None) or "target"): str(dtypes)}
    except Exception as e:  # noqa: BLE001 — schema capture is best-effort
        logger.debug("Could not infer schema from {}: {}", type(data).__name__, e)
    return None


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
    X: Any = None,
    y: Any = None,
    input_schema: Optional[Dict[str, str]] = None,
    output_schema: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Persist a trained model reproducibly and return ``{"artifact_uri": ...}``."""
    mlops_context = _ctx_get(ml_context, "mlops_context")
    run_id = _ctx_get(ml_context, "mlops_run_id")
    model_version = _ctx_get(ml_context, "model_version")
    registry = getattr(mlops_context, "model_registry", None) if mlops_context else None

    stamp = str(run_id or model_version or datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"))

    resolved_input_schema = input_schema if input_schema is not None else infer_schema(X)
    resolved_output_schema = output_schema if output_schema is not None else infer_schema(y)
    if resolved_input_schema is None:
        logger.debug(
            "Model '{}' registered without an input schema: pass X= (the training features) "
            "to persist_model so the version carries its feature contract and the promotion "
            "gate can detect schema drift against the incumbent.",
            name,
        )

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
                    input_schema=resolved_input_schema,
                    output_schema=resolved_output_schema,
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

    dest_dir = Path(base_dir) / name / stamp
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "model.pkl"
    serializer = _serialize(model, dest)

    pointer = Path(base_dir) / name / "latest.txt"
    pointer.write_text(str(dest.resolve()), encoding="utf-8")

    logger.info("Persisted model '{}' to {} ({}); latest -> {}", name, dest, serializer, pointer)
    return {"artifact_uri": dest.resolve().as_uri(), "version": stamp}
