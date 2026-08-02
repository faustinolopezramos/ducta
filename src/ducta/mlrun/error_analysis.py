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

from typing import Any, Dict, List, Optional

from loguru import logger

VALID_TASKS = ("classification", "regression")


def _is_binary(values) -> bool:
    return set(values.dropna().unique()) <= {0, 1, True, False}


def _classification_metrics(y_true, y_pred) -> Dict[str, float]:
    metrics = {"accuracy": float((y_true == y_pred).mean())}
    if _is_binary(y_true) and _is_binary(y_pred):
        tp = float(((y_true == 1) & (y_pred == 1)).sum())
        fp = float(((y_true == 0) & (y_pred == 1)).sum())
        fn = float(((y_true == 1) & (y_pred == 0)).sum())
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        metrics.update({"precision": precision, "recall": recall, "f1": f1})
    return metrics


def _regression_metrics(y_true, y_pred) -> Dict[str, float]:
    import numpy as np

    errors = y_true.astype(float) - y_pred.astype(float)
    return {
        "mae": float(errors.abs().mean()),
        "rmse": float(np.sqrt((errors**2).mean())),
        "bias": float(errors.mean()),
    }


def _align_series(y_true: Any, y_pred: Any, segments: Any = None):
    """Coerce inputs to pandas Series sharing one index.

    When both inputs are already pandas Series, they are aligned by index
    label (not raw position) whenever their indices are a permutation of each
    other — e.g. ``y_pred`` computed on a differently-sorted copy of the same
    rows. Resetting both independently by position, as a naive implementation
    would, silently mis-pairs rows in that case.
    """
    import pandas as pd

    y_true_is_series = isinstance(y_true, pd.Series)
    y_pred_is_series = isinstance(y_pred, pd.Series)

    if y_true_is_series and y_pred_is_series and not y_true.index.equals(y_pred.index):
        if len(y_true) == len(y_pred) and set(y_true.index) == set(y_pred.index):
            # Same rows, different order — align by label before going positional.
            y_pred = y_pred.reindex(y_true.index)
        else:
            raise ValueError(
                "y_true and y_pred are both pandas Series with different indices "
                "that are not a permutation of each other — pass aligned Series "
                "(same index) or plain arrays/lists to compare positionally."
            )

    y_true = pd.Series(list(y_true)) if not y_true_is_series else y_true.reset_index(drop=True)
    y_pred = pd.Series(list(y_pred)) if not y_pred_is_series else y_pred.reset_index(drop=True)
    if len(y_true) != len(y_pred):
        raise ValueError(f"y_true and y_pred lengths differ: {len(y_true)} vs {len(y_pred)}")
    if y_true.empty:
        raise ValueError("y_true is empty")
    if segments is None:
        return y_true, y_pred, None
    segments = (
        pd.Series(list(segments))
        if not isinstance(segments, pd.Series)
        else segments.reset_index(drop=True)
    )
    if len(segments) != len(y_true):
        raise ValueError(f"segments length {len(segments)} != y_true length {len(y_true)}")
    return y_true, y_pred, segments


def segment_metrics(
    y_true: Any,
    y_pred: Any,
    segments: Any,
    task: str = "classification",
    min_rows: int = 10,
) -> Dict[str, Any]:
    """Metrics per segment, sorted worst-first against the overall metric.

    ``segments`` is a per-row label (e.g. a categorical column: region,
    customer tier). Segments with fewer than ``min_rows`` rows are reported
    under ``skipped_segments`` instead of ranked — tiny slices produce noisy
    metrics that would dominate the worst-first ordering. Rows with a
    NaN/None segment label are also reported under ``skipped_segments``
    (as ``segment=None``) rather than silently dropped.

    Returns ``{"task", "primary_metric", "overall", "segments",
    "skipped_segments"}`` where each segment entry carries ``segment``,
    ``rows``, the task metrics, and ``delta_vs_overall`` on the primary metric
    (accuracy for classification, mae for regression; negative deltas are
    worse for accuracy, positive are worse for mae).
    """
    import pandas as pd

    if task not in VALID_TASKS:
        raise ValueError(f"Unknown task '{task}'. Valid: {VALID_TASKS}")

    y_true, y_pred, segments = _align_series(y_true, y_pred, segments)

    compute = _classification_metrics if task == "classification" else _regression_metrics
    primary = "accuracy" if task == "classification" else "mae"
    higher_is_better = task == "classification"

    overall = compute(y_true, y_pred)

    rows: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    # dropna=False: a NaN/None segment label must be surfaced in skipped_segments,
    # not silently vanish from the report (pandas groupby drops NaN keys by
    # default) — errors concentrated in unlabeled rows would otherwise be
    # invisible in both the ranking and the skip list. Iterating the GroupBy
    # directly (rather than via `.groups.items()`) sidesteps a pandas quirk
    # where building `.groups` for a dropna=False grouping over non-categorical
    # NaN keys can raise "Categorical categories cannot be null".
    for value, sub in y_true.groupby(segments.values, dropna=False):
        idx = sub.index
        n = len(idx)
        if pd.isna(value) or n < min_rows:
            skipped.append({"segment": None if pd.isna(value) else value, "rows": n})
            continue
        entry: Dict[str, Any] = {"segment": value, "rows": n}
        entry.update(compute(y_true.loc[idx], y_pred.loc[idx]))
        entry["delta_vs_overall"] = entry[primary] - overall[primary]
        rows.append(entry)

    rows.sort(key=lambda e: e[primary], reverse=not higher_is_better)
    if skipped:
        logger.debug(
            "segment_metrics: {} segment(s) below min_rows={} not ranked", len(skipped), min_rows
        )

    return {
        "task": task,
        "primary_metric": primary,
        "overall": overall,
        "segments": rows,
        "skipped_segments": skipped,
    }


def worst_records(
    y_true: Any,
    y_pred: Any,
    n: int = 20,
    task: str = "classification",
    y_score: Optional[Any] = None,
) -> Any:
    """The ``n`` worst predictions as a pandas DataFrame, worst first.

    regression: rows with the largest absolute error (columns ``y_true``,
    ``y_pred``, ``error``, ``abs_error``).
    classification: misclassified rows; with ``y_score`` (predicted
    probability/confidence of the predicted class) the most confident
    mistakes come first — those are the most informative to inspect.

    The DataFrame keeps the positional index of the inputs so rows can be
    traced back to the original dataset.
    """
    import pandas as pd

    if task not in VALID_TASKS:
        raise ValueError(f"Unknown task '{task}'. Valid: {VALID_TASKS}")

    y_true, y_pred, _ = _align_series(y_true, y_pred)

    if task == "regression":
        error = y_true.astype(float) - y_pred.astype(float)
        out = pd.DataFrame(
            {"y_true": y_true, "y_pred": y_pred, "error": error, "abs_error": error.abs()}
        )
        return out.nlargest(n, "abs_error")

    out = pd.DataFrame({"y_true": y_true, "y_pred": y_pred})
    if y_score is not None:
        score = (
            pd.Series(list(y_score))
            if not isinstance(y_score, pd.Series)
            else y_score.reset_index(drop=True)
        )
        if len(score) != len(out):
            raise ValueError(f"y_score length {len(score)} != y_true length {len(out)}")
        out["y_score"] = score
    mistakes = out[out["y_true"] != out["y_pred"]]
    if "y_score" in mistakes.columns:
        mistakes = mistakes.sort_values("y_score", ascending=False)
    return mistakes.head(n)
