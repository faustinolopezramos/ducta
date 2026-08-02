"""Regression test for AnomalyDetectionCheck's zero-columns-evaluated case.

See test_distribution_checks.py's module docstring — same bug shape:
`passed=True` with zero columns evaluated was indistinguishable from a
genuine pass.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from ducta.check.checks.temporal import AnomalyDetectionCheck
from ducta.check.core import CheckSeverity


class TestAnomalyDetectionZeroColumnsEvaluated:
    def test_no_matching_baseline_columns_is_not_a_clean_pass(self):
        check = AnomalyDetectionCheck()
        config = SimpleNamespace(
            columns=["target_col"],
            z_score_threshold=3.0,
            _baseline={"other_col": {"mean": 1.0, "std": 1.0}},
        )
        adapter = MagicMock()
        adapter.mean_std.return_value = (5.0, 1.0)

        result = check.run(df=None, config=config, adapter=adapter)

        assert result.passed is False
        assert result.severity == CheckSeverity.WARNING
        assert result.is_warning is True
        assert result.details["_columns_evaluated"] == 0

    def test_missing_baseline_entirely_is_still_a_legitimate_pass(self):
        check = AnomalyDetectionCheck()
        config = SimpleNamespace(columns=["c"], _baseline=None)
        adapter = MagicMock()

        result = check.run(df=None, config=config, adapter=adapter)

        assert result.passed is True
