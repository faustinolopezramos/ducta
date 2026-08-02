"""Regression tests for DriftDetectionCheck/StatisticalCheck's zero-columns-evaluated case.

Both used to return `passed=True` (a clean pass) when every configured column
failed to evaluate (no per-column baseline, or not enough samples) — a
`CheckResult` with `passed=True` is indistinguishable from a genuine pass to
`report.passed`/`errors_count`/`warnings_count`, so a missing baseline could
silently look like "everything's fine". `severity=WARNING` alone didn't fix
this: `CheckResult.is_warning` requires `passed is False`.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from ducta.check.checks.distribution import DriftDetectionCheck, StatisticalCheck
from ducta.check.core import CheckSeverity


class TestDriftDetectionZeroColumnsEvaluated:
    def test_no_matching_baseline_columns_is_not_a_clean_pass(self):
        check = DriftDetectionCheck()
        config = SimpleNamespace(
            columns=["target_col"],
            use_scipy=False,
            _baseline={"other_col": {"value_counts": {"a": 3}}},
        )
        adapter = MagicMock()
        adapter.value_counts.return_value = {"a": 1}

        result = check.run(df=None, config=config, adapter=adapter)

        assert result.passed is False
        assert result.severity == CheckSeverity.WARNING
        assert result.is_warning is True
        assert result.details["_columns_evaluated"] == 0

    def test_missing_baseline_entirely_is_still_a_legitimate_pass(self):
        # Distinct from the above: no baseline AT ALL (first run) is a
        # legitimate, unambiguous pass — must not regress to `passed=False`.
        check = DriftDetectionCheck()
        config = SimpleNamespace(columns=["c"], use_scipy=False, _baseline=None)
        adapter = MagicMock()

        result = check.run(df=None, config=config, adapter=adapter)

        assert result.passed is True


class TestStatisticalCheckZeroColumnsEvaluated:
    def test_no_columns_meet_min_samples_is_not_a_clean_pass(self):
        check = StatisticalCheck()
        config = SimpleNamespace(
            columns=["a"],
            test_type="shapiro",
            alpha=0.05,
            min_samples=1000,
            max_rows=1000,
        )
        import pandas as pd

        adapter = MagicMock()
        adapter.sample.return_value = pd.DataFrame({"a": [1, 2, 3]})  # far fewer than min_samples

        result = check.run(df=None, config=config, adapter=adapter)

        assert result.passed is False
        assert result.severity == CheckSeverity.WARNING
        assert result.details["_columns_evaluated"] == 0
