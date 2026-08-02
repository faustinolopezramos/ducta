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

from typing import Any, Dict, Tuple

from loguru import logger


def trivial_baseline_metrics(y_true: Any, task: str = "classification") -> Dict[str, float]:
    """Metrics of the trivial predictor on ``y_true``.

    classification (majority-class predictor):
        baseline_accuracy, baseline_f1, baseline_precision, baseline_recall,
        majority_fraction.
        Binary labels ({0,1} / bools) treat 1/True as positive and report
        positive-class metrics. Multiclass labels report MACRO-averaged
        metrics of the majority predictor — compare them against
        macro-averaged model metrics, never against a positive-class F1.
    regression (mean predictor):
        baseline_mae, baseline_rmse, baseline_r2 (0.0 by definition)
    """
    import numpy as np
    import pandas as pd

    y = pd.Series(list(y_true)) if not isinstance(y_true, pd.Series) else y_true
    if y.empty:
        raise ValueError("y_true is empty")

    if task == "regression":
        mean = float(y.mean())
        return {
            "baseline_mae": float((y - mean).abs().mean()),
            "baseline_rmse": float(np.sqrt(((y - mean) ** 2).mean())),
            "baseline_r2": 0.0,
        }

    if task != "classification":
        raise ValueError(f"Unknown task '{task}'. Valid: classification, regression")

    counts = y.value_counts()
    majority = counts.index[0]
    majority_fraction = float(counts.iloc[0] / len(y))

    # F1/precision/recall of always predicting the majority class, with the
    # positive class defined as 1/True (binary convention). If the majority is
    # the negative class the trivial predictor never predicts positive: f1=0.
    positive_fraction = float((y == 1).mean()) if set(counts.index) <= {0, 1, True, False} else None
    if positive_fraction is None:
        # Multiclass: macro-average over classes. Only the majority class gets
        # nonzero scores (precision = its frequency, recall = 1); the rest are
        # never predicted, so each contributes 0 to the macro mean.
        n_classes = len(counts)
        p = majority_fraction
        precision = p / n_classes
        recall = 1.0 / n_classes
        f1 = (2 * p / (p + 1.0)) / n_classes
        logger.warning(
            "Multiclass labels ({} classes): baseline metrics are MACRO-averaged. "
            "Gates on f1/precision/recall must compare against macro-averaged "
            "model metrics to be meaningful.",
            n_classes,
        )
    elif majority in (1, True):
        precision = positive_fraction
        recall = 1.0
        f1 = 2 * precision / (precision + 1.0)
    else:
        precision = recall = f1 = 0.0

    return {
        "baseline_accuracy": majority_fraction,
        "baseline_f1": f1,
        "baseline_precision": precision,
        "baseline_recall": recall,
        "majority_fraction": majority_fraction,
    }


def compare_to_baseline(
    model_metrics: Dict[str, float],
    baseline_metrics: Dict[str, float],
    metric: str,
    min_delta: float = 0.0,
    higher_is_better: bool = True,
) -> Tuple[bool, str]:
    """Check that ``metric`` beats its baseline counterpart by ``min_delta``.

    Looks up ``metric`` in ``model_metrics`` and ``baseline_<metric>`` (or
    ``metric``) in ``baseline_metrics``. Returns ``(passes, message)``.
    """
    if metric not in model_metrics:
        return False, f"Model metrics do not include '{metric}'"

    baseline_key = f"baseline_{metric}" if f"baseline_{metric}" in baseline_metrics else metric
    if baseline_key not in baseline_metrics:
        return False, f"Baseline metrics do not include '{baseline_key}'"

    model_value = float(model_metrics[metric])
    baseline_value = float(baseline_metrics[baseline_key])
    delta = model_value - baseline_value if higher_is_better else baseline_value - model_value
    passes = delta >= min_delta

    direction = ">" if higher_is_better else "<"
    message = (
        f"{metric}={model_value:.4f} vs {baseline_key}={baseline_value:.4f} "
        f"(delta={delta:+.4f}, required {direction} baseline by {min_delta:+.4f}): "
        f"{'PASS' if passes else 'FAIL'}"
    )
    return passes, message
