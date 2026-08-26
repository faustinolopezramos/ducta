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

import hashlib
from collections.abc import MutableMapping
from typing import Any, Callable, Dict, List, Optional, Tuple

from loguru import logger

VALID_METHODS = ("random", "stratified", "temporal", "group")


class SplitError(ValueError):
    """Raised when a declarative split cannot be applied."""


def _normalize_config(split_config: Any) -> Dict[str, Any]:
    """Accept a SplitConfig model, a plain dict, or None."""
    if split_config is None:
        raise SplitError("No split configuration provided (ml_context['split'] is empty)")
    if hasattr(split_config, "model_dump"):
        return split_config.model_dump()
    if isinstance(split_config, dict):
        return dict(split_config)
    raise SplitError(f"Unsupported split config type: {type(split_config)}")


def _mark_split_applied(ml_context: Any) -> None:
    """Best-effort: set split_applied=True on ml_context, whatever its shape.
    """
    if ml_context is None:
        return
    try:
        if isinstance(ml_context, MutableMapping):
            ml_context["split_applied"] = True
        else:
            setattr(ml_context, "split_applied", True)
    except Exception as e:  # noqa: BLE001 — marking the flag is best-effort
        logger.debug("Could not mark split_applied on ml_context: {}", e)


def _require_pandas(df: Any) -> None:
    """Reject non-pandas inputs with an actionable message.
    """
    if hasattr(df, "iloc") and hasattr(df, "columns"):
        return
    type_name = f"{type(df).__module__}.{type(df).__name__}"
    if "pyspark" in type_name or hasattr(df, "sparkSession") or hasattr(df, "rdd"):
        raise SplitError(
            "split_dataframe operates on pandas DataFrames, but received a Spark "
            f"DataFrame ({type_name}). Collect it with .toPandas() before splitting "
            "(e.g. inside a vectorized node), or split with Spark's randomSplit/"
            "filter before handing rows to the node."
        )
    raise SplitError(
        f"split_dataframe expects a pandas DataFrame, got {type_name}. "
        "Provide a pandas DataFrame (use .toPandas() for Spark)."
    )


def _require_column(df: Any, column: Optional[str], method: str, key: str) -> str:
    if not column:
        raise SplitError(f"split.method='{method}' requires '{key}'")
    if column not in df.columns:
        raise SplitError(f"Split column '{column}' not found in DataFrame")
    return column


def _stable_fraction(value: Any, seed: int) -> float:
    """Deterministic hash of a value to [0, 1), stable across runs/processes."""
    digest = hashlib.sha256(f"{seed}:{value}".encode()).hexdigest()
    return int(digest[:12], 16) / float(16**12)


def split_dataframe(
    df: Any,
    split_config: Any,
    default_seed: Optional[int] = None,
    ml_context: Any = None,
) -> Tuple[Any, ...]:
    """Split a pandas DataFrame according to a declarative split config.
    """
    parts = _split_dataframe_impl(df, split_config, default_seed)
    _mark_split_applied(ml_context)
    return parts


def _split_dataframe_impl(
    df: Any,
    split_config: Any,
    default_seed: Optional[int] = None,
) -> Tuple[Any, ...]:
    _require_pandas(df)
    cfg = _normalize_config(split_config)

    method = cfg.get("method", "random")
    if method not in VALID_METHODS:
        raise SplitError(f"Unknown split method '{method}'. Valid: {VALID_METHODS}")

    test_size = float(cfg.get("test_size", 0.2))
    val_size = cfg.get("val_size")
    val_size = float(val_size) if val_size is not None else None
    if not 0 < test_size < 1:
        raise SplitError(f"test_size must be in (0, 1), got {test_size}")
    if val_size is not None and val_size < 0:
        raise SplitError(f"val_size must be >= 0, got {val_size}")
    if val_size is not None and val_size + test_size >= 1:
        raise SplitError("val_size + test_size must be < 1")

    seed = cfg.get("seed")
    seed = default_seed if seed is None else seed
    if seed is None:
        seed = 42
        logger.warning(
            "split_dataframe called without a seed (config or default): using 42. "
            "Set global_settings.random_seed for explicit reproducibility."
        )

    holdout = test_size + (val_size or 0.0)

    if method == "temporal":
        time_col = _require_column(df, cfg.get("time_col"), method, "time_col")
        ordered = df.sort_values(time_col, kind="mergesort")
        n = len(ordered)
        cut_train = int(round(n * (1 - holdout)))
        if val_size is not None:
            cut_val = int(round(n * (1 - test_size)))
            parts = (
                ordered.iloc[:cut_train],
                ordered.iloc[cut_train:cut_val],
                ordered.iloc[cut_val:],
            )
            _check_non_degenerate(parts, n, method)
            return parts
        parts = (ordered.iloc[:cut_train], ordered.iloc[cut_train:])
        _check_non_degenerate(parts, n, method)
        return parts

    if method == "group":
        group_col = _require_column(df, cfg.get("group_col"), method, "group_col")
        group_lookup = {v: _stable_fraction(v, seed) for v in df[group_col].unique()}
        fractions = df[group_col].map(group_lookup)
    elif method == "stratified":
        stratify_col = _require_column(df, cfg.get("stratify_col"), method, "stratify_col")
        class_counts = df[stratify_col].value_counts()
        singletons = class_counts[class_counts < 2]
        if not singletons.empty:
            shown = {str(k): int(v) for k, v in singletons.head(10).items()}
            raise SplitError(
                f"Stratified split requires at least 2 rows per class; "
                f"{len(singletons)} class(es) have fewer: {shown}. "
                "Drop or merge these classes, or use method='random'."
            )
        fractions = (
            _row_fractions(df, seed).groupby(df[stratify_col].values).rank(pct=True, method="first")
        )
    else:  # random
        fractions = _row_fractions(df, seed).rank(pct=True, method="first")

    test_mask = fractions > (1 - test_size)
    if val_size is not None:
        val_mask = (fractions > (1 - holdout)) & ~test_mask
        train_mask = ~test_mask & ~val_mask
        parts = (df[train_mask], df[val_mask], df[test_mask])
        _check_non_degenerate(parts, len(df), method)
        return parts
    parts = (df[~test_mask], df[test_mask])
    _check_non_degenerate(parts, len(df), method)
    return parts


def _check_non_degenerate(parts: Tuple[Any, ...], n: int, method: str) -> None:
    """Reject a split where a requested partition ends up with 0 rows.
    """
    if n < 2:
        return
    empty = [i for i, part in enumerate(parts) if len(part) == 0]
    if empty:
        names = ["train", "val", "test"] if len(parts) == 3 else ["train", "test"]
        empty_names = ", ".join(names[i] for i in empty)
        raise SplitError(
            f"split.method='{method}' produced an empty partition ({empty_names}) — "
            "too few distinct groups/classes (or too skewed a distribution) for the "
            "requested test_size/val_size. Use a larger dataset, adjust the split "
            "sizes, or merge/drop rare groups."
        )


def _row_fractions(df: Any, seed: int):
    """Deterministic pseudo-random value per row as a pandas Series."""
    import numpy as np
    import pandas as pd

    rng = np.random.default_rng(seed)
    return pd.Series(rng.random(len(df)), index=df.index)


def kfold_splits(
    df: Any,
    split_config: Any = None,
    n_splits: int = 5,
    default_seed: Optional[int] = None,
    ml_context: Any = None,
) -> List[Tuple[Any, Any]]:
    """Yield ``n_splits`` ``(train, validation)`` folds using the same
    declarative semantics as :func:`split_dataframe`.
    """
    folds = _kfold_splits_impl(df, split_config, n_splits, default_seed)
    _mark_split_applied(ml_context)
    return folds


def _kfold_splits_impl(
    df: Any,
    split_config: Any = None,
    n_splits: int = 5,
    default_seed: Optional[int] = None,
) -> List[Tuple[Any, Any]]:
    _require_pandas(df)
    cfg = _normalize_config(split_config) if split_config is not None else {"method": "random"}

    method = cfg.get("method", "random")
    if method not in VALID_METHODS:
        raise SplitError(f"Unknown split method '{method}'. Valid: {VALID_METHODS}")

    n_splits = int(n_splits)
    if n_splits < 2:
        raise SplitError(f"n_splits must be at least 2, got {n_splits}")
    if len(df) < n_splits:
        raise SplitError(
            f"Cannot build {n_splits} folds from {len(df)} row(s): "
            "use fewer folds or more data."
        )

    seed = cfg.get("seed")
    seed = default_seed if seed is None else seed
    if seed is None:
        seed = 42
        logger.warning(
            "kfold_splits called without a seed (config or default): using 42. "
            "Set global_settings.random_seed for explicit reproducibility."
        )

    if method == "temporal":
        time_col = _require_column(df, cfg.get("time_col"), method, "time_col")
        ordered = df.sort_values(time_col, kind="mergesort")
        n = len(ordered)
        bounds = [int(round(n * i / (n_splits + 1))) for i in range(n_splits + 2)]
        folds: List[Tuple[Any, Any]] = []
        for i in range(1, n_splits + 1):
            train_part = ordered.iloc[: bounds[i]]
            val_part = ordered.iloc[bounds[i] : bounds[i + 1]]
            if len(train_part) == 0 or len(val_part) == 0:
                raise SplitError(
                    f"temporal cross-validation produced an empty fold {i} from {n} rows "
                    f"with n_splits={n_splits}: use fewer folds or more data."
                )
            folds.append((train_part, val_part))
        return folds

    if method == "group":
        group_col = _require_column(df, cfg.get("group_col"), method, "group_col")
        group_lookup = {v: _stable_fraction(v, seed) for v in df[group_col].unique()}
        fractions = df[group_col].map(group_lookup)
    elif method == "stratified":
        stratify_col = _require_column(df, cfg.get("stratify_col"), method, "stratify_col")
        class_counts = df[stratify_col].value_counts()
        too_small = class_counts[class_counts < n_splits]
        if not too_small.empty:
            shown = {str(k): int(v) for k, v in too_small.head(10).items()}
            raise SplitError(
                f"Stratified {n_splits}-fold requires at least {n_splits} rows per class; "
                f"{len(too_small)} class(es) have fewer: {shown}. "
                "Use fewer folds, merge/drop rare classes, or method='random'."
            )
        fractions = (
            _row_fractions(df, seed).groupby(df[stratify_col].values).rank(pct=True, method="first")
        )
    else:  # random
        fractions = _row_fractions(df, seed).rank(pct=True, method="first")

    fold_ids = (fractions * n_splits).astype(int).clip(upper=n_splits - 1)

    folds = []
    for fold in range(n_splits):
        val_mask = fold_ids == fold
        train_part, val_part = df[~val_mask], df[val_mask]
        if len(train_part) == 0 or len(val_part) == 0:
            raise SplitError(
                f"split.method='{method}' produced an empty fold {fold} "
                f"(n_splits={n_splits}, rows={len(df)}) — too few distinct "
                "groups/classes for this many folds."
            )
        folds.append((train_part, val_part))
    return folds


def cross_validate(
    fit: Callable[[Any, Any], Any],
    score: Callable[[Any, Any, Any], float],
    ml_context: Any,
    df: Any = None,
    n_splits: Optional[int] = None,
    metric_name: str = "score",
) -> Dict[str, float]:
    """Run k-fold CV using ml_context's declared split/cv_folds/node_seed.
    """
    from ducta.mlrun.persistence import _ctx_get

    if df is None:
        raise SplitError(
            "cross_validate requires df: pass the dataset to fold (ml_context "
            "does not carry the raw dataframe)."
        )

    split_config = _ctx_get(ml_context, "split")
    cv_folds = _ctx_get(ml_context, "cv_folds") or 5
    node_seed = _ctx_get(ml_context, "node_seed")
    resolved_n_splits = n_splits or cv_folds

    folds = kfold_splits(df, split_config, n_splits=resolved_n_splits, default_seed=node_seed)

    scores: List[float] = []
    for train_df, val_df in folds:
        model = fit(train_df, val_df)
        scores.append(float(score(model, val_df, val_df)))

    mean = sum(scores) / len(scores)
    variance = sum((s - mean) ** 2 for s in scores) / len(scores)
    std = variance**0.5

    result = {
        f"{metric_name}_mean": mean,
        f"{metric_name}_std": std,
        f"{metric_name}_folds": scores,
    }

    mlops_context = _ctx_get(ml_context, "mlops_context")
    mlops_run_id = _ctx_get(ml_context, "mlops_run_id")
    if mlops_context is not None and mlops_run_id:
        try:
            tracker = mlops_context.experiment_tracker
            tracker.log_metric(mlops_run_id, f"{metric_name}_mean", mean)
            tracker.log_metric(mlops_run_id, f"{metric_name}_std", std)
        except Exception as e:  # noqa: BLE001 — logging the summary is best-effort
            logger.warning("cross_validate could not log metrics: {}", e)

    return result
