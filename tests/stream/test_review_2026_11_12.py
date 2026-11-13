"""Regressions for the 2026-11-12 review of ducta.stream (no Spark needed).

The micro-batch writes are tested on a real session in
tests/integration/test_streaming_review_2026_11_12_live.py.
"""

from __future__ import annotations

import os
import threading
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from ducta.stream import journal
from ducta.stream.micro_batch import _BufferedStorage

# ---------------------------------------------------------------------------
# Baseline and history are state, not reports
# ---------------------------------------------------------------------------


class _Storage:
    def __init__(self, fmt: str) -> None:
        self.format = fmt
        self.calls: List[str] = []

    def save_baseline(self, *a: Any) -> None:
        self.calls.append("save_baseline")

    def append_history(self, *a: Any) -> None:
        self.calls.append("append_history")

    def save_report(self, *a: Any) -> None:
        self.calls.append("save_report")


def test_the_baseline_is_never_held_back():
    inner = _Storage("parquet")
    buffered = _BufferedStorage(inner)
    buffered.save_baseline({}, "d")
    buffered.save_report({}, "r", "d")
    assert inner.calls == ["save_baseline"]  # the report waits for the verdict


@pytest.mark.parametrize("fmt, at_once", [("json", True), ("parquet", False), ("delta", False)])
def test_a_local_json_history_is_written_every_batch(fmt, at_once):
    inner = _Storage(fmt)
    _BufferedStorage(inner).append_history("d", {"row_count": 1})
    assert (inner.calls == ["append_history"]) is at_once


# ---------------------------------------------------------------------------
# The journal's totals survive rotation; old runs are pruned
# ---------------------------------------------------------------------------


def test_rotation_keeps_the_runs_totals(tmp_path, monkeypatch):
    monkeypatch.setattr(journal, "MAX_BATCHES_BYTES", 2000)
    run = journal.StreamRunJournal(str(tmp_path), "p", "run1", "exec1", ["clean"])
    for batch in range(200):
        run.record("progress", {"node": "clean", "batch_id": batch, "rows": 10})
        run.record(
            "batch",
            {
                "node": "clean",
                "batch_id": batch,
                "rows_written": 9,
                "rows_quarantined": 1,
                "gate": "pass",
            },
        )
    totals = journal.summarize(run.dir)["clean"]
    assert (totals["batches"], totals["rows_in"]) == (200, 2000)
    assert (totals["rows_written"], totals["rows_quarantined"]) == (1800, 200)
    assert (totals["first_batch"], totals["last_batch"], totals["gate"]) == (0, 199, {"pass": 200})


def test_old_finished_runs_are_pruned_but_never_a_running_one(tmp_path, monkeypatch):
    monkeypatch.setattr(journal, "KEEP_RUNS", 2)
    old_running = journal.StreamRunJournal(str(tmp_path), "p", "r0", "e0", ["n"])
    old_running.run["started_at"] = "2000-01-01T00:00:00+00:00"
    old_running._write_run()  # still "starting", its process (this one) alive
    for i in range(1, 5):
        done = journal.StreamRunJournal(str(tmp_path), "p", f"r{i}", f"e{i}", ["n"])
        done.run["started_at"] = f"2026-11-1{i}T00:00:00+00:00"
        done.set_status("completed")
    journal.prune_runs(str(tmp_path), "p", keep=2)
    left = sorted(os.listdir(tmp_path / "p"))
    assert left == ["r0", "r3", "r4"]


# ---------------------------------------------------------------------------
# A hybrid run's stream phase reaches the ledger, the alerts and the certificate
# ---------------------------------------------------------------------------


def _finished(run_id: str = "run-1", status: str = "completed") -> Dict[str, Any]:
    return {
        "kind": "finished",
        "run_id": run_id,
        "status": status,
        "error": None if status == "completed" else "boom",
        "nodes": {"enrich": {"state": "completed", "sink": "silver.orders"}},
    }


def test_the_hybrid_executor_listens_to_its_streams(monkeypatch):
    from ducta.core.executors import hybrid as hybrid_mod

    recorded, finished, heard = [], [], []
    monkeypatch.setattr(
        "ducta.core.executors.streaming.record_stream_outcome",
        lambda context, event: recorded.append(event["run_id"]),
    )
    executor = SimpleNamespace(context=object(), on_finished=finished.append, event_listeners=[])
    executor.event_listeners.append(heard.append)
    hybrid_mod.HybridExecutor._on_stream_event(executor, _finished())
    assert recorded == ["run-1"]  # the stream nodes reach the ledger
    assert [e["run_id"] for e in finished] == ["run-1"]  # the facade can seal
    assert heard and heard[0]["kind"] == "finished"


class _Facade:
    """The facade's hand-over state, without a project behind it."""

    def __init__(self) -> None:
        self._hybrid_runs: Dict[str, Dict[str, Any]] = {}
        self._hybrid_lock = threading.Lock()
        self.sealed: List[Dict[str, Any]] = []

    def _emit_run_certificate(self, **kwargs: Any):
        self.sealed.append(kwargs)
        return "cert.json", None

    def register(self, run_id: str = "run-1") -> None:
        self._hybrid_runs[run_id] = {
            "state": "running",
            "event": None,
            "pipeline": "orders",
            "started_at": "t0",
            "run_window": (None, None),
        }


def _result(ok: bool = True, streams: bool = True):
    return SimpleNamespace(
        ok=ok, streaming_execution_ids=["s1"] if streams else [], mlops_run_id=None
    )


def _methods():
    from ducta.core.executors.facade import PipelineExecutor

    return PipelineExecutor._hybrid_handover, PipelineExecutor._on_hybrid_stream_finished


def test_a_running_stream_phase_defers_the_certificate_until_it_ends():
    handover, on_finished = _methods()
    facade = _Facade()
    facade.register()
    assert handover(facade, "run-1", _result()) == (True, None)
    assert facade.sealed == []
    on_finished(facade, _finished())
    (sealed,) = facade.sealed
    assert (sealed["run_id"], sealed["status"]) == ("run-1", "success")


def test_a_stream_that_ended_before_the_handover_is_sealed_by_run_pipeline():
    handover, on_finished = _methods()
    facade = _Facade()
    facade.register()
    on_finished(facade, _finished(status="failed"))  # early: only kept
    assert facade.sealed == []
    deferred, event = handover(facade, "run-1", _result())
    assert deferred is False and event["status"] == "failed"
    assert "run-1" not in facade._hybrid_runs


def test_a_failed_batch_phase_is_not_sealed_as_a_success_by_its_stopped_streams():
    handover, on_finished = _methods()
    facade = _Facade()
    facade.register()
    on_finished(facade, _finished(status="stopped"))  # the failure stopped them
    deferred, _event = handover(facade, "run-1", _result(ok=False))
    assert deferred is False and facade.sealed == []  # run_pipeline seals it, failed
