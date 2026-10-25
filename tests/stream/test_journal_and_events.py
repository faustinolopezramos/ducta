"""A streaming run's journal (ducta.stream.journal), its finished event, adaptive
history across runs, and the live alerts - on fakes, without a JVM."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from ducta.stream import journal as journal_mod
from ducta.stream.journal import (
    StreamRunJournal,
    find_run,
    load_run,
    recent_trigger_ms,
    summarize,
)
from ducta.stream.pipeline_manager import StreamingPipelineManager

NODE = {"name": "n", "input": {"format": "rate"}, "output": {"format": "console"}}


class FakeQuery:
    def __init__(self, name):
        self.name = name
        self.id = name
        self._active = True
        self.lastProgress = None

    def isActive(self):
        return self._active

    def stop(self):
        self._active = False

    def awaitTermination(self, timeout=None):
        return not self._active

    def exception(self):
        return None


@pytest.fixture
def context(tmp_path):
    return {
        "global_config": {"api_execution_id": "api-1", "streaming_health_interval_seconds": 0},
        "output_path": str(tmp_path),
        "env": "dev",
    }


@pytest.fixture
def manager(context):
    mgr = StreamingPipelineManager(context)
    started = []

    def start(node_config, execution_id, pipeline_name):
        query = FakeQuery(f"{pipeline_name}_{node_config['name']}_{execution_id}")
        started.append(query)
        return query

    mgr.query_manager.create_and_start_query = start
    mgr.started = started
    events = []
    mgr.add_listener(events.append)
    mgr.events = events
    yield mgr
    mgr.shutdown()


def _run(manager, nodes=None, run_id="run-1"):
    eid = manager.start_pipeline(
        "p", {"type": "streaming", "nodes": nodes or [NODE]}, run_id=run_id
    )
    assert manager.wait_for_pipeline_started(eid, timeout=5)
    return eid


def _base(tmp_path):
    return str(tmp_path / "dev" / ".ducta" / "streams")


class TestJournal:
    def test_lines_summary_and_rotation(self, tmp_path, monkeypatch):
        monkeypatch.setattr(journal_mod, "MAX_BATCHES_BYTES", 200)
        journal = StreamRunJournal(str(tmp_path), "p", "r1", "e1", ["n"])
        for batch in range(5):
            journal.record(
                "progress", {"node": "n", "batch_id": batch, "rows": 10, "trigger_ms": 5}
            )
        journal.record(
            "batch",
            {"node": "n", "batch_id": 4, "rows_written": 8, "rows_quarantined": 2, "gate": "pass"},
        )

        assert (journal.dir / "batches.1.jsonl").exists()  # rotated, still read
        summary = summarize(journal.dir)["n"]
        assert summary["batches"] + 0 >= 1
        assert summary["rows_quarantined"] == 2
        assert summary["gate"] == {"pass": 1}
        assert summary["last_batch"] == 4

    def test_a_running_run_whose_process_is_gone_reads_as_interrupted(self, tmp_path):
        journal = StreamRunJournal(str(tmp_path), "p", "r1", "e1", ["n"])
        journal.set_status("running")
        run = json.loads((journal.dir / "run.json").read_text())
        run["pid"] = 2**22 + 12345  # no such process
        (journal.dir / "run.json").write_text(json.dumps(run))

        assert load_run(journal.dir)["status"] == "interrupted"

    def test_final_status_is_kept_as_written(self, tmp_path):
        journal = StreamRunJournal(str(tmp_path), "p", "r1", "e1", ["n"])
        journal.set_status("stopped", nodes={"n": {"state": "stopped"}})
        run = load_run(journal.dir)
        assert run["status"] == "stopped" and run["ended_at"]
        assert run["outcome"] == {"n": {"state": "stopped"}}

    def test_recent_durations_come_from_the_previous_run(self, tmp_path):
        old = StreamRunJournal(str(tmp_path), "p", "old", "e0", ["n"])
        old.record("progress", {"node": "n", "batch_id": 0, "rows": 5, "trigger_ms": 20000})
        time.sleep(0.01)
        StreamRunJournal(str(tmp_path), "p", "new", "e1", ["n"])
        assert recent_trigger_ms(str(tmp_path), "p", "n", exclude_run="new") == [20000.0]


class TestManagerJournals:
    def test_a_run_is_journaled_from_start_to_stop(self, manager, tmp_path):
        eid = _run(manager)
        run = find_run(_base(tmp_path), "p", api_execution_id="api-1")
        assert run["status"] == "running" and run["run_id"] == "run-1"

        query = manager.started[0]
        manager.progress_sink.record(
            {
                "name": query.name,
                "batchId": 0,
                "numInputRows": 7,
                "durationMs": {"triggerExecution": 40},
            }
        )
        manager.stop_pipeline(eid)

        run = find_run(_base(tmp_path), "p", run_id="run-1")
        assert run["status"] == "stopped"
        assert run["outcome"]["n"]["state"] == "stopped"
        lines = list(journal_mod.iter_lines(Path(run["journal_dir"])))
        assert [line["kind"] for line in lines] == ["progress"]
        assert lines[0]["node"] == "n" and lines[0]["rows"] == 7

    def test_finished_is_emitted_once_with_each_node(self, manager):
        eid = _run(manager)
        manager.stop_pipeline(eid)
        manager.stop_pipeline(eid)
        finished = [e for e in manager.events if e["kind"] == "finished"]
        assert len(finished) == 1
        assert finished[0]["run_id"] == "run-1"
        assert finished[0]["status"] == "stopped"
        assert finished[0]["nodes"]["n"]["state"] == "stopped"

    def test_adaptive_starts_from_the_previous_runs_durations(self, manager, tmp_path):
        old = StreamRunJournal(_base(tmp_path), "p", "old", "e0", ["n"])
        old.record("progress", {"node": "n", "batch_id": 0, "rows": 5, "trigger_ms": 20000})
        node = {**NODE, "streaming": {"trigger": {"type": "adaptive"}}}
        _run(manager, [node], run_id="new")
        assert manager.progress_sink.avg_trigger_ms("p::n") == 20000.0


class TestLiveAlerts:
    def _kinds(self, manager):
        return [e["kind"] for e in manager.events if e["kind"] != "finished"]

    def test_a_failure_is_reported_once_and_its_recovery_too(self, manager):
        eid = _run(manager)
        manager.started[0]._active = False
        manager._handle_node_execution_error(eid, "n", "boom")
        manager.check_health_now()
        manager.check_health_now()
        assert self._kinds(manager) == ["stream_failed"]
        event = manager.events[-1]
        assert event["node"] == "n" and "boom" in event["error"]

        assert manager.restart_node(eid, "n")
        manager.check_health_now()
        assert self._kinds(manager) == ["stream_failed", "stream_recovered"]

    def test_quarantine_is_reported_at_once_then_summarised(self, manager):
        eid = _run(manager)
        stats = {"node": "n", "batch_id": 0, "rows_quarantined": 3}
        manager._on_micro_batch("p", eid, stats)
        manager._on_micro_batch("p", eid, {**stats, "batch_id": 1, "rows_quarantined": 2})
        quarantine = [e for e in manager.events if e["kind"] == "stream_quarantine"]
        assert [(e["rows"], e["batches"]) for e in quarantine] == [(3, 1)]

        manager.stop_pipeline(eid)  # what is still pending goes out at the end
        quarantine = [e for e in manager.events if e["kind"] == "stream_quarantine"]
        assert [(e["rows"], e["batches"]) for e in quarantine] == [(3, 1), (2, 1)]
        status = manager.get_pipeline_status(eid, force_refresh=True)
        assert status["micro_batches"]["n"]["rows_quarantined"] == 5


class TestAlertDelivery:
    def _rules(self, when):
        from ducta.setting.project.schema import AlertRule

        return [
            AlertRule.model_validate(
                {"when": when, "channels": [{"type": "webhook", "url_env": "HOOK"}]}
            )
        ]

    def _store(self, monkeypatch, rules):
        class Store:
            root = Path("/proj")

            def project(self):
                return type("P", (), {"project": type("Q", (), {"alerts": rules})()})()

        monkeypatch.setattr(
            "ducta.api.repositories.v2_store.V2ProjectStore.detect",
            staticmethod(lambda path: Store()),
        )

    def test_a_rule_naming_the_kind_gets_one_message(self, monkeypatch):
        from ducta.api.services.alerts import notify_stream_event

        self._store(monkeypatch, self._rules(["stream_quarantine"]))
        monkeypatch.setenv("HOOK", "http://hook")
        sent = []
        event = {
            "kind": "stream_quarantine",
            "pipeline": "p",
            "node": "n",
            "rows": 4,
            "batches": 2,
            "run_id": "r",
        }
        result = notify_stream_event(
            "/proj", "proj", "dev", event, post=lambda url, body: sent.append(body)
        )

        assert result == [{"channel": "webhook", "ok": True}]
        assert "4 row(s) quarantined in 2 batch(es)" in sent[0]["text"]
        assert sent[0]["kind"] == "stream_quarantine"

    def test_other_kinds_and_recoveries_send_nothing(self, monkeypatch):
        from ducta.api.services.alerts import notify_stream_event

        self._store(monkeypatch, self._rules(["stream_failed"]))
        monkeypatch.setenv("HOOK", "http://hook")
        sent = []
        post = lambda url, body: sent.append(body)  # noqa: E731
        notify_stream_event(
            "/proj", "p", "dev", {"kind": "stream_quarantine", "pipeline": "p"}, post=post
        )
        notify_stream_event(
            "/proj", "p", "dev", {"kind": "stream_recovered", "pipeline": "p"}, post=post
        )
        assert sent == []


class TestJournalStatusForTheApi:
    def test_an_interrupted_run_is_shown_from_its_journal(self, tmp_path):
        from ducta.api.services.streaming_status import journal_pipeline_status

        journal = StreamRunJournal(str(tmp_path), "p", "r1", "e1", ["n"])
        journal.record(
            "batch",
            {"node": "n", "batch_id": 9, "rows_written": 1, "rows_quarantined": 4, "gate": "block"},
        )
        run = load_run(journal.dir)
        run["status"] = "interrupted"

        status = journal_pipeline_status(run)
        assert status.from_journal and status.status == "interrupted"
        assert status.run_id == "r1"
        node = status.nodes[0]
        assert (node.node, node.state, node.rows_quarantined, node.gate, node.last_batch_id) == (
            "n",
            "unknown",
            4,
            "block",
            9,
        )
