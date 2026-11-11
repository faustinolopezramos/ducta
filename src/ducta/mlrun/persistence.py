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

from ducta.mlrun.validators import plain_number, validate_model_name


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


def log_run_metrics(ml_context: Any, metrics: Optional[Mapping[str, Any]]) -> None:
    """Best-effort: record each numeric metric on the tracked run, if there is one.

    A metric that cannot be logged (NaN, not a number) is skipped with a warning; it
    never fails the training node.
    """
    mlops = _ctx_get(ml_context, "mlops_context")
    run_id = _ctx_get(ml_context, "mlops_run_id")
    tracker = getattr(mlops, "experiment_tracker", None) if mlops else None
    if tracker is None or not run_id or not metrics:
        return
    for key, value in metrics.items():
        value = plain_number(value)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            logger.warning(
                "Metric '{}' is not a number ({}): not logged to run {}", key, value, run_id
            )
            continue
        try:
            tracker.log_metric(run_id, str(key), value)
        except Exception as error:  # noqa: BLE001 — tracking must not fail a training run
            logger.warning("Could not log metric '{}' to run {}: {}", key, run_id, error)


def log_run_params(ml_context: Any, params: Optional[Mapping[str, Any]]) -> None:
    """Best-effort: record each hyperparameter on the tracked run, if there is one.

    The model a run registered carries its hyperparameters, but a run table or
    ``ducta experiment compare`` reads them from the run, so they go there too. A value
    already on the run (one the run was asked to use) is rewritten with the same value.
    """
    mlops = _ctx_get(ml_context, "mlops_context")
    run_id = _ctx_get(ml_context, "mlops_run_id")
    tracker = getattr(mlops, "experiment_tracker", None) if mlops else None
    if tracker is None or not run_id or not params:
        return
    for key, value in params.items():
        try:
            tracker.log_parameter(run_id, str(key), value)
        except Exception as error:  # noqa: BLE001 — tracking must not fail a training run
            logger.warning("Could not log parameter '{}' to run {}: {}", key, run_id, error)


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


def _promote(
    registry: Any, mlops_context: Any, name: str, version: int, stage_name: str
) -> Dict[str, Any]:
    """Promote *version* through the project's policy: ``{promoted_to, promotion_refused?}``."""
    from ducta.mlrun.exceptions import PromotionGateError
    from ducta.mlrun.model_registry import ModelStage

    stage = _promotion_stage(stage_name)
    policy = getattr(mlops_context, "promotion_policy", None)
    if stage == ModelStage.PRODUCTION and policy is None:
        logger.warning(
            "Model '{}' v{} goes to production without a gate: settings.mlops has no "
            "promotion_policy",
            name,
            version,
        )
    try:
        registry.promote_model(
            name,
            version,
            stage,
            policy=policy if stage == ModelStage.PRODUCTION else None,
            reason="persist_model(promote=...)",
        )
    except PromotionGateError as e:
        logger.warning("Model '{}' v{} is not promoted to {}: {}", name, version, stage.value, e)
        return {"promoted_to": None, "promotion_refused": str(e)}
    logger.info("Model '{}' v{} promoted to {}", name, version, stage.value)
    return {"promoted_to": stage.value}


def _promotion_stage(stage_name: str) -> Any:
    """The ``ModelStage`` *stage_name* names; ``ValueError`` for anything else."""
    from ducta.mlrun.model_registry import ModelStage

    try:
        return ModelStage(str(stage_name).strip().capitalize())
    except ValueError as e:
        raise ValueError(
            f"promote must be one of {[s.value.lower() for s in ModelStage]}, got {stage_name!r}"
        ) from e


def _record_registration(ml_context: Any, name: str, version: Any, result: Dict[str, Any]) -> None:
    """Note the registered version on the node's ml_context, for the run certificate."""
    registered = _ctx_get(ml_context, "registered_models")
    if not isinstance(registered, list):
        return
    registered.append(
        {
            "name": name,
            "version": int(version.version),
            "uri": version.artifact_uri,
            "sha256": getattr(version, "artifact_sha256", None),
            "promoted_to": result.get("promoted_to"),
            **(
                {"promotion_refused": result["promotion_refused"]}
                if result.get("promotion_refused")
                else {}
            ),
        }
    )


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
    log_to_run: bool = True,
    promote: Optional[str] = None,
) -> Dict[str, Any]:
    """Persist a trained model reproducibly and return ``{"artifact_uri": ...}``.

    ``promote="production"`` (or ``"staging"``) promotes the registered version through
    the project's ``settings.mlops.promotion_policy``: a candidate the gate refuses
    stays where it is, and the result says why (``promoted_to: None``,
    ``promotion_refused``) — the node does not fail, so a retrain that is no better
    than production leaves production alone.

    ``metrics`` go to the model version *and*, with ``log_to_run`` (the default), to the
    tracked run, so ``ducta experiment show`` and a run summary can rank runs by them.
    Pass ``log_to_run=False`` when the caller has already logged them.

    ``native=True`` writes an xgboost or lightgbm model in the framework's own format
    (``.json`` / ``.txt``) instead of a pickle, so it can be scored without
    ``model.trust_artifact``. The scored model is then the framework's ``Booster``: for
    ``binary:logistic`` its ``predict`` returns probabilities, not the labels an sklearn
    wrapper's ``predict`` returns. Hence it is opt-in; any other model is pickled as before.
    """
    # The registry's own rule, checked before anything is written: the local copy
    # used the name as a folder unchecked, so "../x" wrote outside base_dir.
    name = validate_model_name(name)
    if promote:
        # Before registering: a misspelled stage left a version registered and the
        # node failed.
        _promotion_stage(promote)
    mlops_context = _ctx_get(ml_context, "mlops_context")
    run_id = _ctx_get(ml_context, "mlops_run_id")
    model_version = _ctx_get(ml_context, "model_version")
    registry = getattr(mlops_context, "model_registry", None) if mlops_context else None

    stamp = _version_stamp(run_id, model_version)

    if log_to_run:
        log_run_metrics(ml_context, metrics)

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

        # A registration that fails fails the node. It used to fall back to a local
        # pickle and succeed: the registry never got the model, and a serving node
        # kept scoring with the previous Production version. The local copy below is
        # for projects without a registry.
        with tempfile.TemporaryDirectory() as tmp:
            artifact, artifact_type, _ = _write_artifact(model, framework, native, Path(tmp), name)
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
            result: Dict[str, Any] = {
                "artifact_uri": version.artifact_uri,
                "version": version.version,
            }
            trial = _ctx_get(ml_context, "sweep_id")
            if promote and trial:
                logger.info(
                    "Model '{}' v{} is a trial of {}: registered, not promoted — promote "
                    "the best one with `ducta model promote`",
                    name,
                    version.version,
                    trial,
                )
                result.update({"promoted_to": None, "promotion_skipped": f"trial of {trial}"})
            elif promote:
                result.update(_promote(registry, mlops_context, name, version.version, promote))
            _record_registration(ml_context, name, version, result)
            return result

    if promote:
        logger.warning(
            "Model '{}' is not promoted to {}: there is no model registry (tracking is off)",
            name,
            promote,
        )
    dest_dir = Path(base_dir) / name / stamp
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest, _, serializer = _write_artifact(model, framework, native, dest_dir, "model")

    pointer = Path(base_dir) / name / "latest.txt"
    pointer.write_text(str(dest.resolve()), encoding="utf-8")

    logger.info("Persisted model '{}' to {} ({}); latest -> {}", name, dest, serializer, pointer)
    return {"artifact_uri": dest.resolve().as_uri(), "version": stamp}
