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

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

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


#: Values a context carries when nothing named a version (``MLNodeCommand`` falls back to
#: ``"unknown"``). They are not versions, so they must never name a directory.
_PLACEHOLDER_VERSIONS = frozenset({"", "none", "unknown"})


def _usable(value: Any) -> bool:
    return value is not None and str(value).strip().lower() not in _PLACEHOLDER_VERSIONS


def _safe_segment(value: Any) -> str:
    """``value`` as one path segment: anything outside ``[A-Za-z0-9._-]`` becomes ``_``."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", str(value).strip())


def _version_stamp(run_id: Any, model_version: Any) -> str:
    """The directory name a locally persisted model gets, unique for every call.

    A run id names the run that produced the model. A ``model_version`` is only a label the
    user chose, so it is suffixed with the time: a fixed ``v1`` would otherwise overwrite
    itself on every run, which is the bug this replaces (``models/<name>/unknown/``).
    """
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    if _usable(run_id):
        return _safe_segment(run_id)
    if _usable(model_version):
        return f"{_safe_segment(model_version)}-{now}"
    return now


#: Frameworks whose own file format can be written, and its suffix. A model saved this way
#: loads without unpickling anything, so scoring it needs no ``trust_artifact``.
_NATIVE_SUFFIX = {"xgboost": ".json", "lightgbm": ".txt"}


def _save_native(model: Any, framework: str, path: Path) -> bool:
    """Write ``model`` in its framework's own format; ``False`` when it has none to write."""
    if framework == "xgboost" and hasattr(model, "save_model"):
        model.save_model(str(path))
        return True
    if framework == "lightgbm":
        booster = getattr(model, "booster_", model)  # LGBMClassifier wraps a Booster
        if hasattr(booster, "save_model"):
            booster.save_model(str(path))
            return True
    return False


def _write_artifact(
    model: Any, framework: str, native: bool, directory: Path, stem: str
) -> Tuple[Path, str, str]:
    """``(file, artifact_type, how)`` — native when asked for and available, else pickled."""
    fw = (framework or "").lower()
    if native and fw in _NATIVE_SUFFIX:
        path = directory / f"{stem}{_NATIVE_SUFFIX[fw]}"
        if _save_native(model, fw, path):
            return path, fw, "native"
        logger.warning(
            "native=True, but {} has no {} save_model(); persisting it as a pickle",
            type(model).__name__,
            fw,
        )
    path = directory / f"{stem}.pkl"
    return path, "pickle", _serialize(model, path)


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
    native: bool = False,
) -> Dict[str, Any]:
    """Persist a trained model reproducibly and return ``{"artifact_uri": ...}``.

    ``native=True`` writes an xgboost or lightgbm model in the framework's own format
    (``.json`` / ``.txt``) instead of a pickle, so it can be scored without
    ``model.trust_artifact``. The scored model is then the framework's ``Booster``: for
    ``binary:logistic`` its ``predict`` returns probabilities, not the labels an sklearn
    wrapper's ``predict`` returns. Hence it is opt-in; any other model is pickled as before.
    """
    mlops_context = _ctx_get(ml_context, "mlops_context")
    run_id = _ctx_get(ml_context, "mlops_run_id")
    model_version = _ctx_get(ml_context, "model_version")
    registry = getattr(mlops_context, "model_registry", None) if mlops_context else None

    stamp = _version_stamp(run_id, model_version)

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
            artifact, artifact_type, _ = _write_artifact(model, framework, native, Path(tmp), name)
            try:
                version = registry.register_model(
                    name=name,
                    artifact_path=str(artifact),
                    artifact_type=artifact_type,
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
    dest, _, serializer = _write_artifact(model, framework, native, dest_dir, "model")

    pointer = Path(base_dir) / name / "latest.txt"
    pointer.write_text(str(dest.resolve()), encoding="utf-8")

    logger.info("Persisted model '{}' to {} ({}); latest -> {}", name, dest, serializer, pointer)
    return {"artifact_uri": dest.resolve().as_uri(), "version": stamp}
