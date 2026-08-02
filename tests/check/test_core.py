"""Unit tests for ducta.check.core — DFAdapter, CheckResult, QualityReport."""

from __future__ import annotations

import pandas as pd
import pytest

from ducta.check.core import (
    CheckResult,
    CheckSeverity,
    DFAdapter,
    QualityEngineError,
    QualityReport,
)


@pytest.fixture
def df():
    return pd.DataFrame({"id": [1, 2, 3, 4], "v": [1.0, None, 3.0, 4.0], "g": ["a", "a", "b", "b"]})


class TestDFAdapterPandas:
    def test_detects_pandas_engine(self, df):
        assert DFAdapter(df).engine == "pandas"

    def test_unsupported_type_raises(self):
        with pytest.raises(QualityEngineError):
            DFAdapter(object())

    def test_count_and_columns(self, df):
        a = DFAdapter(df)
        assert a.count() == 4
        assert a.get_columns() == ["id", "v", "g"]

    def test_schema_is_string_map(self, df):
        schema = DFAdapter(df).get_schema()
        assert set(schema.keys()) == {"id", "v", "g"}
        assert all(isinstance(v, str) for v in schema.values())

    def test_null_count(self, df):
        assert DFAdapter(df).null_count("v") == 1
        assert DFAdapter(df).null_count("id") == 0

    def test_min_max(self, df):
        assert DFAdapter(df).min_max("id") == (1.0, 4.0)

    def test_distinct_values(self, df):
        assert set(DFAdapter(df).distinct_values("g")) == {"a", "b"}

    def test_value_counts(self, df):
        counts = DFAdapter(df).value_counts("g")
        assert counts["a"] == 2 and counts["b"] == 2

    def test_filter_where(self, df):
        assert DFAdapter(df).filter_where("id > 2") == 2

    def test_anti_join(self, df):
        ref = DFAdapter(pd.DataFrame({"id": [1, 2]}))
        # rows in df whose id not in ref -> ids 3, 4
        assert DFAdapter(df).anti_join("id", ref, "id") == 2


class TestCheckSeverity:
    def test_from_str(self):
        assert CheckSeverity.from_str("error") == CheckSeverity.ERROR
        assert CheckSeverity.from_str("WARNING") == CheckSeverity.WARNING

    def test_from_str_invalid(self):
        with pytest.raises(ValueError):
            CheckSeverity.from_str("bogus")

    def test_helpers(self):
        assert CheckSeverity.ERROR.is_error()
        assert CheckSeverity.WARNING.is_warning()


class TestCheckResult:
    def test_error_flag(self):
        r = CheckResult("c", passed=False, severity=CheckSeverity.ERROR)
        assert r.is_error and not r.is_warning

    def test_warning_flag(self):
        r = CheckResult("c", passed=False, severity=CheckSeverity.WARNING)
        assert r.is_warning and not r.is_error

    def test_passed_is_neither(self):
        r = CheckResult("c", passed=True)
        assert not r.is_error and not r.is_warning

    def test_string_severity_coerced(self):
        r = CheckResult("c", passed=True, severity="ERROR")
        assert r.severity == CheckSeverity.ERROR

    def test_to_dict(self):
        d = CheckResult("c", passed=True).to_dict()
        assert d["check_name"] == "c" and d["passed"] is True


class TestQualityReport:
    def test_counts(self):
        report = QualityReport(
            dataset_name="d",
            passed=False,
            results=[
                CheckResult("a", passed=False, severity=CheckSeverity.ERROR),
                CheckResult("b", passed=False, severity=CheckSeverity.WARNING),
                CheckResult("c", passed=True),
            ],
        )
        assert report.errors_count == 1
        assert report.warnings_count == 1
        assert report.checks_count == 3

    def test_dict_results_normalized(self):
        report = QualityReport(
            dataset_name="d",
            passed=True,
            results=[{"check_name": "a", "passed": True, "severity": "ERROR"}],
        )
        assert isinstance(report.results[0], CheckResult)
        assert report.results[0].check_name == "a"
