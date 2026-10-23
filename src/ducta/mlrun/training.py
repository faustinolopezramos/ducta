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
from typing import Any, Dict, Mapping, Optional, Tuple

from loguru import logger

from ducta.mlrun.baseline import compare_to_baseline, trivial_baseline_metrics
from ducta.mlrun.persistence import _ctx_get, log_run_metrics, log_run_params, persist_model
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


def _pin(space: Any, pinned: Mapping[str, Any]) -> Any:
    """``space`` (a grid, or the sub-grids of conditional parameters, or distributions)
    with every pinned parameter reduced to its one given value."""
    if isinstance(space, list):
        return [_pin(sub, pinned) for sub in space]
    return {name: ([pinned[name]] if name in pinned else values) for name, values in space.items()}


def _plan_search(hp_cfg, param_grid, pinned: Mapping[str, Any]) -> Tuple[Any, Any]:
    """The ``(param_grid, distributions)`` this run searches, with pinned values fixed.

    A value the run was explicitly given (``--hyperparams``, a ``--sweep`` or ``--search``
    trial) is not searched: the search inside the node covers only the rest. When the run
    pins every parameter of the search space, that is a search of one point: it still
    cross-validates it, so the run reports the score a search over it would.
    """
    if param_grid is not None:
        return _pin(param_grid, pinned), None
    if hp_cfg is None or not hp_cfg.search_space:
        return None, None
    if set(hp_cfg.search_space) <= set(pinned):
        # Not built from the config: a bayesian space may hold ranges, not a grid.
        return {name: [pinned[name]] for name in hp_cfg.search_space}, None
    algorithm = hp_cfg.algorithm
    if algorithm == "grid":
        return _pin(hp_cfg.build_param_grid(), pinned), None
    if algorithm == "random":
        return None, _pin(hp_cfg.build_distributions(), pinned)
    return None, None  # bayesian with free parameters: _build_searcher says what to do


def _build_searcher(estimator, param_grid, distributions, hp_cfg, scoring, cv, seed, task) -> Any:
    from sklearn.model_selection import GridSearchCV, KFold, RandomizedSearchCV, StratifiedKFold

    folds = (StratifiedKFold if task == "classification" else KFold)(
        n_splits=cv, shuffle=True, random_state=seed
    )
    if param_grid is None and distributions is None:
        raise ValueError(
            "train_with_search runs grid and random searches inside the node; a 'bayesian' "
            "search drives whole runs, so use `ducta start --search` for it. (Under "
            "`--search` every parameter of the search space is fixed by the trial, so this "
            "message means some are not: check that the space and the search agree.)"
        )
    if distributions is not None:
        return RandomizedSearchCV(
            estimator,
            param_distributions=distributions,
            n_iter=hp_cfg.n_trials,
            scoring=scoring,
            cv=folds,
            n_jobs=-1,
            random_state=seed,
        )
    return GridSearchCV(estimator, param_grid=param_grid, scoring=scoring, cv=folds, n_jobs=-1)


def _log_metrics(ml_context: Any, metrics: Mapping[str, float]) -> None:
    """Best-effort: record each metric on the run, if this run is tracked."""
    log_run_metrics(ml_context, metrics)


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
    accepted = estimator.get_params() if hasattr(estimator, "get_params") else {}
    pinned = {
        k: v for k, v in (_ctx_get(ml_context, "cli_hyperparams") or {}).items() if k in accepted
    }
    param_grid, distributions = _plan_search(hp_cfg, param_grid, pinned)
    bayesian_free = hp_cfg is not None and hp_cfg.search_space and hp_cfg.algorithm == "bayesian"
    if param_grid is not None or distributions is not None or bayesian_free:
        if pinned:
            estimator.set_params(**pinned)
        searcher = _build_searcher(
            estimator, param_grid, distributions, hp_cfg, scoring, cv, seed, task
        )
        searcher.fit(X_train, y_train, **(fit_params or {}))
        model = searcher.best_estimator_
        # What the model really is: the search's winner, and the values it was given.
        best_params = {**{k: _plain(v) for k, v in pinned.items()}, **dict(searcher.best_params_)}
        cv_score = float(searcher.best_score_)
        logger.info("Best params: {} (CV {}={:.4f})", best_params, scoring or "score", cv_score)
    else:
        fixed = _ctx_get(ml_context, "hyperparams") or {}
        if fixed and accepted:
            estimator.set_params(**{k: v for k, v in fixed.items() if k in accepted})
        model = estimator.fit(X_train, y_train, **(fit_params or {}))
        best_params = {k: _plain(v) for k, v in fixed.items()}
        cv_score = None

    # The values the model really has, on the run as well as on the model it registers:
    # a run table or `ducta experiment compare` reads hyperparameters from the run.
    log_run_params(ml_context, {k: _plain(v) for k, v in best_params.items()})

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
            log_to_run=False,  # logged just above
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
