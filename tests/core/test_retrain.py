"""``retrain:`` — a scoring pipeline whose drift checks fail has Ducta run its training.

The drift was measured on every scoring run, and nothing acted on it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from ducta.core.executors.facade import PipelineExecutor
from ducta.core.results import PipelineRunResult, RunStatus
from ducta.setting.project.schema import RetrainSpec, duration_seconds

# ── the spec ─────────────────────────────────────────────────────────────────


class TestRetrainSpec:
    def test_the_defaults(self):
        spec = RetrainSpec(run="train")
        assert spec.when == ["prediction_drift"] and spec.cooldown is None

    @pytest.mark.parametrize("cooldown", ["1d", "6h", "30m", "90s"])
    def test_a_cooldown_is_a_duration(self, cooldown):
        assert RetrainSpec(run="train", cooldown=cooldown).cooldown == cooldown

    @pytest.mark.parametrize("cooldown", ["daily", "1 day", "-1h", "1w"])
    def test_anything_else_is_refused(self, cooldown):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            RetrainSpec(run="train", cooldown=cooldown)

    def test_durations(self):
        assert duration_seconds("1d") == 86400 and duration_seconds("6h") == 21600


PROJECT = "version: 2\nproject: p\npaths: {input: data, output: out}\n"
TRAIN = "type: ml\nrequires_dates: false\nnodes:\n  fit:\n    run: pipelines.m:fit\n    ml_stage: training\n    inputs: [raw]\n    outputs: [gold.m.ref]\n"


def _project(tmp_path: Path, score_retrain: str, train: str = TRAIN) -> Path:
    (tmp_path / "pipelines").mkdir()
    (tmp_path / "ducta.yaml").write_text(PROJECT)
    (tmp_path / "catalog.yaml").write_text(
        "raw: {format: csv, path: data/raw.csv}\ngold.m.ref: {format: parquet}\n"
        "gold.m.scores: {format: parquet}\n"
    )
    (tmp_path / "pipelines" / "train.yaml").write_text(train)
    (tmp_path / "pipelines" / "score.yaml").write_text(
        "type: ml\nrequires_dates: false\n"
        f"{score_retrain}\n"
        "nodes:\n  predict:\n    ml_stage: serving\n"
        "    model: {name: m, stage: production, trust_artifact: true}\n"
        "    inputs: [raw]\n    outputs: [gold.m.scores]\n"
    )
    return tmp_path


def _problems(root: Path) -> str:
    from ducta.setting.project.validation import validate_project

    try:
        validate_project(root, None)
    except Exception as e:  # noqa: BLE001 — the message lists every problem
        return str(e)
    return ""


class TestTheProjectChecksTheTarget:
    def test_a_valid_retrain_compiles_into_the_pipeline(self, tmp_path):
        from ducta.setting.project.compiler import compile_project
        from ducta.setting.project.validation import validate_project

        root = _project(tmp_path, "retrain: {run: train, cooldown: 1d}")
        docs = compile_project(validate_project(root, None))
        assert docs["pipelines_config"]["score"]["retrain"] == {
            "run": "train",
            "when": ["prediction_drift"],
            "cooldown": "1d",
        }

    def test_an_unknown_pipeline(self, tmp_path):
        assert "'trian', which is not a pipeline" in _problems(
            _project(tmp_path, "retrain: {run: trian}")
        )

    def test_itself(self, tmp_path):
        assert "cannot run the pipeline itself" in _problems(
            _project(tmp_path, "retrain: {run: score}")
        )

    def test_a_target_that_is_not_ml(self, tmp_path):
        batch = TRAIN.replace("type: ml", "type: batch").replace("    ml_stage: training\n", "")
        assert "it must be type: ml" in _problems(
            _project(tmp_path, "retrain: {run: train}", train=batch)
        )

    def test_a_target_with_a_retrain_of_its_own(self, tmp_path):
        looping = TRAIN.replace(
            "requires_dates: false\n", "requires_dates: false\nretrain: {run: score}\n"
        )
        assert "one retrain may not trigger another" in _problems(
            _project(tmp_path, "retrain: {run: train}", train=looping)
        )


# ── the trigger ──────────────────────────────────────────────────────────────


class _Executor:
    """``PipelineExecutor._maybe_retrain`` with a recorded ``run_pipeline``."""

    def __init__(self, tmp_path: Path, **context: Any) -> None:
        self.executor = object.__new__(PipelineExecutor)
        self.executor.context = SimpleNamespace(**context)
        self.executor.settings = SimpleNamespace(run_certificate_dir=str(tmp_path / "runs"))
        self.calls: List[Dict[str, Any]] = []
        self.seen_triggered_by: List[Any] = []

        def run_pipeline(pipeline_name: str, **kwargs: Any) -> PipelineRunResult:
            self.calls.append({"pipeline": pipeline_name, **kwargs})
            self.seen_triggered_by.append(getattr(self.executor.context, "triggered_by", None))
            return PipelineRunResult(pipeline=pipeline_name, run_id="t1")

        self.executor.run_pipeline = run_pipeline  # type: ignore[method-assign]

    def retrain(self, spec, failed, hyperparams=None):
        return self.executor._maybe_retrain(
            "score", {"retrain": spec}, "s1", set(failed), hyperparams, None, None
        )


SPEC = {"run": "train", "when": ["prediction_drift"]}


def test_a_failed_drift_check_runs_the_training(tmp_path):
    ex = _Executor(tmp_path)
    outcome = ex.retrain(SPEC, {"prediction_drift", "prediction_rate"})
    assert [c["pipeline"] for c in ex.calls] == ["train"]
    assert outcome == {
        "pipeline": "train",
        "checks": ["prediction_drift"],
        "run_id": "t1",
        "status": RunStatus.SUCCESS.value,
    }
    # The training run's certificate says what started it, and only that run does.
    assert ex.seen_triggered_by == [
        {"run_id": "s1", "pipeline": "score", "checks": ["prediction_drift"]}
    ]
    assert ex.executor.context.triggered_by is None


def test_other_failed_checks_do_not(tmp_path):
    ex = _Executor(tmp_path)
    assert ex.retrain(SPEC, {"prediction_rate"}) is None
    assert ex.retrain(None, {"prediction_drift"}) is None
    assert ex.calls == []


@pytest.mark.parametrize(
    "context, hyperparams",
    [
        ({"reproduction_of": "r0"}, None),
        ({"sample_rows": 100}, None),
        ({}, {"sweep_index": 2, "max_depth": 3}),
    ],
)
def test_never_from_a_reproduction_a_sample_or_a_trial(tmp_path, context, hyperparams):
    """They must not change the models in production."""
    ex = _Executor(tmp_path, **context)
    outcome = ex.retrain(SPEC, {"prediction_drift"}, hyperparams)
    assert ex.calls == [] and outcome["skipped"] == "not a production run"


def _certificate(tmp_path: Path, run_id: str, pipeline: str, ended: datetime, **extra) -> None:
    import json

    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "certificate.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "pipeline": pipeline,
                "status": "success",
                "ended_at": ended.isoformat(),
                **extra,
            }
        )
    )


class TestCooldown:
    SPEC = {**SPEC, "cooldown": "1d"}

    def test_within_it_nothing_runs(self, tmp_path):
        _certificate(tmp_path, "a", "train", datetime.now(timezone.utc) - timedelta(hours=2))
        ex = _Executor(tmp_path)
        assert ex.retrain(self.SPEC, {"prediction_drift"})["skipped"] == "cooldown 1d"
        assert ex.calls == []

    def test_after_it_the_training_runs(self, tmp_path):
        _certificate(tmp_path, "a", "train", datetime.now(timezone.utc) - timedelta(days=2))
        ex = _Executor(tmp_path)
        assert ex.retrain(self.SPEC, {"prediction_drift"})["run_id"] == "t1"

    def test_a_reproduction_or_another_pipeline_does_not_count(self, tmp_path):
        recent = datetime.now(timezone.utc) - timedelta(hours=1)
        _certificate(tmp_path, "a", "train", recent, reproduction_of="x")
        _certificate(tmp_path, "b", "score", recent)
        ex = _Executor(tmp_path)
        assert ex.retrain(self.SPEC, {"prediction_drift"})["run_id"] == "t1"


def test_a_failed_training_is_reported_not_raised(tmp_path):
    ex = _Executor(tmp_path)

    def boom(pipeline_name: str, **kwargs: Any) -> PipelineRunResult:
        error = RuntimeError("training failed")
        error.run_result = PipelineRunResult(pipeline=pipeline_name, run_id="t9")  # type: ignore[attr-defined]
        raise error

    ex.executor.run_pipeline = boom  # type: ignore[method-assign]
    outcome = ex.retrain(SPEC, {"prediction_drift"})
    assert outcome["status"] == "failed" and outcome["run_id"] == "t9"
    assert ex.executor.context.triggered_by is None


# ── the evidence the trigger reads ───────────────────────────────────────────


def test_the_gate_result_keeps_the_failed_checks():
    from ducta.check.core import CheckResult, QualityReport
    from ducta.check.gate import QualityGateEvaluator

    report = QualityReport(
        dataset_name="d",
        passed=False,
        results=[
            CheckResult(check_name="prediction_drift", passed=False, severity="warning"),
            CheckResult(check_name="prediction_contract", passed=True),
            CheckResult(check_name="prediction_rate", passed=False),
        ],
    )
    gate = QualityGateEvaluator.from_config(report, node_gate_cfg={"max_errors": 0})
    assert gate.failed_checks == ["prediction_drift", "prediction_rate"]


def test_a_blocked_run_still_names_its_failed_checks():
    """A gate that blocks on drift is when retraining matters most."""
    from ducta.check.gate import GateAction, GateResult
    from ducta.core.execution.quality import QualityCheckExecutor

    recorded: List[Dict[str, Any]] = []
    phase = object.__new__(QualityCheckExecutor)
    phase._ledger = SimpleNamespace(record_quality=recorded.append)
    error = Exception("blocked")
    error.gate_result = GateResult(  # type: ignore[attr-defined]
        gate_name="g",
        passed=False,
        score=0.0,
        action=GateAction.BLOCK,
        failed_checks=["prediction_drift"],
    )
    phase._deposit_quality_abort("score", "data_quality", error)
    assert recorded[0]["failed_checks"] == ["prediction_drift"]


class TestARetrainThatDidNotSucceedStillStartsTheCooldown:
    """A retrain whose model the policy refused failed the training run; it did not
    count, and every scoring run after it retrained again."""

    SPEC = {**SPEC, "cooldown": "1d"}

    def test_a_failed_retrain_counts(self, tmp_path):
        recent = datetime.now(timezone.utc) - timedelta(minutes=5)
        _certificate(tmp_path, "a", "train", recent, status="failed", triggered_by={"run_id": "s0"})
        ex = _Executor(tmp_path)
        assert ex.retrain(self.SPEC, {"prediction_drift"})["skipped"] == "cooldown 1d"
        assert ex.calls == []

    def test_a_failed_training_nobody_triggered_does_not(self, tmp_path):
        recent = datetime.now(timezone.utc) - timedelta(minutes=5)
        _certificate(tmp_path, "a", "train", recent, status="failed")
        ex = _Executor(tmp_path)
        assert ex.retrain(self.SPEC, {"prediction_drift"})["run_id"] == "t1"


# ── how it is reported ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "retrain, exit_ok",
    [
        (
            {
                "pipeline": "train",
                "checks": ["prediction_drift"],
                "run_id": "t",
                "status": "success",
            },
            True,
        ),
        (
            {
                "pipeline": "train",
                "checks": ["prediction_drift"],
                "run_id": "t",
                "status": "failed",
            },
            False,
        ),
        (
            {
                "pipeline": "train",
                "checks": ["prediction_drift"],
                "run_id": "t",
                "status": "gate_blocked",
            },
            False,
        ),
        (
            {
                "pipeline": "train",
                "checks": ["prediction_drift"],
                "run_id": "t",
                "status": "skipped",
            },
            False,
        ),
        ({"pipeline": "train", "checks": ["prediction_drift"], "skipped": "cooldown 1d"}, True),
    ],
)
def test_only_a_successful_retrain_exits_zero(retrain, exit_ok):
    """A training run its own gate blocked was reported as "retrained", exit code 0."""
    from ducta.console.core import ExitCode
    from ducta.console.execution import _outcome_code

    result = PipelineRunResult(pipeline="score", run_id="s1")
    result.retrain = retrain
    assert (_outcome_code(result) == ExitCode.SUCCESS.value) is exit_ok


def test_the_result_carries_the_retrain():
    """The API and structured logs read ``to_dict()``, which left it out."""
    result = PipelineRunResult(pipeline="score", run_id="s1")
    assert result.to_dict()["retrain"] is None
    result.retrain = {"pipeline": "train", "run_id": "t1", "status": "success", "checks": ["x"]}
    assert result.to_dict()["retrain"]["run_id"] == "t1"


def test_the_compact_summary_names_it():
    from ducta.console.ux.view import _retrain_row

    assert _retrain_row({"pipeline": "train", "skipped": "cooldown 1d", "checks": ["d"]}) == (
        "train not run (cooldown 1d) — d failed"
    )
    row = _retrain_row(
        {
            "pipeline": "train",
            "run_id": "abcdef0123456789",
            "status": "gate_blocked",
            "checks": ["d"],
        }
    )
    assert row.startswith("train run ") and "gate_blocked — d failed" in row


def test_the_scoring_runs_id_is_back_on_the_context_after_the_retrain(tmp_path):
    """The training run stamped its own ``_run_id`` on the shared context, and the API,
    which links an execution's certificate from it, linked the scoring run to the
    training run's certificate."""
    ex = _Executor(tmp_path, _run_id="s1")
    inner = ex.executor.run_pipeline

    def run_pipeline(pipeline_name: str, **kwargs: Any) -> PipelineRunResult:
        ex.executor.context._run_id = "t1"  # what the training run's ledger does
        return inner(pipeline_name, **kwargs)

    ex.executor.run_pipeline = run_pipeline  # type: ignore[method-assign]
    ex.retrain(SPEC, {"prediction_drift"})
    assert ex.executor.context._run_id == "s1"


def test_the_api_records_the_retrain_on_the_execution():
    from ducta_server.execution.runner import _link_certificate

    attached: Dict[str, Any] = {}
    manager = SimpleNamespace(
        attach_certificate=lambda eid, rid: attached.update(certificate=rid),
        attach_retrain=lambda eid, retrain: attached.update(retrain=retrain),
    )
    retrain = {"pipeline": "train", "checks": ["prediction_drift"], "run_id": "t1"}
    _link_certificate(SimpleNamespace(_run_id="s1", _retrain=retrain), manager, "e1")
    assert attached == {"certificate": "s1", "retrain": retrain}
