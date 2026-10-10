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

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional

from loguru import logger

from ducta.mlrun.baseline import compare_to_baseline, trivial_baseline_metrics
from ducta.mlrun.persistence import _ctx_get, persist_model
from ducta.mlrun.split import split_dataframe, tag_partitions

_TARGET = "__ducta_target__"
_FALLBACK_SEED = 42
_FALLBACK_SPLIT = {"method": "random", "test_size": 0.2}
_FALLBACK_CV_FOLDS = 5
_TASKS = ("classification", "regression")


@dataclass
class TrainResult:
    """What :func:`train_with_search` produced."""

    model: Any
    best_params: Dict[str, Any]
    cv_score: Optional[float]
    metrics: Dict[str, float]
    X_train: Any
    X_test: Any
    y_train: Any
    y_test: Any
    X_val: Any = None
    y_val: Any = None
    persisted: Optional[Dict[str, Any]] = field(default=None)

    def partition_frame(self, frame: Any, column: str = "split") -> Any:
        """``frame`` with a column saying which rows trained the model and which did not.

        ``frame`` must share the index of the ``X`` that was passed in (e.g. the DataFrame
        it was cut from, with predictions added).
        """
        parts = [self.X_train] + ([self.X_val] if self.X_val is not None else []) + [self.X_test]
        return tag_partitions(frame, *parts, column=column)

    def metrics_frame(self) -> Any:
        """The metrics as a one-row pandas DataFrame, the usual return value of a node."""
        import pandas as pd

        return pd.DataFrame([self.metrics])


def _plain(value: Any) -> Any:
    """numpy scalars to Python ones: the model registry rejects the former."""
    return value.item() if hasattr(value, "item") and getattr(value, "ndim", 1) == 0 else value


def _numeric(metrics: Mapping[str, Any]) -> Dict[str, float]:
    return {k: float(v) for k, v in metrics.items() if isinstance(v, (int, float))}


def _evaluate(model: Any, X_test: Any, y_test: Any, task: str) -> Dict[str, float]:
    from sklearn import metrics as skm

    predicted = model.predict(X_test)
    if task == "regression":
        import numpy as np

        return {
            "rmse": float(np.sqrt(skm.mean_squared_error(y_test, predicted))),
            "mae": float(skm.mean_absolute_error(y_test, predicted)),
            "r2": float(skm.r2_score(y_test, predicted)),
        }

    classes = sorted(set(y_test))
    average = "binary" if len(classes) <= 2 else "macro"
    out = {
        "accuracy": float(skm.accuracy_score(y_test, predicted)),
        "f1": float(skm.f1_score(y_test, predicted, average=average, zero_division=0)),
        "precision": float(
            skm.precision_score(y_test, predicted, average=average, zero_division=0)
        ),
        "recall": float(skm.recall_score(y_test, predicted, average=average, zero_division=0)),
    }
    if hasattr(model, "predict_proba") and len(classes) == 2:
        out["auc_roc"] = float(skm.roc_auc_score(y_test, model.predict_proba(X_test)[:, 1]))
    return out


def _build_searcher(estimator, param_grid, hp_cfg, scoring, cv, seed, task) -> Any:
    from sklearn.model_selection import GridSearchCV, KFold, RandomizedSearchCV, StratifiedKFold

    folds = (StratifiedKFold if task == "classification" else KFold)(
        n_splits=cv, shuffle=True, random_state=seed
    )
    algorithm = hp_cfg.algorithm if hp_cfg is not None else "grid"
    if algorithm == "bayesian":
        raise ValueError(
            "train_with_search runs grid and random searches inside the node; a 'bayesian' "
            "search drives whole runs, so use `ducta start --search` for it."
        )
    if algorithm == "random" and param_grid is None:
        return RandomizedSearchCV(
            estimator,
            param_distributions=hp_cfg.build_distributions(),
            n_iter=hp_cfg.n_trials,
            scoring=scoring,
            cv=folds,
            n_jobs=-1,
            random_state=seed,
        )
    return GridSearchCV(estimator, param_grid=param_grid, scoring=scoring, cv=folds, n_jobs=-1)


def _log_metrics(ml_context: Any, metrics: Mapping[str, float]) -> None:
    """Best-effort: record each metric on the run, if this run is tracked."""
    mlops = _ctx_get(ml_context, "mlops_context")
    run_id = _ctx_get(ml_context, "mlops_run_id")
    tracker = getattr(mlops, "experiment_tracker", None) if mlops else None
    if tracker is None or not run_id:
        return
    try:
        for key, value in metrics.items():
            tracker.log_metric(run_id, key, value)
    except Exception as error:  # noqa: BLE001 — tracking must not fail a training run
        logger.warning("Could not log metrics to run {}: {}", run_id, error)


def train_with_search(
    estimator: Any,
    X: Any,
    y: Any,
    ml_context: Any = None,
    *,
    task: str,
    scoring: Optional[str] = None,
    param_grid: Optional[Dict[str, Any]] = None,
    fit_params: Optional[Dict[str, Any]] = None,
    baseline_metric: Optional[str] = None,
    higher_is_better: Optional[bool] = None,
    min_delta: float = 0.0,
    extra_baselines: Optional[Dict[str, float]] = None,
    name: Optional[str] = None,
    framework: str = "sklearn",
    native: bool = False,
) -> TrainResult:
    """Split, search, evaluate, gate, track and (with ``name``) register one model."""
    if task not in _TASKS:
        raise ValueError(f"task must be one of {_TASKS}, got {task!r}")
    import pandas as pd

    hp_cfg = _ctx_get(ml_context, "hyperparams_config")
    seed = _ctx_get(ml_context, "node_seed") or _ctx_get(ml_context, "seed") or _FALLBACK_SEED
    cv = int(
        _ctx_get(ml_context, "cv_folds") or getattr(hp_cfg, "cv_folds", None) or _FALLBACK_CV_FOLDS
    )

    # ── split: the one the pipeline file declares ──────────────────────────────
    target = getattr(y, "name", None) or "target"
    if target in X.columns:
        raise ValueError(f"The target column '{target}' is also in X; drop it from the features")
    target_series = pd.Series(list(y), index=X.index, name=target) if not hasattr(y, "index") else y
    data = X.copy()
    data[target] = target_series.to_numpy()
    split = _ctx_get(ml_context, "split")
    if split is None and ml_context is None:
        split = _FALLBACK_SPLIT  # outside a Ducta run
    parts = split_dataframe(data, split, default_seed=seed, ml_context=ml_context)
    train_df, test_df = parts[0], parts[-1]
    val_df = parts[1] if len(parts) == 3 else None
    X_train, y_train = train_df.drop(columns=[target]), train_df[target]
    X_test, y_test = test_df.drop(columns=[target]), test_df[target]

    # ── search ─────────────────────────────────────────────────────────────────
    if isinstance(estimator, type):
        try:
            estimator = estimator(random_state=seed)
        except TypeError:
            estimator = estimator()
    objective = getattr(hp_cfg, "objective", None) or {}
    scoring = scoring or objective.get("metric") or None
    if param_grid is None and hp_cfg is not None and hp_cfg.search_space:
        if hp_cfg.algorithm == "grid":
            param_grid = hp_cfg.build_param_grid()
    if param_grid is not None or (hp_cfg is not None and hp_cfg.search_space):
        searcher = _build_searcher(estimator, param_grid, hp_cfg, scoring, cv, seed, task)
        searcher.fit(X_train, y_train, **(fit_params or {}))
        model, best_params = searcher.best_estimator_, dict(searcher.best_params_)
        cv_score = float(searcher.best_score_)
        logger.info("Best params: {} (CV {}={:.4f})", best_params, scoring or "score", cv_score)
    else:
        fixed = _ctx_get(ml_context, "hyperparams") or {}
        accepted = estimator.get_params() if hasattr(estimator, "get_params") else {}
        if fixed and accepted:
            estimator.set_params(**{k: v for k, v in fixed.items() if k in accepted})
        model = estimator.fit(X_train, y_train, **(fit_params or {}))
        best_params = {k: _plain(v) for k, v in fixed.items()}
        cv_score = None

    # ── evaluate, gate, track, register ────────────────────────────────────────
    metrics = _evaluate(model, X_test, y_test, task)
    if cv_score is not None:
        metrics["best_cv_score"] = cv_score
        if objective.get("metric") and objective["metric"] not in metrics:
            metrics[objective["metric"]] = cv_score

    if baseline_metric:
        baseline = trivial_baseline_metrics(y_test, task=task)
        baseline.update(extra_baselines or {})
        metrics.update(baseline)
        better_up = (
            higher_is_better
            if higher_is_better is not None
            else baseline_metric not in ("mae", "rmse", "mse")
        )
        passes, message = compare_to_baseline(
            metrics, baseline, baseline_metric, min_delta=min_delta, higher_is_better=better_up
        )
        logger.info("Baseline gate ({}): {}", baseline_metric, message)
        if not passes:
            raise ValueError(
                f"Baseline gate FAILED — model does not beat the trivial baseline: {message}"
            )

    _log_metrics(ml_context, _numeric(metrics))

    persisted = None
    if name:
        persisted = persist_model(
            model,
            ml_context,
            name,
            framework=framework,
            metrics=_numeric(metrics),
            hyperparameters={k: _plain(v) for k, v in best_params.items()},
            X=X_train,
            y=y_train,
            native=native,
        )

    return TrainResult(
        model=model,
        best_params=best_params,
        cv_score=cv_score,
        metrics=metrics,
        X_train=X_train,
        X_test=X_test,
        y_train=y_train,
        y_test=y_test,
        X_val=val_df.drop(columns=[target]) if val_df is not None else None,
        y_val=val_df[target] if val_df is not None else None,
        persisted=persisted,
    )
