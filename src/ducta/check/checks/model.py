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

# Checks on what a model produced: the column a serving node writes. Data checks
# ask whether the data is well formed; these ask whether the model is behaving —
# flagging a sane share of rows, scoring within its range, scoring the way it did
# when it was validated.

from typing import Any, ClassVar, Dict, FrozenSet, List, Optional

from ducta.check.core import (
    BaseQualityCheck,
    CheckResult,
    CheckSeverity,
    DFAdapter,
    register_check,
)

#: Rows sampled from each side for prediction_drift.
_DRIFT_SAMPLE_ROWS = 50_000
_PSI_BINS = 10
_PSI_EPSILON = 1e-4
#: PSI reported when a constant reference meets anything else. Finite, so reports
#: stay valid JSON; any PSI above 0.25 already reads as a major shift.
_PSI_MAX = 10.0


def _param(config: Any, name: str, default: Any = None) -> Any:
    return getattr(config, name, default)


@register_check("prediction_rate")
class PredictionRateCheck(BaseQualityCheck):
    """The share of rows a model flags stays within [min, max].

    A model that suddenly flags everything — or nothing — usually has a broken
    input, not a changed world. ``threshold`` turns a score into a flag
    (``column >= threshold``); without it the column is a label and ``1``/``true``
    is a flag.
    """

    CONFIG_PARAMS: ClassVar[FrozenSet[str]] = frozenset({"column", "threshold", "min", "max"})

    def __init__(self) -> None:
        super().__init__("prediction_rate", CheckSeverity.ERROR)

    def _run_impl(
        self,
        df: Any,
        config: Any,
        adapter: DFAdapter,
        context_datasets: Optional[Dict[str, Any]] = None,
    ) -> CheckResult:
        column = _param(config, "column")
        low, high = _param(config, "min"), _param(config, "max")
        if not column:
            return self._create_result(False, "prediction_rate needs column", {})
        if low is None and high is None:
            return self._create_result(
                False, "prediction_rate needs min and/or max: a rate with no bounds checks nothing"
            )
        missing = self._missing_columns_result([column], adapter)
        if missing is not None:
            return missing

        scored = adapter.count() - adapter.null_count(column)
        if scored == 0:
            return self._create_result(False, f"No scored rows in '{column}'", {"rows": 0})
        threshold = _param(config, "threshold")
        condition = (
            f"`{column}` >= {float(threshold)}" if threshold is not None else f"`{column}` == 1"
        )
        flagged = adapter.filter_where(condition)
        rate = flagged / scored
        details = {
            "column": column,
            "flagged": int(flagged),
            "scored_rows": int(scored),
            "rate": rate,
            "threshold": threshold,
            "min": low,
            "max": high,
        }
        if low is not None and rate < float(low):
            return self._create_result(
                False,
                f"'{column}' flags {rate:.2%} of rows, below the minimum {float(low):.2%}",
                details,
            )
        if high is not None and rate > float(high):
            return self._create_result(
                False,
                f"'{column}' flags {rate:.2%} of rows, above the maximum {float(high):.2%}",
                details,
            )
        return self._create_result(True, f"'{column}' flags {rate:.2%} of rows", details)


@register_check("prediction_contract")
class PredictionContractCheck(BaseQualityCheck):
    """Every row has a prediction, inside the range the model can produce."""

    CONFIG_PARAMS: ClassVar[FrozenSet[str]] = frozenset({"column", "min", "max", "allow_null"})

    def __init__(self) -> None:
        super().__init__("prediction_contract", CheckSeverity.ERROR)

    def _run_impl(
        self,
        df: Any,
        config: Any,
        adapter: DFAdapter,
        context_datasets: Optional[Dict[str, Any]] = None,
    ) -> CheckResult:
        column = _param(config, "column")
        if not column:
            return self._create_result(False, "prediction_contract needs column", {})
        missing = self._missing_columns_result([column], adapter)
        if missing is not None:
            return missing

        problems: List[str] = []
        nulls = adapter.null_count(column)
        if nulls and not _param(config, "allow_null", False):
            problems.append(f"{nulls} row(s) without a prediction")
        low, high = _param(config, "min"), _param(config, "max")
        observed_min, observed_max = adapter.min_max(column)
        if low is not None and observed_min is not None and observed_min < low:
            problems.append(f"minimum {observed_min} is below {low}")
        if high is not None and observed_max is not None and observed_max > high:
            problems.append(f"maximum {observed_max} is above {high}")
        details = {
            "column": column,
            "nulls": int(nulls),
            "observed_min": observed_min,
            "observed_max": observed_max,
            "min": low,
            "max": high,
        }
        if problems:
            return self._create_result(False, f"'{column}': {'; '.join(problems)}", details)
        return self._create_result(True, f"'{column}' honours its contract", details)


@register_check("prediction_drift")
class PredictionDriftCheck(BaseQualityCheck):
    """The scores' distribution has not moved away from a reference set of scores.

    ``reference`` is a catalog dataset — typically the scores on the validation
    set the model was promoted on. ``method: psi`` (population stability index,
    over the reference's deciles) or ``ks`` (Kolmogorov-Smirnov statistic). The
    statistic itself is compared with ``threshold``, not a p-value: on large
    datasets every difference is "significant".
    """

    CONFIG_PARAMS: ClassVar[FrozenSet[str]] = frozenset(
        {"column", "reference", "reference_column", "method", "threshold"}
    )
    DEFAULT_THRESHOLDS: ClassVar[Dict[str, float]] = {"psi": 0.2, "ks": 0.1}

    def __init__(self) -> None:
        super().__init__("prediction_drift", CheckSeverity.WARNING)

    def _run_impl(
        self,
        df: Any,
        config: Any,
        adapter: DFAdapter,
        context_datasets: Optional[Dict[str, Any]] = None,
    ) -> CheckResult:
        column = _param(config, "column")
        reference = _param(config, "reference")
        method = str(_param(config, "method", "psi")).lower()
        if not column or not reference:
            return self._create_result(False, "prediction_drift needs column and reference", {})
        if method not in self.DEFAULT_THRESHOLDS:
            return self._create_result(False, f"Unknown method '{method}' (psi | ks)", {})
        missing = self._missing_columns_result([column], adapter)
        if missing is not None:
            return missing
        ref_adapter = self._get_context_adapter(reference, context_datasets)
        if ref_adapter is None:
            return self._create_result(False, f"Reference dataset '{reference}' not available", {})
        ref_column = _param(config, "reference_column") or column
        if ref_column not in ref_adapter.get_columns():
            return self._create_result(
                False, f"Reference dataset '{reference}' has no column '{ref_column}'", {}
            )

        current = _numeric_sample(adapter, column)
        baseline = _numeric_sample(ref_adapter, ref_column)
        if len(current) == 0 or len(baseline) == 0:
            return self._create_result(
                False,
                "No numeric values to compare "
                f"(current: {len(current)}, reference: {len(baseline)})",
                {},
            )
        statistic = _psi(baseline, current) if method == "psi" else _ks(baseline, current)
        threshold = float(_param(config, "threshold", self.DEFAULT_THRESHOLDS[method]))
        details = {
            "column": column,
            "reference": reference,
            "method": method,
            "statistic": statistic,
            "threshold": threshold,
            "current_rows": len(current),
            "reference_rows": len(baseline),
        }
        if statistic > threshold:
            return self._create_result(
                False,
                f"'{column}' drifted from '{reference}': {method} {statistic:.4f} > {threshold}",
                details,
            )
        return self._create_result(
            True, f"'{column}' matches '{reference}': {method} {statistic:.4f}", details
        )


def _numeric_sample(adapter: DFAdapter, column: str) -> Any:
    import numpy as np
    import pandas as pd

    sample = adapter.sample(max_rows=_DRIFT_SAMPLE_ROWS)
    values = pd.to_numeric(sample[column], errors="coerce").to_numpy(dtype=float)
    return values[np.isfinite(values)]


def _psi(reference: Any, current: Any) -> float:
    """Population stability index over the reference's deciles."""
    import numpy as np

    edges = np.unique(np.quantile(reference, np.linspace(0, 1, _PSI_BINS + 1)))
    if len(edges) < 2:  # a constant reference: one bin holds everything
        same = float(np.mean(current == edges[0]))
        return 0.0 if same == 1.0 else _PSI_MAX
    edges[0], edges[-1] = -np.inf, np.inf
    ref_share = np.histogram(reference, edges)[0] / len(reference)
    cur_share = np.histogram(current, edges)[0] / len(current)
    ref_share = np.clip(ref_share, _PSI_EPSILON, None)
    cur_share = np.clip(cur_share, _PSI_EPSILON, None)
    return float(np.sum((cur_share - ref_share) * np.log(cur_share / ref_share)))


def _ks(reference: Any, current: Any) -> float:
    """Kolmogorov-Smirnov statistic: the largest gap between the two CDFs."""
    import numpy as np

    reference, current = np.sort(reference), np.sort(current)
    points = np.concatenate([reference, current])
    cdf_ref = np.searchsorted(reference, points, side="right") / len(reference)
    cdf_cur = np.searchsorted(current, points, side="right") / len(current)
    return float(np.max(np.abs(cdf_ref - cdf_cur)))
