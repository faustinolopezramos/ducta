"""Regressions for the 2026-11-12 review of ducta.check: one test per finding.

Each test failed on the code before the fix (see the review's reproduction scripts).
"""

import json
import types
from pathlib import Path

import pandas as pd
import pytest

from ducta.check import QualityChecksFailed, SanityPhaseRunner, ValidationPhaseRunner
from ducta.check.checks.business import BusinessRulesCheck
from ducta.check.checks.structural import NullRateCheck, RangeCheck
from ducta.check.checks.temporal import IncrementalVolumeCheck
from ducta.check.core import DFAdapter, QualityConfigError, QualityEngineError
from ducta.check.output_manager import QualityOutputManager
from ducta.check.profiles import QualityProfile, apply_auto_tune
from ducta.check.service import QualityService
from ducta.check.storage import (
    HISTORY_MAX_ENTRIES,
    ContextAwareStorageBackend,
    FileStorageBackend,
    _sanitize_dataset_name,
)


def _config(**params):
    return type("CheckConfig", (), params)()


def _baseline_file(workspace) -> Path:
    found = list(Path(workspace).rglob("baseline.json"))
    return found[0] if found else None


# ---------------------------------------------------------------------------
# 1. A quality config/engine error fails the node instead of skipping the checks
# ---------------------------------------------------------------------------


class TestDataQualityDoesNotFailOpen:
    @pytest.fixture
    def executor(self, tmp_path):
        from ducta.core.execution.quality import QualityCheckExecutor

        ctx = types.SimpleNamespace(
            global_config={"output_path": str(tmp_path), "environment": "dev"},
            output_path=str(tmp_path),
            spark=None,
        )
        return QualityCheckExecutor(ctx)

    def test_a_misspelled_severity_fails_the_node(self, executor):
        dq = {"checks": {"null_rate": {"columns": ["id"], "severity": "warnig"}}}
        with pytest.raises(QualityConfigError):
            executor.run_dq_checks(pd.DataFrame({"id": [1]}), {"data_quality": dq}, "n")

    def test_an_output_the_checks_cannot_read_fails_the_node(self, executor):
        dq = {"checks": {"empty_dataset": {}}}
        with pytest.raises(QualityEngineError):
            executor.run_dq_checks({"not": "a dataframe"}, {"data_quality": dq}, "n")


# ---------------------------------------------------------------------------
# 2. The baseline comes from a run that passed
# ---------------------------------------------------------------------------


class TestBaselineFromAPassingRun:
    CFG = {
        "checks": {
            "range": {"column": "amount", "min": 0, "max": 1000},
            "anomaly_detection": {"columns": ["amount"]},
        },
        "quality_gate": {"max_errors": 0},
    }

    def test_a_blocked_first_run_does_not_become_the_baseline(self, tmp_path):
        from ducta.check import QualityGateBlocked

        bad = pd.DataFrame({"amount": [900_000.0, 950_000.0] * 50})
        with pytest.raises(QualityGateBlocked):
            ValidationPhaseRunner(workspace_path=str(tmp_path)).run("orders", bad, self.CFG)
        assert _baseline_file(tmp_path) is None

        good = pd.DataFrame({"amount": [100.0, 120.0, 90.0] * 30})
        report = ValidationPhaseRunner(workspace_path=str(tmp_path)).run("orders", good, self.CFG)
        assert report.passed
        saved = json.loads(_baseline_file(tmp_path).read_text())
        assert saved["amount"]["mean"] == pytest.approx(103.33, rel=1e-3)

    def test_an_unreadable_baseline_is_reported_and_not_overwritten(self, tmp_path):
        runner = ValidationPhaseRunner(workspace_path=str(tmp_path))
        saved = []
        runner.storage.load_baseline = lambda *a: (_ for _ in ()).throw(OSError("throttled"))
        runner.storage.save_baseline = lambda *a, **k: saved.append(a)
        report = runner.run("d", pd.DataFrame({"a": [1.0, 2.0]}), {"checks": {}})
        assert saved == []
        assert report.persistence_warnings == ["Could not read the baseline: throttled"]


# ---------------------------------------------------------------------------
# 3 / 4. NaN does not hide values (Spark) or pass a column gone null (pandas)
# ---------------------------------------------------------------------------


class TestMissingValues:
    def test_pandas_mean_of_an_all_null_column_is_none(self):
        adapter = DFAdapter(pd.DataFrame({"a": [None, None]}, dtype=float))
        assert adapter.mean_std("a") == (None, None)
        assert adapter.percentile("a", 50) is None

    def test_anomaly_detection_does_not_pass_a_column_gone_null(self, tmp_path):
        cfg = {"checks": {"anomaly_detection": {"columns": ["amount"]}}}
        runner = ValidationPhaseRunner(workspace_path=str(tmp_path))
        runner.run("t", pd.DataFrame({"amount": [10.0, 12.0, 11.0]}), cfg)
        report = runner.run("t", pd.DataFrame({"amount": [None] * 3}, dtype=float), cfg)
        (result,) = report.results
        assert not result.passed
        assert result.details["amount"] == {"skipped": "no non-null values"}

    def test_spark_range_sees_a_value_next_to_a_nan(self):
        pytest.importorskip("pyspark")
        from pyspark.sql import SparkSession

        spark = SparkSession.builder.master("local[1]").getOrCreate()
        sdf = spark.createDataFrame([(1.0,), (1e9,), (float("nan"),)], ["amount"])
        result = RangeCheck().run(
            sdf, _config(column="amount", min=0, max=100), DFAdapter(sdf), None
        )
        assert not result.passed
        assert result.details["actual_max"] == 1e9
        assert DFAdapter(sdf).null_counts(["amount"]) == {"amount": 1}


# ---------------------------------------------------------------------------
# 5. Cloud report paths keep their scheme
# ---------------------------------------------------------------------------


def test_output_manager_keeps_the_cloud_scheme():
    manager = QualityOutputManager(types.SimpleNamespace(global_config={}, spark=None))
    path = manager._resolve_output_path("s3://bucket/q", "orders", "r1", "data_quality", "p")
    assert path == "s3://bucket/q/data_quality/p/orders/r1"
    assert manager.summary_path("s3://bucket/q", "p", "r1") == "s3://bucket/q/global_summary/p/r1"


# ---------------------------------------------------------------------------
# 6. fail_fast yields to a declared gate
# ---------------------------------------------------------------------------


class TestFailFastYieldsToTheGate:
    DF = pd.DataFrame({"id": [1, None]})
    CHECKS = {"null_rate": {"columns": ["id"], "threshold": 0.0}}

    def test_warn_only_gate_lets_the_node_continue(self, tmp_path):
        cfg = {"checks": self.CHECKS, "quality_gate": {"behavior": "warn_only"}}
        runner = ValidationPhaseRunner(workspace_path=str(tmp_path), fail_fast=True)
        report = runner.run("d", self.DF, cfg)
        assert not report.passed

    def test_a_disabled_gate_still_fails_on_errors(self, tmp_path):
        cfg = {"checks": self.CHECKS, "quality_gate": {"enabled": False}}
        runner = ValidationPhaseRunner(workspace_path=str(tmp_path), fail_fast=True)
        with pytest.raises(QualityChecksFailed):
            runner.run("d", self.DF, cfg)


# ---------------------------------------------------------------------------
# 7. auto_tune keeps a configured score_threshold
# ---------------------------------------------------------------------------


class TestAutoTuneKeepsAnExplicitThreshold:
    class Storage:
        def load_history(self, *a):
            return [{"score": 0.5, "errors_count": 0, "gate_action": "pass"}] * 6

    PROFILE = QualityProfile("p", {}, auto_tune=True)

    def test_on_the_node(self):
        gate = {"score_threshold": 0.95}
        assert apply_auto_tune(self.PROFILE, gate, "d", self.Storage()) is gate

    def test_on_the_global_gate(self):
        tuned = apply_auto_tune(
            self.PROFILE, None, "d", self.Storage(), global_gate_cfg={"score_threshold": 0.9}
        )
        assert tuned is None

    def test_tunes_when_nobody_chose_one(self):
        assert apply_auto_tune(self.PROFILE, {}, "d", self.Storage()) == {"score_threshold": 0.475}


# ---------------------------------------------------------------------------
# 8. incremental_volume compares with the runs that passed
# ---------------------------------------------------------------------------


def test_incremental_volume_ignores_blocked_and_failed_runs():
    history = [{"row_count": 0, "gate_action": "block"}] * 3
    history += [{"row_count": 0, "errors_count": 2}] * 2
    history += [{"row_count": 1000, "gate_action": "pass", "errors_count": 0}] * 5
    adapter = DFAdapter(pd.DataFrame({"a": range(300)}))
    result = IncrementalVolumeCheck().run(None, _config(_history=history), adapter, None)
    assert not result.passed
    assert result.details["historical_mean"] == 1000.0


# ---------------------------------------------------------------------------
# 9. No sanity score is invented
# ---------------------------------------------------------------------------


def test_get_score_does_not_invent_a_sanity_score(tmp_path):
    report = ValidationPhaseRunner(workspace_path=str(tmp_path)).run(
        "t", pd.DataFrame({"a": [1]}), {"checks": {"empty_dataset": {}}}
    )
    score = QualityService.get_score(report.run_id, workspace=str(tmp_path))
    assert score["sanity_score"] is None
    assert score["dq_score"] == 1.0


# ---------------------------------------------------------------------------
# 10. A Python rule answers True/False
# ---------------------------------------------------------------------------


def test_a_python_rule_that_returns_a_number_is_a_rule_error():
    df = pd.DataFrame({"name": ["", "", "abc"]})
    cfg = _config(rule_type="python", rules=["lambda row: len(row['name'])"])
    result = BusinessRulesCheck().run(df, cfg, DFAdapter(df), None)
    assert not result.passed
    assert "must return True or False" in next(iter(result.details["rule_errors"].values()))


def test_a_boolean_python_rule_still_counts_violations():
    df = pd.DataFrame({"name": ["", "", "abc"]})
    cfg = _config(rule_type="python", rules=["lambda row: len(row['name']) > 0"])
    result = BusinessRulesCheck().run(df, cfg, DFAdapter(df), None)
    assert result.details["total_violations"] == 2


# ---------------------------------------------------------------------------
# 11. input_index must name an input
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("index", [2, -1, "0"])
def test_sanity_input_index_out_of_range_is_a_config_error(index):
    dfs = [pd.DataFrame({"x": [1]}), pd.DataFrame({"x": []})]
    node = {"sanity_checks": {"input_index": index, "checks": {"empty_dataset": {}}}}
    with pytest.raises(QualityConfigError, match="input_index"):
        SanityPhaseRunner(fail_fast=False).run_node_checks(dfs, node, "n")


# ---------------------------------------------------------------------------
# 12. Dataset names with a separator get their own folder
# ---------------------------------------------------------------------------


def test_dataset_names_with_a_separator_do_not_collide(tmp_path):
    assert _sanitize_dataset_name("raw/orders") == "raw__orders"
    assert _sanitize_dataset_name("../../etc") == "etc"
    with pytest.raises(ValueError):
        _sanitize_dataset_name("../..")
    storage = FileStorageBackend(str(tmp_path))
    assert storage._dataset_path("raw/orders") != storage._dataset_path("gold/orders")


# ---------------------------------------------------------------------------
# 13. A non-JSON history read error does not wipe the history
# ---------------------------------------------------------------------------


class TestStrictStateReads:
    @pytest.fixture
    def backend(self, tmp_path):
        ctx = types.SimpleNamespace(
            spark=None, global_config={"output_path": str(tmp_path)}, output_path=str(tmp_path)
        )
        return ContextAwareStorageBackend(ctx, format="parquet", base_path=str(tmp_path / "q"))

    def test_a_missing_history_is_none(self, backend, monkeypatch):
        class Reader:
            def read(self, *a):
                raise FileNotFoundError("nothing there")

        monkeypatch.setattr(
            "ducta.gate.factories.ReaderFactory.get_handler", lambda self, fmt: Reader()
        )
        assert backend.load_history("d") is None

    def test_a_failed_history_read_aborts_the_append(self, backend, monkeypatch):
        class Reader:
            def read(self, *a):
                raise ConnectionError("throttled")

        written = []
        monkeypatch.setattr(
            "ducta.gate.factories.ReaderFactory.get_handler", lambda self, fmt: Reader()
        )
        monkeypatch.setattr(backend, "_write_with_io", lambda data, path: written.append(data))
        with pytest.raises(ConnectionError):
            backend.append_history("d", {"row_count": 1})
        assert written == []


# ---------------------------------------------------------------------------
# S1 / S2. One-pass null counts; bounded history
# ---------------------------------------------------------------------------


def test_null_counts_matches_null_count_on_pandas():
    df = pd.DataFrame({"a": [1, None, 3], "b": [None, None, "x"]})
    adapter = DFAdapter(df)
    assert adapter.null_counts(["a", "b"]) == {"a": 1, "b": 2}
    result = NullRateCheck().run(df, _config(threshold=0.4), adapter, None)
    assert not result.passed
    assert set(result.details) == {"b"}


def test_history_keeps_the_most_recent_entries(tmp_path):
    storage = FileStorageBackend(str(tmp_path))
    path = storage._dataset_path("d") / "history.json"
    path.write_text(json.dumps([{"i": i} for i in range(HISTORY_MAX_ENTRIES)]))
    storage.append_history("d", {"i": "new"})
    history = json.loads(path.read_text())
    assert len(history) == HISTORY_MAX_ENTRIES
    assert history[0] == {"i": 1} and history[-1] == {"i": "new"}


def test_a_storage_error_on_fail_fast_abort_keeps_the_check_failure(tmp_path):
    runner = ValidationPhaseRunner(workspace_path=str(tmp_path), fail_fast=True)
    runner.storage.save_report = lambda *a, **k: (_ for _ in ()).throw(OSError("disk full"))
    cfg = {"checks": {"empty_dataset": {}}}
    with pytest.raises(QualityChecksFailed):
        runner.run("d", pd.DataFrame({"a": []}), cfg)


def test_sanity_and_validation_share_one_check_executor(tmp_path):
    """S5: both phases resolve `type:` and `severity:` the same way."""
    df = pd.DataFrame({"x": []})
    entry = {"no_rows": {"type": "empty_dataset", "severity": "warning"}}
    sanity = SanityPhaseRunner(fail_fast=False).run_node_checks(
        [df], {"sanity_checks": {"checks": entry}}, "n"
    )
    dq = ValidationPhaseRunner(workspace_path=str(tmp_path)).run("n", df, {"checks": entry})
    for report in (sanity, dq):
        (result,) = report.results
        assert (result.check_name, result.severity.value, result.passed) == (
            "no_rows",
            "WARNING",
            False,
        )
