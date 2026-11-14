"""The ``BaseExecutor`` helpers every executor (batch, ML, hybrid) calls around a run.

The executor is built without ``__init__`` (which wires readers, writers and the
quality manager) and given only the attributes each helper reads, so a helper
that starts reading something else fails here instead of passing by accident.
"""

from __future__ import annotations

import json
import random
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest
from loguru import logger

from ducta.core.executors import base as base_mod
from ducta.core.executors.base import BaseExecutor


def _executor(**attrs: Any) -> BaseExecutor:
    executor = object.__new__(BaseExecutor)
    defaults: Dict[str, Any] = {
        "settings": SimpleNamespace(random_seed=None, quality={}),
        "context": SimpleNamespace(),
        "is_ml_layer": False,
        "max_workers": 1,
        "last_run_metrics": {},
        "last_mlops_run_id": None,
        "_mlops_pipeline_name": None,
    }
    for name, value in {**defaults, **attrs}.items():
        setattr(executor, name, value)
    return executor


@pytest.fixture
def logs():
    """What the helpers log. ``ducta`` disables its logger at import (the CLI enables it)."""
    lines: List[str] = []
    sink = logger.add(lambda m: lines.append(m.record["message"]), level="DEBUG")
    logger.enable("ducta")
    try:
        yield lines
    finally:
        logger.disable("ducta")
        logger.remove(sink)


class TestGlobalSeed:
    def test_no_seed_leaves_the_rngs_alone(self, logs):
        _executor()._apply_global_seed()
        assert not any("random seed" in line for line in logs)

    def test_the_seed_makes_random_and_numpy_repeat(self):
        np = pytest.importorskip("numpy")
        executor = _executor(settings=SimpleNamespace(random_seed=7, quality={}))
        executor._apply_global_seed()
        first = (random.random(), float(np.random.rand()))
        executor._apply_global_seed()
        assert (random.random(), float(np.random.rand())) == first

    def test_parallel_ml_nodes_are_warned_the_global_seed_is_not_enough(self, logs):
        executor = _executor(
            settings=SimpleNamespace(random_seed=7, quality={}), is_ml_layer=True, max_workers=4
        )
        executor._apply_global_seed()
        assert any("not reproducible under parallelism" in line for line in logs)

    def test_an_ml_run_without_a_seed_is_warned(self, logs):
        _executor(is_ml_layer=True)._log_pipeline_start("train", {}, "ML")
        assert any("WITHOUT random_seed" in line for line in logs)


def _output(report_type: str, node: str, path: str) -> SimpleNamespace:
    return SimpleNamespace(report_type=report_type, node_name=node, output_path=path)


class TestQualitySummary:
    OUTPUTS = [
        _output("validation", "clean", "q/clean/v.json"),
        _output("sanity", "clean", "q/clean/s.json"),
        _output("validation", "gold", "q/gold/v.json"),
    ]

    def test_written_when_enabled(self, tmp_path):
        target = tmp_path / "summary" / "global"
        executor = _executor(
            context=SimpleNamespace(quality_output_paths=self.OUTPUTS),
            settings=SimpleNamespace(
                random_seed=None,
                quality={"global_summary": {"enabled": True, "output_path": str(target)}},
            ),
        )
        executor._aggregate_and_persist_quality_summary()
        summary = json.loads((tmp_path / "summary" / "global.json").read_text())
        assert summary["total_outputs"] == 3
        assert summary["outputs_by_type"]["validation"] == [
            {"node": "clean", "path": "q/clean/v.json"},
            {"node": "gold", "path": "q/gold/v.json"},
        ]
        assert summary["outputs_by_node"]["clean"] == [
            {"type": "validation", "path": "q/clean/v.json"},
            {"type": "sanity", "path": "q/clean/s.json"},
        ]

    def test_the_documented_switch_writes_one_file_per_run_next_to_the_reports(
        self, tmp_path, monkeypatch
    ):
        """``quality.output.global_summary: true`` was validated, then ignored."""
        from ducta.check.output_manager import QualityOutputManager
        from ducta.core.ledger import RunLedger

        monkeypatch.chdir(tmp_path)  # nothing may land in the working directory
        quality_dir = tmp_path / "data" / "dev" / "quality"
        context = SimpleNamespace(quality_output_paths=[], global_config={})
        executor = _executor(
            context=context,
            settings=SimpleNamespace(
                random_seed=None,
                quality={"output": {"global_summary": True, "base_path": str(quality_dir)}},
            ),
            quality_output_manager=QualityOutputManager(context),
            _mlops_pipeline_name="silver.sales",
        )
        for run_id in ("r1", "r2"):
            RunLedger.start(context, run_id)
            context.quality_output_paths.extend(self.OUTPUTS)
            executor._aggregate_and_persist_quality_summary()

        folder = quality_dir / "global_summary" / "silver.sales"
        assert sorted(p.name for p in folder.iterdir()) == ["r1.json", "r2.json"]
        # Each run's summary lists its own reports, not the previous run's too.
        assert json.loads((folder / "r2.json").read_text())["total_outputs"] == 3
        assert sorted(p.name for p in tmp_path.iterdir()) == ["data"]

    def test_not_written_unless_enabled(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        executor = _executor(context=SimpleNamespace(quality_output_paths=self.OUTPUTS))
        executor._aggregate_and_persist_quality_summary()
        assert list(tmp_path.iterdir()) == []

    @pytest.mark.parametrize(
        "context", [SimpleNamespace(), SimpleNamespace(quality_output_paths=[])]
    )
    def test_nothing_to_aggregate(self, context, logs):
        _executor(context=context)._aggregate_and_persist_quality_summary()
        assert not any("Aggregating" in line for line in logs)

    def test_a_write_failure_never_fails_the_run(self, tmp_path, logs):
        blocker = tmp_path / "file"
        blocker.write_text("x")
        _executor()._persist_global_quality_summary(
            {"validation": self.OUTPUTS[:1]}, {}, {"output_path": str(blocker / "sub" / "s")}
        )
        assert any("Failed to persist global quality summary" in line for line in logs)


class TestPreflightSanity:
    def test_no_node_with_sanity_checks_runs_nothing(self, monkeypatch):
        runner = MagicMock()
        monkeypatch.setattr(base_mod, "SanityPhaseRunner", runner)
        nodes = {"a": {}, "b": {"sanity_checks": {"enabled": False}}}
        assert _executor()._run_preflight_sanity_checks(nodes) == {}
        runner.assert_not_called()

    def test_runs_fail_fast_with_the_project_profiles_and_the_dates(self, monkeypatch):
        report = SimpleNamespace(errors_count=0)
        runner = MagicMock()
        runner.return_value.run_preflight_checks.return_value = {"a": report}
        monkeypatch.setattr(base_mod, "SanityPhaseRunner", runner)
        monkeypatch.setattr(base_mod, "QualityReporter", MagicMock())
        monkeypatch.setattr(
            "ducta.check.profiles.load_profiles", lambda gs: {"strict": gs["quality"]}
        )
        context = SimpleNamespace(global_config={"quality": "p"})
        nodes = {"a": {"sanity_checks": {"row_count": {"min": 1}}}}

        executor = _executor(context=context, _mlops_pipeline_name="daily")
        reports = executor._run_preflight_sanity_checks(nodes, "2026-01-01", "2026-01-02")

        assert reports == {"a": report}
        runner.assert_called_once_with(fail_fast=True, profiles={"strict": "p"})
        runner.return_value.run_preflight_checks.assert_called_once_with(
            {"nodes": nodes},
            context,
            pipeline_name="daily",
            start_date="2026-01-01",
            end_date="2026-01-02",
        )

    def test_a_failed_check_is_a_data_error_not_an_unexpected_one(self, monkeypatch):
        """A check failing in the preflight (fail_fast) used to escape as a bare
        QualityCheckError: the CLI printed "Unexpected error" and exited 1, where the
        same check failing inside the node exits 4."""
        from ducta.check import QualityCheckError
        from ducta.core.errors import SanityCheckFailedError

        runner = MagicMock()
        runner.return_value.run_preflight_checks.side_effect = QualityCheckError(
            "schema", "Missing column", node_name="extract"
        )
        monkeypatch.setattr(base_mod, "SanityPhaseRunner", runner)
        nodes = {"extract": {"sanity_checks": {"checks": {"schema": {}}}}}

        with pytest.raises(SanityCheckFailedError) as raised:
            _executor()._run_preflight_sanity_checks(nodes)

        assert raised.value.exit_code == 4
        assert "extract" in str(raised.value) and "Missing column" in str(raised.value)


class TestEndMlopsRun:
    def test_nothing_to_end(self):
        integration = MagicMock()
        executor = _executor()
        executor._end_mlops_run(True, integration, None)
        executor._end_mlops_run(True, None, "r1")
        integration.end_pipeline_run.assert_not_called()
        assert executor.last_mlops_run_id is None

    def test_success_keeps_the_run_metrics_and_id(self):
        integration = MagicMock()
        integration.end_pipeline_run.return_value = {"rmse": 1.5}
        executor = _executor()
        executor._end_mlops_run(True, integration, "r1")
        integration.end_pipeline_run.assert_called_once_with("r1")
        assert executor.last_run_metrics == {"rmse": 1.5}
        assert executor.last_mlops_run_id == "r1"

    def test_a_failed_run_is_recorded_as_failed(self):
        from ducta.mlrun.experiment_tracking import RunStatus

        integration = MagicMock()
        integration.end_pipeline_run.return_value = None
        executor = _executor()
        executor._end_mlops_run(False, integration, "r1")
        integration.end_pipeline_run.assert_called_once_with("r1", status=RunStatus.FAILED)
        assert executor.last_run_metrics == {}

    def test_a_tracking_failure_does_not_mask_the_run(self, logs):
        integration = MagicMock()
        integration.end_pipeline_run.side_effect = RuntimeError("tracking down")
        executor = _executor()
        executor._end_mlops_run(True, integration, "r1")
        assert any("tracking record may be incomplete" in line for line in logs)
        assert executor.last_mlops_run_id is None
