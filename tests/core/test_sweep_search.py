"""Unit tests for ducta.core.sweep.run_search — the trial driver.

run_search is what connects a search strategy to actual pipeline execution:
it asks for a hyperparameter set, runs one trial, reads the objective metric
off the resulting PipelineRunResult, and reports it back. Getting the failure
paths right matters more than the happy path — a trial that crashes, gets
blocked by a quality gate, or logs no metric must count toward the budget
without ever being able to win.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from ducta.core.sweep import run_search
from ducta.mlrun.hyperparams import HyperparamConfig
from ducta.mlrun.search import build_search_strategy


@dataclass
class FakeResult:
    """Stands in for PipelineRunResult (only the fields run_search reads)."""

    metrics: Dict[str, float] = field(default_factory=dict)
    gate_blocked: Dict[str, Any] = field(default_factory=dict)


def _strategy(n_trials: int = 4, direction: str = "maximize"):
    config = HyperparamConfig.from_dict(
        {
            "algorithm": "random",
            "n_trials": n_trials,
            "objective": {"metric": "val_f1", "type": direction},
            "search_space": {"depth": [3, 5, 7]},
        }
    )
    return build_search_strategy(config, seed=42)


class TestRunSearchHappyPath:
    def test_runs_every_trial_and_reports_the_best(self):
        scores = iter([0.5, 0.9, 0.2, 0.7])
        calls = []

        def run_trial(params, index):
            calls.append((index, params))
            return FakeResult(metrics={"val_f1": next(scores)})

        outcome = run_search(_strategy(), "val_f1", run_trial)

        assert len(outcome.trials) == 4
        assert [i for i, _ in calls] == [1, 2, 3, 4]
        assert outcome.failures == 0
        assert outcome.succeeded == 4
        assert outcome.best_score == 0.9

    def test_minimize_direction_selects_the_lowest(self):
        scores = iter([10.0, 3.0, 8.0, 6.0])

        def run_trial(params, index):
            return FakeResult(metrics={"val_f1": next(scores)})

        outcome = run_search(_strategy(direction="minimize"), "val_f1", run_trial)
        assert outcome.best_score == 3.0
        assert outcome.direction == "minimize"

    def test_search_id_is_recorded_on_the_outcome(self):
        def run_trial(params, index):
            return FakeResult(metrics={"val_f1": 0.5})

        outcome = run_search(_strategy(n_trials=2), "val_f1", run_trial, search_id="search-abc")
        assert outcome.search_id == "search-abc"
        assert outcome.metric == "val_f1"


class TestRunSearchFailurePaths:
    def test_a_raising_trial_does_not_end_the_search(self):
        """One bad trial must not abort the remaining budget."""
        attempts = {"n": 0}

        def run_trial(params, index):
            attempts["n"] += 1
            if index == 2:
                raise RuntimeError("node exploded")
            return FakeResult(metrics={"val_f1": 0.5})

        outcome = run_search(_strategy(), "val_f1", run_trial)

        assert attempts["n"] == 4  # all four still ran
        assert outcome.failures == 1
        assert outcome.best_score == 0.5
        failed = [t for t in outcome.trials if t.failed]
        assert "node exploded" in failed[0].reason

    def test_a_gate_blocked_trial_counts_as_failed(self):
        """A blocked gate does not raise, so counting only exceptions would
        report a trial that produced nothing as a success."""

        def run_trial(params, index):
            if index == 1:
                return FakeResult(gate_blocked={"train_model": "row count below floor"})
            return FakeResult(metrics={"val_f1": 0.5})

        outcome = run_search(_strategy(), "val_f1", run_trial)

        assert outcome.failures == 1
        blocked = [t for t in outcome.trials if t.failed][0]
        assert "quality gate" in blocked.reason
        assert blocked.score is None

    def test_a_trial_missing_the_objective_metric_is_failed_with_a_useful_reason(self):
        def run_trial(params, index):
            return FakeResult(metrics={"test_f1": 0.9, "baseline_f1": 0.1})

        outcome = run_search(_strategy(n_trials=1), "val_f1", run_trial)

        assert outcome.failures == 1
        assert outcome.best_params is None
        reason = outcome.trials[0].reason
        assert "val_f1" in reason
        # names the metrics that WERE logged, so the mismatch is obvious
        assert "test_f1" in reason and "baseline_f1" in reason

    def test_all_trials_failing_leaves_no_best(self):
        def run_trial(params, index):
            raise RuntimeError("always fails")

        outcome = run_search(_strategy(), "val_f1", run_trial)

        assert outcome.best_params is None
        assert outcome.best_score is None
        assert outcome.failures == len(outcome.trials) == 4

    def test_a_nan_objective_cannot_win(self):
        scores = iter([float("nan"), 0.3, float("nan"), 0.1])

        def run_trial(params, index):
            return FakeResult(metrics={"val_f1": next(scores)})

        outcome = run_search(_strategy(), "val_f1", run_trial)
        assert outcome.best_score == 0.3
