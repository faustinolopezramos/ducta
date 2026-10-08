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
    """Best-effort: set split_applied=True on ml_context, whatever its shape."""
    if ml_context is None:
        return
    try:
        if isinstance(ml_context, MutableMapping):
            ml_context["split_applied"] = True
        else:
            setattr(ml_context, "split_applied", True)
    except Exception as e:  # noqa: BLE001 — marking the flag is best-effort
        logger.debug("Could not mark split_applied on ml_context: {}", e)


def _require_pandas(df: Any, caller: str = "split_dataframe") -> None:
    """Reject inputs that are neither pandas nor (where supported) Spark."""
    if hasattr(df, "iloc") and hasattr(df, "columns"):
        return
    type_name = f"{type(df).__module__}.{type(df).__name__}"
    if _is_spark(df):
        raise SplitError(
            f"{caller} operates on pandas DataFrames, but received a Spark DataFrame "
            f"({type_name}). Collect it with .toPandas() first (e.g. inside a vectorized "
            "node); split_dataframe itself accepts a Spark DataFrame."
        )
    raise SplitError(f"{caller} expects a pandas or Spark DataFrame, got {type_name}.")


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
    """Split a pandas or Spark DataFrame according to a declarative split config.

    Returns ``(train, test)``, or ``(train, val, test)`` with ``val_size``. A Spark
    DataFrame is split without being collected (see :func:`_split_spark`).
    """
    parts = _split_dataframe_impl(df, split_config, default_seed)
    _mark_split_applied(ml_context)
    return parts


def _is_spark(df: Any) -> bool:
    type_name = f"{type(df).__module__}.{type(df).__name__}"
    return "pyspark" in type_name or (hasattr(df, "sparkSession") and hasattr(df, "schema"))


def _split_dataframe_impl(
    df: Any,
    split_config: Any,
    default_seed: Optional[int] = None,
) -> Tuple[Any, ...]:
    spark = _is_spark(df)
    if not spark:
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

    seed = _resolve_seed(cfg, default_seed, "split_dataframe")

    holdout = test_size + (val_size or 0.0)

    if spark:
        return _split_spark(df, cfg, method, seed, test_size, val_size)

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

    def _stratified_error(count: int, shown: Dict[str, int]) -> str:
        return (
            f"Stratified split requires at least 2 rows per class; "
            f"{count} class(es) have fewer: {shown}. "
            "Drop or merge these classes, or use method='random'."
        )

    fractions = _compute_fractions(
        df, cfg, method, seed, min_rows_per_class=2, stratified_error=_stratified_error
    )

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


_PART = "__ducta_split_part"
_FRACTION = "__ducta_split_fraction"


def _split_spark(
    df: Any,
    cfg: Dict[str, Any],
    method: str,
    seed: int,
    test_size: float,
    val_size: Optional[float],
) -> Tuple[Any, ...]:
    """The same declarative split on a Spark DataFrame, without collecting it.

    ``random`` and ``group`` assign rows by a hash of their content (or group)
    and the seed, so the assignment does not depend on how the data is
    partitioned; ``stratified`` takes exactly ``test_size`` of each class;
    ``temporal`` cuts at the time column's quantiles. Same proportions and
    guarantees as the pandas path — not the same rows, since the hashes differ.
    """
    from pyspark.sql import Window
    from pyspark.sql import functions as F

    holdout = test_size + (val_size or 0.0)

    def _hash_fraction(*cols: Any) -> Any:
        return F.pmod(F.xxhash64(F.lit(seed), *cols), F.lit(2**31)) / F.lit(float(2**31))

    if method == "temporal":
        time_col = _require_column(df, cfg.get("time_col"), method, "time_col")
        dtype = dict(df.dtypes)[time_col]
        as_number = (
            F.unix_timestamp(F.col(time_col))
            if dtype in ("date", "timestamp", "timestamp_ntz")
            else F.col(time_col).cast("double")
        )
        probs = [1 - holdout] + ([1 - test_size] if val_size is not None else [])
        cuts = df.select(as_number.alias(_FRACTION)).approxQuantile(_FRACTION, probs, 1e-4)
        if len(cuts) < len(probs):
            raise SplitError(f"split.method='temporal': '{time_col}' has no values to cut on")
        part = F.when(as_number < cuts[0], F.lit("train"))
        if val_size is not None:
            part = part.when(as_number < cuts[1], F.lit("val"))
        labeled = df.withColumn(_PART, part.otherwise(F.lit("test")))
    else:
        if method == "group":
            group_col = _require_column(df, cfg.get("group_col"), method, "group_col")
            fraction = _hash_fraction(F.col(group_col))
        elif method == "stratified":
            stratify_col = _require_column(df, cfg.get("stratify_col"), method, "stratify_col")
            small = df.groupBy(stratify_col).count().filter(F.col("count") < 2).limit(10).collect()
            if small:
                shown = {str(r[stratify_col]): int(r["count"]) for r in small}
                raise SplitError(
                    f"Stratified split requires at least 2 rows per class; {len(shown)} "
                    f"class(es) have fewer: {shown}. Drop or merge these classes, or use "
                    "method='random'."
                )
            window = Window.partitionBy(stratify_col).orderBy(_hash_fraction(*df.columns))
            fraction = F.percent_rank().over(window)
        else:  # random
            fraction = _hash_fraction(*df.columns)
        part = F.when(fraction >= F.lit(1 - test_size), F.lit("test"))
        if val_size is not None:
            part = part.when(fraction >= F.lit(1 - holdout), F.lit("val"))
        labeled = df.withColumn(_PART, part.otherwise(F.lit("train")))

    names = ("train", "val", "test") if val_size is not None else ("train", "test")
    counts = {r[_PART]: r["count"] for r in labeled.groupBy(_PART).count().collect()}
    sizes = [counts.get(name, 0) for name in names]
    if sum(sizes) >= 2 and 0 in sizes:
        empty = ", ".join(n for n, size in zip(names, sizes) if size == 0)
        raise SplitError(
            f"split.method='{method}' produced an empty partition ({empty}) — too few "
            "distinct groups/classes (or too skewed a distribution) for the requested "
            "test_size/val_size. Use a larger dataset, adjust the split sizes, or "
            "merge/drop rare groups."
        )
    return tuple(labeled.filter(F.col(_PART) == name).drop(_PART) for name in names)


def _check_non_degenerate(parts: Tuple[Any, ...], n: int, method: str) -> None:
    """Reject a split where a requested partition ends up with 0 rows."""
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


def _resolve_seed(cfg: Dict[str, Any], default_seed: Optional[int], caller_name: str) -> int:
    """Resolve the effective seed for a split/fold call, warning and falling
    back to 42 if none was configured. Shared by ``_split_dataframe_impl`` and
    ``_kfold_splits_impl``, which previously carried this block twice,
    identical apart from ``caller_name`` in the warning text.
    """
    seed = cfg.get("seed")
    seed = default_seed if seed is None else seed
    if seed is None:
        seed = 42
        logger.warning(
            "{} called without a seed (config or default): using 42. "
            "Set global_config.random_seed for explicit reproducibility.",
            caller_name,
        )
    return seed


def _compute_fractions(
    df: Any,
    cfg: Dict[str, Any],
    method: str,
    seed: int,
    *,
    min_rows_per_class: int,
    stratified_error: Callable[[int, Dict[str, int]], str],
):
    """Per-row ``[0, 1)`` fraction used to assign rows to train/val/test (or a
    fold), for the ``group``/``stratified``/``random`` methods — ``temporal``
    is handled separately by each caller since its cut-point arithmetic
    differs between a single split and k folds.

    Shared by ``_split_dataframe_impl`` and ``_kfold_splits_impl``, which
    previously carried this block twice, identical apart from the stratified
    class-size threshold (``2`` vs ``n_splits``) and its error message.
    ``stratified_error(count, shown)`` builds that caller-specific message.
    """
    if method == "group":
        group_col = _require_column(df, cfg.get("group_col"), method, "group_col")
        group_lookup = {v: _stable_fraction(v, seed) for v in df[group_col].unique()}
        return df[group_col].map(group_lookup)

    if method == "stratified":
        stratify_col = _require_column(df, cfg.get("stratify_col"), method, "stratify_col")
        class_counts = df[stratify_col].value_counts()
        too_small = class_counts[class_counts < min_rows_per_class]
        if not too_small.empty:
            shown = {str(k): int(v) for k, v in too_small.head(10).items()}
            raise SplitError(stratified_error(len(too_small), shown))
        return (
            _row_fractions(df, seed).groupby(df[stratify_col].values).rank(pct=True, method="first")
        )

    return _row_fractions(df, seed).rank(pct=True, method="first")  # random


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
    _require_pandas(df, "kfold_splits")
    cfg = _normalize_config(split_config) if split_config is not None else {"method": "random"}

    method = cfg.get("method", "random")
    if method not in VALID_METHODS:
        raise SplitError(f"Unknown split method '{method}'. Valid: {VALID_METHODS}")

    n_splits = int(n_splits)
    if n_splits < 2:
        raise SplitError(f"n_splits must be at least 2, got {n_splits}")
    if len(df) < n_splits:
        raise SplitError(
            f"Cannot build {n_splits} folds from {len(df)} row(s): use fewer folds or more data."
        )

    seed = _resolve_seed(cfg, default_seed, "kfold_splits")

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

    def _stratified_error(count: int, shown: Dict[str, int]) -> str:
        return (
            f"Stratified {n_splits}-fold requires at least {n_splits} rows per class; "
            f"{count} class(es) have fewer: {shown}. "
            "Use fewer folds, merge/drop rare classes, or method='random'."
        )

    fractions = _compute_fractions(
        df, cfg, method, seed, min_rows_per_class=n_splits, stratified_error=_stratified_error
    )

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
    """Run k-fold CV using ml_context's declared split/cv_folds/node_seed."""
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
