"""``ValidationPhaseRunner.run``: the branches ``test_engine.py`` leaves out.

Written against the runner as it was before it was split into steps
(2026-11-10), to hold its behaviour while the steps moved out of ``run``.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import patch

import pandas as pd
import pytest

from ducta.check.core import QUALITY_CHECKS_REGISTRY, CheckResult, QualityChecksFailed
from ducta.check.engine import ValidationPhaseRunner
from ducta.check.storage import FileStorageBackend

DF = pd.DataFrame({"id": [1, 2, 3]})


class _Recorder:
    """A check that passes and remembers the config it was given."""

    seen: List[Any] = []

    def run(self, df, config, adapter, context_datasets):
        _Recorder.seen.append(config)
        return CheckResult(check_name="recorder", passed=True, message="ok")


class _Boom:
    def run(self, df, config, adapter, context_datasets):
        raise RuntimeError("check blew up")


def _runner(tmp_path, **kwargs: Any) -> ValidationPhaseRunner:
    kwargs.setdefault("fail_fast", False)
    return ValidationPhaseRunner(storage_backend=FileStorageBackend(str(tmp_path)), **kwargs)


class TestConfig:
    def test_an_object_config_is_read_like_a_dict(self, tmp_path):
        config = SimpleNamespace(
            enabled=True, checks={"row_count": {"min": 1}}, profile=None, quality_gate=None
        )
        report = _runner(tmp_path).run("ds", DF, config)
        assert report.passed and [r.check_name for r in report.results] == ["row_count"]

    def test_a_disabled_object_config_runs_nothing(self, tmp_path):
        report = _runner(tmp_path).run("ds", DF, SimpleNamespace(enabled=False, checks={}))
        assert report.passed and report.results == []
        assert report.run_id

    def test_a_disabled_check_is_skipped(self, tmp_path):
        config = {"checks": {"row_count": {"enabled": False, "min": 1000}}}
        report = _runner(tmp_path).run("ds", DF, config)
        assert report.passed and report.results == []

    def test_a_check_entry_that_is_not_a_mapping_is_ignored(self, tmp_path):
        report = _runner(tmp_path).run("ds", DF, {"checks": {"row_count": True}})
        assert report.results == []


class TestTemporalInputs:
    @pytest.mark.parametrize(
        "registry_key, gets_history",
        [("anomaly_detection", True), ("incremental_volume", True), ("drift_detection", False)],
    )
    def test_temporal_checks_get_the_baseline_and_history(
        self, tmp_path, registry_key, gets_history
    ):
        runner = _runner(tmp_path)
        runner.run("ds", DF, {"checks": {}})  # first run: creates the baseline and history
        _Recorder.seen = []
        with patch.dict(QUALITY_CHECKS_REGISTRY, {registry_key: _Recorder}):
            report = runner.run("ds", DF, {"checks": {"mine": {"type": registry_key}}})
        config = _Recorder.seen[0]
        assert config._baseline is not None
        assert hasattr(config, "_history") is gets_history
        if gets_history:
            assert len(config._history) == 1
        assert [r.check_name for r in report.results] == ["mine"]  # the alias, not the type


class TestCheckErrors:
    def test_an_exception_in_a_check_is_an_error_result(self, tmp_path):
        with patch.dict(QUALITY_CHECKS_REGISTRY, {"boom": _Boom}):
            with pytest.raises(QualityChecksFailed) as caught:
                _runner(tmp_path).run("ds", DF, {"checks": {"boom": {}}})
        assert "check blew up" in caught.value.results[0].message

    def test_under_fail_fast_it_aborts_before_the_next_check(self, tmp_path):
        _Recorder.seen = []
        checks: Dict[str, Any] = {"boom": {}, "after": {"type": "rec"}}
        with patch.dict(QUALITY_CHECKS_REGISTRY, {"boom": _Boom, "rec": _Recorder}):
            with pytest.raises(QualityChecksFailed):
                _runner(tmp_path, fail_fast=True).run("ds", DF, {"checks": checks})
        assert _Recorder.seen == []


class TestScore:
    @pytest.mark.parametrize(
        "node_gate, global_gate, weights",
        [
            (None, None, {}),
            (None, {"score_weights": {"row_count": 2.0}}, {"row_count": 2.0}),
            (
                {"score_weights": {"row_count": 3.0}},
                {"score_weights": {"x": 1.0}},
                {"row_count": 3.0},
            ),
        ],
    )
    def test_the_node_weights_win_over_the_global_ones(
        self, tmp_path, node_gate, global_gate, weights
    ):
        config: Dict[str, Any] = {"checks": {}}
        if node_gate:
            config["quality_gate"] = node_gate
        with (
            patch(
                "ducta.check.gate.QualityGateEvaluator.compute_score", return_value=0.5
            ) as compute,
            patch("ducta.check.gate.QualityGateEvaluator.from_config", return_value=None),
        ):
            report = _runner(tmp_path, global_gate_config=global_gate).run("ds", DF, config)
        assert compute.call_args.args[1] == weights
        assert report.score == 0.5

    def test_a_score_failure_falls_back_to_one(self, tmp_path):
        with patch(
            "ducta.check.gate.QualityGateEvaluator.compute_score",
            side_effect=RuntimeError("bad weights"),
        ):
            report = _runner(tmp_path).run("ds", DF, {"checks": {}})
        assert report.score == 1.0

    def test_a_node_gate_given_as_a_model_is_read_as_a_dict(self, tmp_path):
        gate = SimpleNamespace(model_dump=lambda exclude_none: {"min_score": 0.0})
        report = _runner(tmp_path).run("ds", DF, {"checks": {}, "quality_gate": gate})
        assert report.passed


class TestPersistenceWarnings:
    def test_a_baseline_failure_is_on_the_report(self, tmp_path):
        runner = _runner(tmp_path)
        with patch.object(runner, "_create_and_save_baseline", side_effect=OSError("disk full")):
            report = runner.run("ds", DF, {"checks": {}})
        assert report.persistence_warnings == ["Failed to create baseline: disk full"]

    def test_a_gate_result_save_failure_is_on_the_report(self, tmp_path):
        runner = _runner(tmp_path, global_gate_config={"min_score": 0.0})
        runner.storage.save_gate_result = lambda *a, **k: (_ for _ in ()).throw(OSError("ro"))
        report = runner.run("ds", DF, {"checks": {}})
        assert report.persistence_warnings == ["Failed to save gate result: ro"]

    def test_a_history_failure_is_on_the_report(self, tmp_path):
        runner = _runner(tmp_path)
        with patch.object(runner, "_append_to_history", side_effect=OSError("locked")):
            report = runner.run("ds", DF, {"checks": {}})
        assert report.persistence_warnings == ["Failed to update history: locked"]

    def test_the_gate_decision_is_recorded_in_the_history(self, tmp_path):
        runner = _runner(tmp_path, global_gate_config={"min_score": 0.0})
        runner.run("ds", DF, {"checks": {}})
        history = runner.storage.load_history("ds")
        assert history[-1]["gate_action"] is not None
