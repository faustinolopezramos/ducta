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
from typing import Any, Dict, Optional, Tuple

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


def _require_pandas(df: Any) -> None:
    """Reject non-pandas inputs with an actionable message.

    All split strategies rely on pandas semantics (``sort_values``, ``.iloc``,
    boolean masks, ``value_counts``). A Spark DataFrame would otherwise fail
    deep inside with an opaque ``AttributeError``, so fail loudly and early.
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
) -> Tuple[Any, ...]:
    """Split a pandas DataFrame according to a declarative split config.

    Returns ``(train, test)``, or ``(train, val, test)`` when ``val_size`` is
    set. Rows are never shuffled across the temporal boundary, and with
    ``method='group'`` all rows of an entity land on the same side.
    """
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
        # All rows of an entity share one hash, so the entity lands entirely on
        # one side. The fraction is over groups, not rows.
        group_col = _require_column(df, cfg.get("group_col"), method, "group_col")
        fractions = df[group_col].map(lambda v: _stable_fraction(v, seed))
    elif method == "stratified":
        # Per-class percentile rank of per-row random values: every class
        # contributes ~test_size of its rows, preserving class balance.
        stratify_col = _require_column(df, cfg.get("stratify_col"), method, "stratify_col")
        # A 1-row class gets percentile 1.0 and would always land entirely in
        # test, so train would never see it. Fail loudly like sklearn does.
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

    ``method='group'`` has no per-class minimum-count guard the way
    ``stratified`` does, so with too few distinct groups (or one dominant
    group) the fraction-based masks can silently produce an empty train/val/test
    partition. Applied to every method as a general safety net.
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
