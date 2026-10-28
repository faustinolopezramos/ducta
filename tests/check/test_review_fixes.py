"""Regression tests for the ``ducta.check`` review (2026-10-26)."""

from __future__ import annotations

import json
import time
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pytest

from ducta.check import QUALITY_CHECKS_REGISTRY, DFAdapter
from ducta.check.checks.distribution import DriftDetectionCheck
from ducta.check.checks.temporal import FreshnessCheck
from ducta.check.core import CheckSeverity, QualityConfigError
from ducta.check.engine import SanityPhaseRunner
from ducta.check.storage import ContextAwareStorageBackend, FileStorageBackend
from tests.check.test_validate_node_config import PIPELINE, _project


def run_check(name: str, df: pd.DataFrame, **config):
    return QUALITY_CHECKS_REGISTRY[name]().run(df, SimpleNamespace(**config), DFAdapter(df))


class TestSanityGateThatDoesNotDecide:
    """A declared gate turns off fail-fast; if it never evaluates, nothing may be lost."""

    FAILING = {"row_count": {"min": 1000}}

    def _run(self, gate):
        from ducta.check.core import QualityChecksFailed  # noqa: F401

        runner = SanityPhaseRunner(fail_fast=True)
        node = {"sanity_checks": {"checks": self.FAILING, "sanity_gate": gate}}
        return runner.run_node_checks([pd.DataFrame({"id": [1, 2, 3]})], node, "n")

    def test_a_disabled_gate_does_not_hide_the_error(self):
        from ducta.check.core import QualityCheckError

        with pytest.raises(QualityCheckError):
            self._run({"enabled": False})

    def test_a_gate_that_cannot_be_evaluated_fails_the_node(self):
        with pytest.raises(QualityConfigError):
            self._run({"max_errors": None})

    def test_a_gate_that_evaluates_still_decides(self):
        report = self._run({"behavior": "warn_only", "max_errors": 0})
        assert report.gate_decided and not report.passed


class TestCloudRoot:
    def _backend(self, tmp_path, fmt, base):
        context = SimpleNamespace(output_path=str(tmp_path))
        return ContextAwareStorageBackend(context, format=fmt, base_path=base)

    def test_a_cloud_uri_keeps_its_scheme(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        backend = self._backend(tmp_path, "parquet", "s3://bucket/quality")
        assert str(backend._dataset_dir("ds", "pipe")) == "s3://bucket/quality/pipe/ds"
        assert not (tmp_path / "s3:").exists()

    def test_json_cannot_go_to_the_cloud_and_says_so(self, tmp_path):
        with pytest.raises(QualityConfigError, match="parquet"):
            self._backend(tmp_path, "json", "s3://bucket/quality")

    def test_an_s3_output_path_is_not_collapsed(self, tmp_path, monkeypatch):
        from ducta.check.engine import ValidationPhaseRunner

        monkeypatch.chdir(tmp_path)
        context = SimpleNamespace(
            global_config={
                "output_path": "s3://bucket/out",
                "environment": "dev",
                "quality": {"output": {"format": "parquet"}},
            },
            output_path="s3://bucket/out",
        )
        runner = ValidationPhaseRunner(context=context)
        assert runner.workspace_path == "s3://bucket/out/dev/quality"

    def _runner(self, tmp_path, monkeypatch, output):
        from ducta.check.engine import ValidationPhaseRunner

        monkeypatch.chdir(tmp_path)
        context = SimpleNamespace(
            global_config={
                "output_path": "s3://bucket/out",
                "environment": "dev",
                "quality": {"output": output},
            },
            output_path="s3://bucket/out",
        )
        return ValidationPhaseRunner(context=context)

    def test_no_format_on_a_cloud_output_path_gets_parquet(self, tmp_path, monkeypatch):
        # JSON is the default format; a project that never chose one must not fail.
        runner = self._runner(tmp_path, monkeypatch, {})
        assert runner.storage.format == "parquet"

    def test_json_chosen_for_a_cloud_output_path_still_fails(self, tmp_path, monkeypatch):
        with pytest.raises(QualityConfigError, match="parquet"):
            self._runner(tmp_path, monkeypatch, {"format": "json"})


class TestHistoryIsAtomic:
    def test_a_torn_history_is_moved_aside_and_the_run_continues(self, tmp_path):
        backend = FileStorageBackend(str(tmp_path))
        backend.append_history("ds", {"score": 1.0})
        history = tmp_path / ".quality" / "_adhoc" / "ds" / "history.json"
        history.write_text('[{"score": 1.0}, {"sco')  # a process died mid-write

        assert backend.load_history("ds") is None  # no longer raises
        backend.append_history("ds", {"score": 0.5})

        assert [h["score"] for h in backend.load_history("ds")] == [0.5]
        assert list(history.parent.glob("history.json.corrupt-*"))

    def test_appends_accumulate_and_leave_no_temp_files(self, tmp_path):
        backend = FileStorageBackend(str(tmp_path))
        for score in (0.1, 0.2, 0.3):
            backend.append_history("ds", {"score": score})
        assert [h["score"] for h in backend.load_history("ds")] == [0.1, 0.2, 0.3]
        folder = tmp_path / ".quality" / "_adhoc" / "ds"
        assert not [p for p in folder.iterdir() if ".tmp-" in p.name]

    def test_an_append_error_reaches_the_report_warnings(self, tmp_path):
        from ducta.check.engine import ValidationPhaseRunner

        runner = ValidationPhaseRunner(workspace_path=str(tmp_path))
        runner.storage.append_history = MagicMock(side_effect=OSError("disk full"))
        report = runner.run("ds", pd.DataFrame({"a": [1]}), {"checks": {"empty_dataset": {}}})
        assert any("disk full" in w for w in report.persistence_warnings)

    def test_an_unreadable_non_json_history_is_not_overwritten(self, tmp_path):
        context = SimpleNamespace(output_path=str(tmp_path))
        backend = ContextAwareStorageBackend(context, format="csv", base_path=str(tmp_path / "q"))
        history_file = backend._dataset_dir("ds") / "history.csv"
        history_file.write_text("garbage")
        backend.load_history = lambda *a, **k: None  # a read error: None, like _read_with_io
        with pytest.raises(RuntimeError, match="could not be read"):
            backend.append_history("ds", {"score": 1.0})
        assert history_file.read_text() == "garbage"


class TestMisspelledOptionsAreErrors:
    def test_an_unknown_statistical_test_is_not_a_pass(self):
        df = pd.DataFrame({"x": range(100)})
        result = run_check("statistical", df, test_type="shapiro_wilk", columns=["x"])
        assert not result.passed and result.severity == CheckSeverity.ERROR
        assert "shapiro_wilk" in result.message

    def test_an_unknown_rule_type_is_not_a_pass(self):
        df = pd.DataFrame({"a": [1]})
        result = run_check("business_rules", df, rules=["a > 0"], rule_type="pyhton")
        assert not result.passed and result.severity == CheckSeverity.ERROR

    def test_an_unknown_direction_is_not_a_pass(self):
        df = pd.DataFrame({"id": [1]})
        check = QUALITY_CHECKS_REGISTRY["dataset_completeness"]()
        config = SimpleNamespace(
            column="id", reference_dataset="ref", reference_column="id", direction="a-b"
        )
        result = check.run(df, config, DFAdapter(df), {"ref": df})
        assert not result.passed and "direction" in result.message

    def test_schema_drift_without_a_baseline_does_not_pretend_to_store_one(self):
        result = run_check("schema_drift", pd.DataFrame({"a": [1]}))
        assert not result.passed and "storing" not in result.message

    def test_config_validate_rejects_the_statistical_typo(self):
        from ducta.check.params import CHECK_PARAMS, problems_in

        fragment = CHECK_PARAMS["statistical"]["test_type"]
        assert problems_in("shapiro_wilk", fragment, "test_type")
        assert not problems_in("ks", fragment, "test_type")


class TestSqlRulesCountNulls:
    def test_the_rule_must_be_true_not_merely_not_false(self):
        adapter = MagicMock()
        adapter.engine = "spark"
        adapter.filter_where.return_value = 2
        from ducta.check.checks.business import BusinessRulesCheck

        assert BusinessRulesCheck._execute_sql_rule(adapter, "amount > 0") == 2
        adapter.filter_where.assert_called_once_with("NOT COALESCE((amount > 0), FALSE)")


class TestDriftKeys:
    def _run(self, current, baseline, use_scipy=True):
        check = DriftDetectionCheck()
        config = SimpleNamespace(
            columns=["c"],
            use_scipy=use_scipy,
            min_categories=1,
            _baseline={"c": {"value_counts": baseline}},
        )
        adapter = MagicMock()
        adapter.get_columns.return_value = ["c"]
        adapter.value_counts.return_value = current
        return check.run(df=None, config=config, adapter=adapter)

    def test_timestamp_and_null_keys_match_the_stringified_baseline(self):
        stamps = {pd.Timestamp("2024-01-01"): 40, pd.Timestamp("2024-01-02"): 60, None: 5}
        baseline = {"2024-01-01 00:00:00": 40, "2024-01-02 00:00:00": 60}
        result = self._run(stamps, baseline)
        assert result.passed, result.message

    def test_a_real_shift_is_still_drift(self):
        result = self._run({"a": 5, "b": 95}, {"a": 95, "b": 5})
        assert not result.passed

    def test_chi_square_compares_shares_not_counts(self):
        result = self._run(
            {"a": 500_000, "b": 500_000}, {"a": 50_000, "b": 50_000}, use_scipy=False
        )
        assert result.passed, result.message


class TestDatasetCompleteness:
    def _run(self, main, ref, **config):
        check = QUALITY_CHECKS_REGISTRY["dataset_completeness"]()
        cfg = SimpleNamespace(column="id", reference_dataset="ref", reference_column="id", **config)
        return check.run(main, cfg, DFAdapter(main), {"ref": ref})

    def test_identical_tables_with_a_distinct_limit_are_inconclusive_not_failed_gaps(self):
        frame = pd.DataFrame({"id": range(50)})
        result = self._run(frame, frame.copy(), distinct_limit=10, direction="bidirectional")
        assert not result.passed and result.severity == CheckSeverity.WARNING
        assert "inconclusive" in result.message

    def test_a_limit_that_covers_the_values_compares_them(self):
        frame = pd.DataFrame({"id": range(5)})
        assert self._run(frame, frame.copy(), distinct_limit=10).passed

    def test_nan_is_not_a_missing_identifier(self):
        main = pd.DataFrame({"id": [1.0, float("nan")]})
        ref = pd.DataFrame({"id": [1.0, float("nan")]})
        assert self._run(main, ref, direction="bidirectional").passed


class TestHolidays:
    def test_unquoted_yaml_dates_are_holidays(self):
        # 24th, 25th and 26th are weekdays: the 25th, a holiday, does not count.
        with_holiday = FreshnessCheck._count_business_days(
            date(2024, 12, 24), date(2024, 12, 27), [date(2024, 12, 25)], False
        )
        without = FreshnessCheck._count_business_days(
            date(2024, 12, 24), date(2024, 12, 27), [], False
        )
        assert with_holiday == without - 1

    def test_strings_still_work_and_garbage_is_an_error(self):
        assert (
            FreshnessCheck._count_business_days(
                date(2024, 12, 24), date(2024, 12, 27), ["2024-12-25"], False
            )
            == 2
        )
        with pytest.raises(ValueError, match="Invalid holiday"):
            FreshnessCheck._count_business_days(
                date(2024, 12, 24), date(2024, 12, 27), ["christmas"], False
            )

    def test_a_naive_spark_datetime_is_read_in_the_driver_zone(self, monkeypatch):
        import os
        from datetime import datetime, timezone

        monkeypatch.setenv("TZ", "Etc/GMT-3")  # UTC+3
        time.tzset()
        try:
            adapter = MagicMock()
            adapter.engine = "spark"
            adapter.min_max.return_value = (None, datetime(2024, 1, 1, 12, 0))
            got = FreshnessCheck._get_max_date_value(adapter, "ts")
            assert got == datetime(2024, 1, 1, 9, 0, tzinfo=timezone.utc)
        finally:
            monkeypatch.delenv("TZ", raising=False)
            time.tzset()


class TestServiceFixes:
    def test_the_summary_trend_is_the_scores(self, tmp_path):
        from ducta.check.service import QualityService

        backend = FileStorageBackend(str(tmp_path))
        for score in (0.5, 0.75):
            backend.append_history("ds", {"score": score})
        backend.save_report({"score": 0.75, "passed": True}, "r1", "ds")
        summary = QualityService.get_summary(workspace=str(tmp_path), storage=backend)
        assert summary[0]["trend"] == [0.5, 0.75]

    def test_a_named_instance_is_validated_by_its_type(self, tmp_path):
        from ducta.check.service import QualityService

        root = _project(tmp_path, extra="orders_nulls: {type: null_rate, columns: [order_id]}")
        assert QualityService.validate_node_config("clean", root)["valid"]

        bad = _project(tmp_path / "bad", extra="orders_nulls: {type: zzz_unknown}")
        result = QualityService.validate_node_config("clean", bad)
        assert not result["valid"] and "type 'zzz_unknown'" in result["errors"][0]
