"""``ExperimentTracker.list_runs(with_metrics=True)``: the final value of each metric."""

from __future__ import annotations

import pytest

from ducta.mlrun.experiment_tracking import ExperimentTracker, RunStatus
from ducta.mlrun.storage import LocalStorageBackend


@pytest.fixture
def tracker(tmp_path):
    return ExperimentTracker(storage=LocalStorageBackend(base_path=str(tmp_path / "mlops")))


def _finished_run(tracker):
    experiment = tracker.create_experiment("churn")
    run = tracker.start_run(experiment_id=experiment.experiment_id, name="r")
    tracker.log_metric(run.run_id, "loss", 0.9, step=0)
    tracker.log_metric(run.run_id, "loss", 0.4, step=1)
    tracker.log_metric(run.run_id, "auc", 0.88)
    tracker.end_run(run.run_id, RunStatus.COMPLETED)
    return experiment.experiment_id


class TestListRunsWithMetrics:
    def test_each_metric_is_its_latest_point(self, tracker):
        experiment_id = _finished_run(tracker)

        (item,) = tracker.list_runs(experiment_id, with_metrics=True)

        assert set(item["metrics"]) == {"loss", "auc"}
        (last_loss,) = item["metrics"]["loss"]
        assert last_loss["value"] == pytest.approx(0.4) and last_loss["step"] == 1
        assert item["metrics"]["auc"][0]["value"] == pytest.approx(0.88)

    def test_without_the_flag_only_the_metric_names_are_listed(self, tracker):
        experiment_id = _finished_run(tracker)

        (item,) = tracker.list_runs(experiment_id)

        assert "metrics" not in item
        assert sorted(item["metric_keys"]) == ["auc", "loss"]
