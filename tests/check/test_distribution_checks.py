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


class TestDriftDetectionMinCategoriesIsNotTopk:
    """Regression: min_categories used to be passed straight through as
    value_counts()'s topk, so a column with e.g. 50 real categories only
    ever got compared on its top `min_categories` most frequent ones —
    biasing Jensen-Shannon toward frequent categories and hiding drift in
    the long tail. min_categories is now a minimum-category-count gate;
    the fetch width is a separate (wider) topk_categories."""

    def test_fetch_uses_a_wide_default_topk_not_min_categories(self):
        check = DriftDetectionCheck()
        config = SimpleNamespace(
            columns=["c"],
            use_scipy=False,
            min_categories=5,
            _baseline={"c": {"value_counts": {"a": 1}}},
        )
        adapter = MagicMock()
        adapter.value_counts.return_value = {"a": 1}

        check.run(df=None, config=config, adapter=adapter)

        # Old buggy behavior called value_counts("c", topk=5) — the
        # min_categories value itself, capping the comparison at 5 rows.
        adapter.value_counts.assert_called_once_with("c", topk=100)

    def test_explicit_topk_categories_config_controls_fetch_width(self):
        check = DriftDetectionCheck()
        config = SimpleNamespace(
            columns=["c"],
            use_scipy=False,
            min_categories=1,
            topk_categories=250,
            _baseline={"c": {"value_counts": {"a": 1}}},
        )
        adapter = MagicMock()
        adapter.value_counts.return_value = {"a": 1}

        check.run(df=None, config=config, adapter=adapter)

        adapter.value_counts.assert_called_once_with("c", topk=250)

    def test_column_with_fewer_than_min_categories_is_skipped(self):
        check = DriftDetectionCheck()
        config = SimpleNamespace(
            columns=["sparse_col"],
            use_scipy=False,
            min_categories=5,
            _baseline={"sparse_col": {"value_counts": {"a": 10, "b": 5}}},
        )
        adapter = MagicMock()
        # Only 2 categories actually exist — below min_categories=5.
        adapter.value_counts.return_value = {"a": 10, "b": 5}

        result = check.run(df=None, config=config, adapter=adapter)

        assert result.details["_columns_evaluated"] == 0

    def test_column_meeting_min_categories_is_evaluated(self):
        check = DriftDetectionCheck()
        config = SimpleNamespace(
            columns=["c"],
            use_scipy=False,
            min_categories=2,
            _baseline={"c": {"value_counts": {"a": 1, "b": 1}}},
        )
        adapter = MagicMock()
        adapter.value_counts.return_value = {"a": 1, "b": 1}

        result = check.run(df=None, config=config, adapter=adapter)

        assert result.details["_columns_evaluated"] == 1


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
