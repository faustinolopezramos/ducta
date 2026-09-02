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

Distribution quality checks.
"""

from functools import lru_cache
from typing import Any, Dict, Optional

from loguru import logger  # type: ignore

from ducta.check.core import (
    BaseQualityCheck,
    CheckResult,
    CheckSeverity,
    DFAdapter,
    QualityEngineError,
    register_check,
)


@lru_cache(maxsize=1)
def _scipy_available() -> bool:
    """Whether scipy can be imported. Checked once up front (not per-column)
    so a missing dependency surfaces as a clear failure instead of being
    swallowed by each column's individual try/except and silently producing
    a false PASS ("no drift"/"all tests passed") once every column errors.
    """
    try:
        import scipy  # noqa: F401

        return True
    except ImportError:
        return False


@register_check("drift_detection")
class DriftDetectionCheck(BaseQualityCheck):
    """Detects distribution drift comparing current vs baseline using Jensen-Shannon divergence."""

    def __init__(self) -> None:
        super().__init__("drift_detection", CheckSeverity.WARNING)

    def run(
        self,
        df: Any,
        config: Any,
        adapter: DFAdapter,
        context_datasets: Optional[Dict[str, Any]] = None,
    ) -> CheckResult:
        """Execute drift detection check."""
        try:
            if not getattr(config, "enabled", True):
                return self._create_result(True, "Check disabled")

            columns = config.columns if hasattr(config, "columns") else []
            if not columns:
                return self._create_result(True, "No columns configured for drift detection", {})

            threshold = (
                config.jensen_shannon_threshold
                if hasattr(config, "jensen_shannon_threshold")
                else 0.1
            )
            use_scipy = config.use_scipy if hasattr(config, "use_scipy") else True
            min_categories = config.min_categories if hasattr(config, "min_categories") else 5
            # How many categories to actually fetch per column for the
            # Jensen-Shannon comparison — independent of min_categories,
            # which is a *minimum* category-count gate, not a cap on how
            # many categories get compared. Reusing min_categories as both
            # meant a column with e.g. 50 real categories only ever got
            # compared on its top `min_categories` most frequent ones,
            # biasing drift detection toward frequent categories and hiding
            # drift in the long tail.
            topk_categories = config.topk_categories if hasattr(config, "topk_categories") else 100
            # value_counts() is itself topk-limited, so fetch at least
            # min_categories rows — otherwise "fewer than min_categories
            # rows came back" could mean "the fetch was capped low", not
            # "the column really has fewer than min_categories categories."
            fetch_topk = max(topk_categories, min_categories)

            if use_scipy and not _scipy_available():
                return self._create_result(
                    False,
                    "SciPy is required for drift detection (use_scipy=True) but is not "
                    "installed. Run `pip install scipy`, or set use_scipy=false to use "
                    "the chi-square distance instead.",
                    {},
                    severity=CheckSeverity.WARNING,
                )

            # Load baseline
            baseline = getattr(config, "_baseline", None)
            if not baseline:
                return self._create_result(
                    True, "No baseline available, first run creates baseline", {}
                )

            drifts = []
            details = {}
            columns_evaluated = 0

            for column in columns:
                try:
                    current_counts = adapter.value_counts(column, topk=fetch_topk)
                    if len(current_counts) < min_categories:
                        logger.debug(
                            f"Skipping drift check for column '{column}': only "
                            f"{len(current_counts)} categor{'y' if len(current_counts) == 1 else 'ies'} "
                            f"found, need at least {min_categories}"
                        )
                        continue

                    baseline_counts = baseline.get(column, {}).get("value_counts", {})

                    if not baseline_counts:
                        continue

                    drift_distance = self._compute_distribution_distance(
                        current_counts,
                        baseline_counts,
                        use_scipy,
                    )
                    columns_evaluated += 1

                    details[column] = {
                        "drift_distance": float(drift_distance),
                        "threshold": float(threshold),
                        "current_categories": len(current_counts),
                        "baseline_categories": len(baseline_counts),
                    }

                    if drift_distance > threshold:
                        drifts.append(
                            f"Column '{column}': drift {drift_distance:.3f} > {threshold}"
                        )

                except Exception as e:
                    logger.exception(f"Error detecting drift in column '{column}': {e}")

            details["_columns_evaluated"] = columns_evaluated
            details["_columns_configured"] = len(columns)

            if drifts:
                return self._create_result(
                    False,
                    f"Distribution drift detected in {len(drifts)} column(s): {'; '.join(drifts)}",
                    details,
                )

            if columns_evaluated == 0:
                # See temporal.py's AnomalyDetectionCheck for why this is
                # `passed=False`: a clean pass with zero columns evaluated is
                # indistinguishable from a real pass to report.passed/
                # errors_count, so a missing baseline silently looked fine.
                return self._create_result(
                    False,
                    f"No columns could be evaluated (0/{len(columns)} had a usable baseline) "
                    "— inconclusive, not a pass",
                    details,
                    severity=CheckSeverity.WARNING,
                )

            return self._create_result(True, "No distribution drift detected", details)

        except Exception as e:
            logger.exception(f"Error executing drift detection check: {e}")
            return self._create_result(
                False, f"Check execution failed: {str(e)}", {"error": str(e)}
            )

    @staticmethod
    def _compute_distribution_distance(
        current: Dict[Any, int],
        baseline: Dict[Any, int],
        use_scipy: bool,
    ) -> float:
        """Compute distribution distance (Jensen-Shannon or chi-square)."""
        if use_scipy:
            try:
                from scipy.spatial.distance import jensenshannon  # type: ignore

                if not current or not baseline:
                    return 0.0

                # Align on union of all categories to guarantee positional match
                all_categories = sorted(
                    set(current.keys()) | set(baseline.keys()),
                    key=str,
                )

                current_vals = [current.get(k, 0) for k in all_categories]
                baseline_vals = [baseline.get(k, 0) for k in all_categories]

                current_sum = sum(current_vals) or 1
                baseline_sum = sum(baseline_vals) or 1

                current_dist = [v / current_sum for v in current_vals]
                baseline_dist = [v / baseline_sum for v in baseline_vals]

                return float(jensenshannon(current_dist, baseline_dist))
            except ImportError:
                raise QualityEngineError(
                    "SciPy is required for DriftDetectionCheck with Jensen-Shannon divergence. "
                    "Run `pip install scipy`.",
                    engine_type="",
                )
        else:
            return DriftDetectionCheck._compute_chi_square_distance(current, baseline)

    @staticmethod
    def _compute_chi_square_distance(current: Dict[Any, int], baseline: Dict[Any, int]) -> float:
        """Compute normalised chi-square distance between distributions."""
        chi_square = 0.0
        all_keys = set(current.keys()) | set(baseline.keys())
        baseline_total = sum(baseline.values()) or 1

        for key in all_keys:
            curr_val = current.get(key, 0)
            base_val = baseline.get(key, 0)

            if base_val == 0:
                chi_square += curr_val / baseline_total
            else:
                chi_square += ((curr_val - base_val) ** 2) / base_val

        return chi_square / baseline_total


@register_check("statistical")
class StatisticalCheck(BaseQualityCheck):
    """Executes statistical hypothesis tests (normality, distribution, correlation)."""

    def __init__(self) -> None:
        super().__init__("statistical", CheckSeverity.WARNING)

    def run(
        self,
        df: Any,
        config: Any,
        adapter: DFAdapter,
        context_datasets: Optional[Dict[str, Any]] = None,
    ) -> CheckResult:
        """Execute statistical check."""
        try:
            if not getattr(config, "enabled", True):
                return self._create_result(True, "Check disabled")

            test_type = config.test_type if hasattr(config, "test_type") else "shapiro"
            columns = config.columns if hasattr(config, "columns") else []
            alpha = config.alpha if hasattr(config, "alpha") else 0.05
            min_samples = config.min_samples if hasattr(config, "min_samples") else 30

            if not columns:
                return self._create_result(True, "No columns configured for statistical test", {})

            if not _scipy_available():
                return self._create_result(
                    False,
                    f"SciPy is required for statistical tests ('{test_type}') but is not "
                    "installed. Run `pip install scipy`.",
                    {},
                    severity=CheckSeverity.WARNING,
                )

            # Sample data for driver-side statistical tests to avoid OOM
            max_rows = config.max_rows if hasattr(config, "max_rows") else 100000
            pdf = adapter.sample(max_rows=max_rows)
            details = {}
            columns_evaluated = 0

            for column in columns:
                try:
                    if column not in pdf.columns:
                        continue

                    data = pdf[column].dropna().values
                    if len(data) < min_samples:
                        continue

                    # Execute test based on type
                    if test_type == "shapiro":
                        self._test_shapiro(data, alpha, column, details)
                    elif test_type == "ks":
                        self._test_ks(data, alpha, column, details)
                    elif test_type == "chi_square":
                        self._test_chi_square(data, alpha, column, details)
                    columns_evaluated += 1

                except Exception as e:
                    logger.warning(
                        f"Error in statistical test '{test_type}' for column '{column}': {e}"
                    )

            details["_columns_evaluated"] = columns_evaluated
            details["_columns_configured"] = len(columns)

            # Check if any test failed
            failed_tests = [
                k for k, v in details.items() if isinstance(v, dict) and not v.get("passed", True)
            ]

            if failed_tests:
                return self._create_result(
                    False,
                    f"Statistical tests failed for {len(failed_tests)} column(s)",
                    details,
                )

            if columns_evaluated == 0:
                # See AnomalyDetectionCheck in temporal.py for why this is
                # `passed=False` rather than a clean pass.
                return self._create_result(
                    False,
                    f"No columns could be evaluated (0/{len(columns)} had enough samples) "
                    "— inconclusive, not a pass",
                    details,
                    severity=CheckSeverity.WARNING,
                )

            return self._create_result(True, f"All statistical tests passed (α={alpha})", details)

        except Exception as e:
            logger.exception(f"Error executing statistical check: {e}")
            return self._create_result(
                False, f"Check execution failed: {str(e)}", {"error": str(e)}
            )

    @staticmethod
    def _test_shapiro(data: Any, alpha: float, column: str, details: Dict) -> None:
        """Execute Shapiro-Wilk normality test."""
        try:
            from scipy.stats import shapiro  # type: ignore

            if len(data) < 5000:
                stat, p_value = shapiro(data)
            else:
                # Sample for large datasets; fixed seed for reproducibility
                import numpy as np  # type: ignore

                rng = np.random.default_rng(seed=42)
                sample = rng.choice(data, 5000, replace=False)
                stat, p_value = shapiro(sample)

            details[f"{column}_shapiro"] = {
                "statistic": float(stat),
                "p_value": float(p_value),
                "alpha": float(alpha),
                "passed": p_value > alpha,
            }
        except ImportError:
            raise QualityEngineError(
                "SciPy is required for StatisticalCheck (Shapiro test). Run `pip install scipy`.",
                engine_type="",
            )

    @staticmethod
    def _test_ks(data: Any, alpha: float, column: str, details: Dict) -> None:
        """Execute Kolmogorov-Smirnov test."""
        try:
            from scipy.stats import kstest  # type: ignore

            stat, p_value = kstest(data, "norm", args=(data.mean(), data.std()))

            details[f"{column}_ks"] = {
                "statistic": float(stat),
                "p_value": float(p_value),
                "alpha": float(alpha),
                "passed": p_value > alpha,
            }
        except ImportError:
            raise QualityEngineError(
                "SciPy is required for StatisticalCheck (KS test). Run `pip install scipy`.",
                engine_type="",
            )

    @staticmethod
    def _test_chi_square(data: Any, alpha: float, column: str, details: Dict) -> None:
        """Execute Chi-square test."""
        try:
            import numpy as np  # type: ignore
            from scipy.stats import chisquare  # type: ignore

            # Create categorical test
            binned = np.histogram(data, bins=10)[0]
            expected = np.ones_like(binned) * (len(data) / len(binned))

            stat, p_value = chisquare(binned, expected)

            details[f"{column}_chi_square"] = {
                "statistic": float(stat),
                "p_value": float(p_value),
                "alpha": float(alpha),
                "passed": p_value > alpha,
            }
        except ImportError:
            raise QualityEngineError(
                "SciPy is required for StatisticalCheck (Chi-square test). "
                "Run `pip install scipy`.",
                engine_type="",
            )
