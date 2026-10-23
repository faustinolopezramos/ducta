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

import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd
from loguru import logger  # type: ignore

from ducta.mlrun.persistence import _ctx_get

#: Columns every summary has, in this order, before the ``param_*`` and ``metric_*`` ones.
BASE_COLUMNS = [
    "run_id",
    "pipeline",
    "run_name",
    "status",
    "started_at",
    "duration_seconds",
    "sweep_id",
    "model_name",
    "model_version",
    "model_stage",
    "model_label",
    "artifact_sha256",
    "git_commit",
    "code_hash",
    "data_hash",
    "split_applied",
    "certificate_id",
    "certificate_ok",
]


def _stores(ml_context: Any, mlops_path: Optional[str]) -> Tuple[Any, Any]:
    """The experiment tracker and the model registry to read: the run's own, or the ones
    stored under ``mlops_path``."""
    mlops = _ctx_get(ml_context, "mlops_context")
    tracker = getattr(mlops, "experiment_tracker", None) if mlops else None
    registry = getattr(mlops, "model_registry", None) if mlops else None
    if tracker is not None and registry is not None:
        return tracker, registry
    if not mlops_path:
        raise ValueError(
            "run_summary needs the tracked run's ml_context, or the mlops_path where "
            "experiments and models are stored (settings.mlops_path)."
        )
    from ducta.mlrun.config import DEFAULT_REGISTRY_PATH, DEFAULT_TRACKING_PATH
    from ducta.mlrun.experiment_tracking import ExperimentTracker
    from ducta.mlrun.model_registry import ModelRegistry
    from ducta.mlrun.storage import LocalStorageBackend

    storage = LocalStorageBackend(base_path=mlops_path)
    return (
        ExperimentTracker(storage=storage, tracking_path=DEFAULT_TRACKING_PATH),
        ModelRegistry(storage=storage, registry_path=DEFAULT_REGISTRY_PATH),
    )


def _versions_by_run(registry: Any) -> Dict[str, Dict[str, Any]]:
    """Registered model versions keyed by the run that produced them (the latest wins)."""
    by_run: Dict[str, Dict[str, Any]] = {}
    try:
        models = registry.list_models()
    except Exception as error:  # noqa: BLE001 — a run table is useful without models
        logger.warning("Model registry unreadable, models left out of the run summary: {}", error)
        return by_run
    for model in models:
        try:
            versions = registry.list_model_versions(model["name"])
        except Exception as error:  # noqa: BLE001
            logger.warning("Versions of model '{}' unreadable: {}", model["name"], error)
            continue
        for version in sorted(versions, key=lambda v: v["version"]):
            run_id = version.get("experiment_run_id")
            if run_id:
                by_run[run_id] = {"name": model["name"], **version}
    return by_run


def _data_hash(raw: Any) -> Optional[str]:
    """One digest for all the inputs of a run, from the fingerprints it logged."""
    if not raw:
        return None
    try:
        fingerprints = json.loads(raw) if isinstance(raw, str) else raw
        parts = {
            key: (fp or {}).get("fingerprint")
            or (fp or {}).get("raw_file_hash")
            or (fp or {}).get("schema_hash")
            for key, fp in sorted(fingerprints.items())
        }
    except (TypeError, ValueError, AttributeError):
        return None
    digest = hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()
    return f"sha256:{digest}"


def _certificate_ok(
    certificates_dir: Optional[str], certificate_id: Optional[str]
) -> Optional[bool]:
    """Whether the run's certificate is on disk and unaltered; ``None`` if not checked."""
    if not certificates_dir or not certificate_id:
        return None
    from ducta.core.certificate import find_certificate_dir, verify_certificate

    run_dir = find_certificate_dir(Path(certificates_dir), certificate_id)
    if run_dir is None:
        return False
    return bool(verify_certificate(run_dir / "certificate.json").ok)


#: Given a certificate id, whether that certificate exists and is unaltered; ``None`` if unknown.
CertificateCheck = Callable[[str], Optional[bool]]


def _row(
    pipeline: str,
    run: Any,
    version: Optional[Dict[str, Any]],
    certificates_dir: Optional[str],
    certificate_check: Optional[CertificateCheck] = None,
) -> Dict[str, Any]:
    params = dict(run.parameters or {})
    tags = dict(run.tags or {})
    metrics: Dict[str, Any] = {}
    for key in run.metrics:
        latest = run.metric_index.get_latest(key)
        if latest is not None:
            metrics[key] = latest.value
    # A run logged before metrics went to the run itself: take them from its model.
    for key, value in ((version or {}).get("metrics") or {}).items():
        if key not in metrics and isinstance(value, (int, float)) and not isinstance(value, bool):
            metrics[key] = value

    split_applied = params.get("_split_applied")
    certificate_id = tags.get("ducta_run_id")
    row: Dict[str, Any] = {
        "run_id": run.run_id,
        "pipeline": pipeline,
        "run_name": run.name,
        "status": run.status.value,
        "started_at": run.start_time or run.created_at,
        "duration_seconds": run.duration_seconds,
        "sweep_id": tags.get("sweep_id") or params.get("sweep_id"),
        "model_name": (version or {}).get("name"),
        "model_version": (version or {}).get("version"),
        "model_stage": (version or {}).get("stage"),
        "model_label": tags.get("model_version"),
        "artifact_sha256": (version or {}).get("artifact_sha256"),
        "git_commit": tags.get("git_commit"),
        "code_hash": params.get("_code_hash"),
        "data_hash": _data_hash(params.get("_input_fingerprints")),
        "split_applied": None if split_applied is None else str(split_applied) == "true",
        "certificate_id": certificate_id,
        "certificate_ok": (
            certificate_check(certificate_id)
            if certificate_check is not None and certificate_id
            else _certificate_ok(certificates_dir, certificate_id)
        ),
    }
    for key, value in params.items():
        if not key.startswith("_"):
            row[f"param_{key}"] = value
    for key, value in metrics.items():
        row[f"metric_{key}"] = value
    return row


def _normalise(frame: pd.DataFrame) -> pd.DataFrame:
    """Make every column one type, so the table can be written as parquet or Delta.

    A column with no value in any run (a certificate nobody checked) has no type, and Spark
    refuses to infer one: it is left out. A hyperparameter that is a number in one run and
    a word in another (``max_depth`` 6 and ``None``) would be an ``object`` column no
    columnar format accepts: it becomes text. A version stays a whole number.
    """
    frame = frame.dropna(axis="columns", how="all").copy()
    for column in [c for c in frame.columns if c.startswith("param_")]:
        values = frame[column].dropna()
        numeric = all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values)
        boolean = all(isinstance(v, bool) for v in values)
        if not (numeric or boolean):
            frame[column] = frame[column].map(lambda v: None if pd.isna(v) else str(v))
    if "model_version" in frame.columns:
        frame["model_version"] = [None if pd.isna(v) else int(v) for v in frame["model_version"]]
        frame["model_version"] = frame["model_version"].astype(object)
    return frame


def run_summary(
    ml_context: Any = None,
    *,
    pipeline: Optional[str] = None,
    mlops_path: Optional[str] = None,
    certificates_dir: Optional[str] = None,
    certificate_check: Optional[CertificateCheck] = None,
    sort_by: Optional[str] = None,
    ascending: bool = False,
) -> pd.DataFrame:
    """One row per tracked run, joined with the model it registered and its certificate.

    Reads the experiment tracker, the model registry and, when ``certificates_dir`` is
    given, checks each run's certificate. Returns a pandas DataFrame with the columns of
    :data:`BASE_COLUMNS`, then the run's hyperparameters as ``param_<name>`` and its final
    metrics as ``metric_<name>``. A column no run has a value for is left out. A node returns
    it and Ducta writes it where the catalog says (parquet, Delta, CSV...).

    Args:
        ml_context: The ``ml_context`` of an ML node; its tracker and registry are read.
        pipeline: Only the runs of this pipeline (its experiment). All, when omitted.
        mlops_path: Where experiments and models are stored, for use outside a pipeline.
        certificates_dir: The runs directory of the certificates, to fill
            ``certificate_ok``. Left ``None``, that column is empty.
        certificate_check: Looks a certificate up by id and says whether it is intact, for
            callers that know more places to look than one directory (the API). Takes
            precedence over ``certificates_dir``.
        sort_by: Column to order by; newest first when omitted.
        ascending: Direction for ``sort_by``.
    """
    tracker, registry = _stores(ml_context, mlops_path)
    versions = _versions_by_run(registry)

    experiments: List[Dict[str, Any]] = tracker.list_experiments()
    if pipeline is not None:
        known = [e["name"] for e in experiments]
        experiments = [e for e in experiments if e["name"] == pipeline]
        if not experiments:
            logger.warning(
                "No experiment named '{}' in this tracking store (found: {}). A pipeline "
                "reads another's runs only when both share settings.mlops_path.",
                pipeline,
                ", ".join(known) or "none",
            )

    rows = []
    for experiment in experiments:
        for item in tracker.list_runs(experiment["experiment_id"]):
            try:
                run = tracker.get_run(item["run_id"])
            except Exception as error:  # noqa: BLE001 — one unreadable run must not hide the rest
                logger.warning("Run {} left out of the summary: {}", item["run_id"], error)
                continue
            rows.append(
                _row(
                    experiment["name"],
                    run,
                    versions.get(run.run_id),
                    certificates_dir,
                    certificate_check,
                )
            )

    frame = pd.DataFrame(rows, columns=None if rows else BASE_COLUMNS)
    if frame.empty:
        return frame
    frame = _normalise(frame)

    leading = [c for c in BASE_COLUMNS if c in frame.columns]
    params = sorted(c for c in frame.columns if c.startswith("param_"))
    metrics = sorted(c for c in frame.columns if c.startswith("metric_"))
    frame = frame[leading + params + metrics]

    if sort_by is not None:
        if sort_by not in frame.columns:
            raise ValueError(f"Cannot sort by '{sort_by}'. Columns: {', '.join(frame.columns)}")
        return frame.sort_values(sort_by, ascending=ascending).reset_index(drop=True)
    return frame.sort_values("started_at", ascending=False).reset_index(drop=True)
