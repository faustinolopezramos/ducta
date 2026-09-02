"""Regressions: checks that decided correctly and then misreported the decision.

None of these were logic bugs — every check passed or failed the right dataset.
What was wrong is what they *said* afterwards, which is the only part a reader of
a persisted report ever sees:

  * `min: 0` printed as `-∞`, because the bound was formatted with `min_val or
    '-∞'` and `0` is falsy. `row_count` additionally used `'∞'` for both ends, so
    a `max: 0` fell the same way. A range check pinned at zero advertised a bound
    it was not enforcing.
  * `DuplicateCheck` said "No duplicate rows found" on every pass, including a
    pass *within tolerance*, and dropped the count and rate it had just computed.
    The official demo hit this on real data — 15 duplicates in 907 rows, reported
    as none — and had to carry a nine-line comment in its node config warning
    readers not to believe the line.
  * `severity: "warning"` on a node's check was accepted by the config object and
    then read by nothing: `_create_result` resolves `severity or self.severity`,
    the check's *class* default. The check stayed an ERROR and still blocked at
    `quality_gate.max_errors` — the opposite of what the key asks for.
"""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from ducta.check import QUALITY_CHECKS_REGISTRY, DFAdapter
from ducta.check.core import CheckSeverity, QualityChecksFailed, QualityConfigError
from ducta.check.engine import ValidationPhaseRunner
from ducta.check.storage import FileStorageBackend


def run_check(name: str, df: pd.DataFrame, **config):
    check = QUALITY_CHECKS_REGISTRY[name]()
    return check.run(df, SimpleNamespace(**config), DFAdapter(df))


class TestZeroIsARealBound:
    def test_range_min_zero_is_not_reported_as_negative_infinity(self):
        result = run_check("range", pd.DataFrame({"v": [0, 1, 2]}), column="v", min=0, max=10)
        assert result.passed
        assert "-∞" not in result.message
        assert "[0, 10]" in result.message

    def test_range_max_zero_is_not_reported_as_positive_infinity(self):
        result = run_check("range", pd.DataFrame({"v": [-2, -1, 0]}), column="v", min=-10, max=0)
        assert result.passed
        assert "+∞" not in result.message
        assert "[-10, 0]" in result.message

    def test_row_count_min_zero_is_not_reported_as_infinity(self):
        result = run_check("row_count", pd.DataFrame({"id": [1, 2]}), min=0, max=10)
        assert result.passed
        assert "[0, 10]" in result.message

    def test_absent_bounds_still_render_as_infinities(self):
        result = run_check("range", pd.DataFrame({"v": [1, 2]}), column="v")
        assert result.passed
        assert "[-∞, +∞]" in result.message

    def test_row_count_absent_lower_bound_is_negative_infinity(self):
        # It used to print '∞' for the lower bound, which reads as *positive*
        # infinity — an interval whose low end is above its high end.
        result = run_check("row_count", pd.DataFrame({"id": [1, 2]}), max=10)
        assert result.passed
        assert "[-∞, 10]" in result.message


class TestDuplicatesReportsWhatItMeasured:
    def test_pass_within_tolerance_reports_the_duplicates_it_tolerated(self):
        # 1 duplicate in 4 rows = 25%, under a 30% tolerance: a pass that is
        # emphatically not "no duplicates found".
        df = pd.DataFrame({"id": [1, 1, 2, 3]})
        result = run_check("duplicates", df, columns=["id"], max_duplicate_rate=0.3)

        assert result.passed
        assert "No duplicate rows found" not in result.message
        assert result.details["duplicates_count"] == 1
        assert result.details["duplicate_rate"] == pytest.approx(0.25)
        assert result.details["max_duplicate_rate"] == pytest.approx(0.3)

    def test_clean_dataset_reports_zero_rather_than_omitting_the_count(self):
        df = pd.DataFrame({"id": [1, 2, 3]})
        result = run_check("duplicates", df, columns=["id"], max_duplicate_rate=0.0)

        assert result.passed
        assert result.details["duplicates_count"] == 0
        assert result.details["duplicate_rate"] == pytest.approx(0.0)


class TestConfiguredSeverityIsHonoured:
    def test_warning_severity_downgrades_a_failing_check(self, tmp_path):
        # An ERROR-severity failure raises QualityChecksFailed once all checks
        # finish, even outside fail_fast. Downgrading to WARNING is therefore
        # visible as the run completing at all.
        storage = FileStorageBackend(str(tmp_path))
        runner = ValidationPhaseRunner(storage_backend=storage, fail_fast=False)
        df = pd.DataFrame({"id": [1, 2, 3]})

        report = runner.run(
            dataset_name="ds",
            df=df,
            config={"checks": {"row_count": {"min": 1000, "severity": "warning"}}},
        )

        assert report.errors_count == 0
        assert report.warnings_count == 1
        assert report.results[0].severity == CheckSeverity.WARNING

    def test_without_the_key_the_check_stays_an_error(self, tmp_path):
        storage = FileStorageBackend(str(tmp_path))
        runner = ValidationPhaseRunner(storage_backend=storage, fail_fast=False)
        df = pd.DataFrame({"id": [1, 2, 3]})

        with pytest.raises(QualityChecksFailed):
            runner.run(
                dataset_name="ds",
                df=df,
                config={"checks": {"row_count": {"min": 1000}}},
            )

    def test_downgraded_check_does_not_trip_fail_fast(self, tmp_path):
        storage = FileStorageBackend(str(tmp_path))
        runner = ValidationPhaseRunner(storage_backend=storage, fail_fast=True)
        df = pd.DataFrame({"id": [1, 2, 3]})

        report = runner.run(
            dataset_name="ds",
            df=df,
            config={"checks": {"row_count": {"min": 1000, "severity": "warning"}}},
        )

        assert report.warnings_count == 1

    def test_invalid_severity_is_a_config_error_not_a_check_failure(self, tmp_path):
        # Two ways to get this wrong, both tried and rejected: falling back to
        # the class default turns a typo into a check that quietly keeps
        # blocking, and resolving it inside the execution try/except reports
        # "check execution failed", pointing the reader at their data instead of
        # at the line they mistyped.
        storage = FileStorageBackend(str(tmp_path))
        runner = ValidationPhaseRunner(storage_backend=storage, fail_fast=False)
        df = pd.DataFrame({"id": [1, 2, 3]})

        with pytest.raises(QualityConfigError, match="Invalid severity"):
            runner.run(
                dataset_name="ds",
                df=df,
                config={"checks": {"row_count": {"min": 1, "severity": "wrning"}}},
            )
