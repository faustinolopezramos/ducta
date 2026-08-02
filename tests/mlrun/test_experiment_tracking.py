"""Unit tests for ducta.mlrun.experiment_tracking.ExperimentTracker."""

from __future__ import annotations

import pytest

from ducta.mlrun.experiment_tracking import ExperimentTracker, RunStatus
from ducta.mlrun.storage import LocalStorageBackend


@pytest.fixture
def tracker(tmp_path):
    storage = LocalStorageBackend(base_path=str(tmp_path / "mlops"), enable_circuit_breaker=False)
    return ExperimentTracker(storage=storage, tracking_path="experiment_tracking")


def _start_run(tracker):
    exp = tracker.create_experiment("exp1")
    return tracker.start_run(experiment_id=exp.experiment_id, name="run1")


class TestGetRunReturnsIsolatedCopy:
    def test_mutating_returned_run_does_not_affect_tracker_state(self, tracker):
        run = _start_run(tracker)
        tracker.log_metric(run.run_id, "acc", 0.9)

        fetched = tracker.get_run(run.run_id)
        fetched.tags["mutated"] = "yes"
        fetched.parameters["injected"] = 123

        fetched_again = tracker.get_run(run.run_id)
        assert "mutated" not in fetched_again.tags
        assert "injected" not in fetched_again.parameters

    def test_get_run_reflects_current_metrics(self, tracker):
        run = _start_run(tracker)
        tracker.log_metric(run.run_id, "acc", 0.9)
        fetched = tracker.get_run(run.run_id)
        assert "acc" in fetched.metrics


class TestCloseRunIdempotency:
    def test_close_run_on_terminal_run_does_not_overwrite_status(self, tracker):
        run = _start_run(tracker)
        tracker.end_run(run.run_id, status=RunStatus.COMPLETED)

        result = tracker.close_run(run.run_id, status=RunStatus.FAILED)

        assert result.status == RunStatus.COMPLETED
        reloaded = tracker.get_run(run.run_id)
        assert reloaded.status == RunStatus.COMPLETED

    def test_close_run_with_allow_override_does_overwrite(self, tracker):
        run = _start_run(tracker)
        tracker.end_run(run.run_id, status=RunStatus.COMPLETED)

        result = tracker.close_run(run.run_id, status=RunStatus.FAILED, allow_override=True)

        assert result.status == RunStatus.FAILED


class TestFlushCounterOnlyResetsOnSuccess:
    def test_counter_not_reset_when_flush_fails(self, tracker, monkeypatch):
        run = _start_run(tracker)
        tracker.metric_buffer_size = 2

        call_count = {"n": 0}
        real_write_json = tracker.storage.write_json

        def flaky_write_json(*args, **kwargs):
            call_count["n"] += 1
            raise RuntimeError("transient storage failure")

        monkeypatch.setattr(tracker.storage, "write_json", flaky_write_json)

        tracker.log_metric(run.run_id, "acc", 0.1)
        tracker.log_metric(run.run_id, "acc", 0.2)  # hits buffer_size=2, flush fails

        assert tracker._metric_counts[run.run_id] == 2  # not reset to 0 on failed flush

        monkeypatch.setattr(tracker.storage, "write_json", real_write_json)
        tracker.log_metric(run.run_id, "acc", 0.3)  # buffer_size still exceeded, retries flush
        assert tracker._metric_counts[run.run_id] == 0  # successful flush resets it
