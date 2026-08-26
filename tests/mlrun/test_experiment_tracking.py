"""Unit tests for ducta.mlrun.experiment_tracking.ExperimentTracker."""

from __future__ import annotations

from unittest.mock import patch

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
        real_append_lines = tracker.storage.append_lines

        def flaky_append_lines(*args, **kwargs):
            call_count["n"] += 1
            raise RuntimeError("transient storage failure")

        # _flush_metrics appends incrementally (append_lines), not a full
        # rewrite (write_json) — patch the method it actually calls now.
        monkeypatch.setattr(tracker.storage, "append_lines", flaky_append_lines)

        tracker.log_metric(run.run_id, "acc", 0.1)
        tracker.log_metric(run.run_id, "acc", 0.2)  # hits buffer_size=2, flush fails

        assert tracker._metric_counts[run.run_id] == 2  # not reset to 0 on failed flush

        monkeypatch.setattr(tracker.storage, "append_lines", real_append_lines)
        tracker.log_metric(run.run_id, "acc", 0.3)  # buffer_size still exceeded, retries flush
        assert tracker._metric_counts[run.run_id] == 0  # successful flush resets it


class TestIncrementalMetricFlush:
    """`_flush_metrics` used to rewrite the run's entire metrics history on
    every flush — O(M^2) total I/O across M logged points for a run with
    frequent flushes. It now appends only the points logged since the
    previous flush, and writes the full consolidated snapshot exactly once,
    when the run ends."""

    def test_flush_only_writes_new_points_since_last_flush(self, tracker, monkeypatch):
        run = _start_run(tracker)
        tracker.metric_buffer_size = 1  # flush on every log_metric call

        appended = []
        real_append_lines = tracker.storage.append_lines

        def spy_append_lines(lines, path):
            appended.append(list(lines))
            return real_append_lines(lines, path)

        monkeypatch.setattr(tracker.storage, "append_lines", spy_append_lines)

        tracker.log_metric(run.run_id, "acc", 0.1)  # flush #1
        tracker.log_metric(run.run_id, "acc", 0.2)  # flush #2

        assert len(appended) == 2
        assert len(appended[0]) == 1  # not 1 (cumulative would be 1, 2)
        assert len(appended[1]) == 1  # only the new point, not a full rewrite

    def test_end_run_consolidates_full_json_snapshot(self, tracker):
        run = _start_run(tracker)
        tracker.metric_buffer_size = 100  # high enough that auto-flush never fires
        tracker.log_metric(run.run_id, "acc", 0.1)
        tracker.log_metric(run.run_id, "acc", 0.2)
        tracker.log_metric(run.run_id, "loss", 1.5)

        tracker.end_run(run.run_id, status=RunStatus.COMPLETED)

        snapshot_path = f"experiment_tracking/metrics/{run.experiment_id}/{run.run_id}_metrics.json"
        data = tracker.storage.read_json(snapshot_path)
        assert len(data["acc"]) == 2
        assert len(data["loss"]) == 1

    def test_get_run_on_active_run_reflects_uncommitted_metrics(self, tracker):
        # Regression guard: get_run for an active run must keep reading from
        # in-memory state, not from the incrementally-flushed .jsonl on disk
        # (which never holds a directly re-readable full snapshot mid-run).
        run = _start_run(tracker)
        tracker.metric_buffer_size = 1000  # never auto-flushes
        tracker.log_metric(run.run_id, "acc", 0.42)

        fetched = tracker.get_run(run.run_id)
        assert fetched.metrics["acc"].get_all()[0].value == 0.42

    def test_eviction_during_active_run_logs_warning_on_next_flush(self, tracker):
        run = _start_run(tracker)
        tracker.max_metrics_per_key = 3
        tracker.metric_buffer_size = 1  # flush on every log_metric call

        with patch("ducta.mlrun.experiment_tracking.logger") as mock_logger:
            for i in range(5):  # exceeds max_metrics_per_key=3, window evicts
                tracker.log_metric(run.run_id, "acc", 0.1 * i)

            warning_texts = [str(c.args[0]) for c in mock_logger.warning.call_args_list]
        assert any("evicted entries" in text for text in warning_texts)

    def test_no_evictions_no_warning(self, tracker):
        run = _start_run(tracker)
        tracker.metric_buffer_size = 1

        with patch("ducta.mlrun.experiment_tracking.logger") as mock_logger:
            for i in range(3):
                tracker.log_metric(run.run_id, "acc", 0.1 * i)

            warning_texts = [str(c.args[0]) for c in mock_logger.warning.call_args_list]
        assert not any("evicted entries" in text for text in warning_texts)
