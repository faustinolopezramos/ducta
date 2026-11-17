"""The stream's second step (2026-11-16 review), on fakes without a JVM.

F1 automatic restarts, F2 stateful/source metrics, F3 sink compatibility and the
plan's state warning, F4 the sources Spark really reads. The same on a real Spark
session: tests/integration/test_streaming_review_2026_11_16_live.py.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any, List, Optional

import pytest

from ducta.stream.exceptions import StreamingValidationError
from ducta.stream.journal import StreamRunJournal, summarize
from ducta.stream.node_state import derive_node_state
from ducta.stream.pipeline_manager import StreamingPipelineManager
from ducta.stream.plan import plan_pipeline
from ducta.stream.progress_listener import StreamingProgressSink
from ducta.stream.validators import StreamingValidator

NODE = {"name": "n", "input": {"format": "rate"}, "output": {"format": "console"}}


class FakeQuery:
    def __init__(self, name: str) -> None:
        self.name = name
        self.id = name
        self._active = True
        self._error: Optional[Exception] = None
        self.lastProgress = None

    def isActive(self) -> bool:
        return self._active

    def stop(self) -> None:
        self._active = False

    def die(self, message: str = "boom") -> None:
        self._error = RuntimeError(message)
        self._active = False

    def awaitTermination(self, timeout: Any = None) -> bool:
        return not self._active

    def exception(self) -> Optional[Exception]:
        return self._error


def _wait(predicate, timeout: float = 5.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def make_manager(tmp_path):
    managers: List[StreamingPipelineManager] = []

    def make(**settings: Any) -> StreamingPipelineManager:
        context = {
            "global_config": {
                "streaming_health_interval_seconds": 0,
                "streaming_restart_backoff_seconds": 0.05,
                **settings,
            },
            "output_path": str(tmp_path),
            "env": "dev",
        }
        mgr = StreamingPipelineManager(context)
        started: List[FakeQuery] = []

        def start(node_config, execution_id, pipeline_name):
            if getattr(mgr, "fail_starts", 0):
                mgr.fail_starts -= 1
                raise RuntimeError("cannot start")
            query = FakeQuery(f"{pipeline_name}_{node_config['name']}_{execution_id}")
            started.append(query)
            return query

        mgr.query_manager.create_and_start_query = start
        mgr.started = started  # type: ignore[attr-defined]
        mgr.events = []  # type: ignore[attr-defined]
        mgr.add_listener(mgr.events.append)  # type: ignore[attr-defined]
        managers.append(mgr)
        return mgr

    yield make
    for mgr in managers:
        mgr.shutdown()


def _start(mgr: StreamingPipelineManager, nodes=None) -> str:
    eid = mgr.start_pipeline("p", {"type": "streaming", "nodes": nodes or [NODE]})
    assert mgr.wait_for_pipeline_started(eid, timeout=5)
    return eid


def _kinds(mgr) -> List[str]:
    return [e["kind"] for e in mgr.events]


# ---------------------------------------------------------------------------
# F1 · a query that dies while running is restarted, then given up on
# ---------------------------------------------------------------------------


class TestRestarts:
    def test_a_failed_query_is_restarted_and_streams_on(self, make_manager):
        mgr = make_manager()
        eid = _start(mgr)
        mgr.started[0].die("broker went away")

        assert _wait(lambda: len(mgr.started) == 2)
        assert _wait(lambda: "stream_restarted" in _kinds(mgr))
        status = mgr.get_pipeline_status(eid, force_refresh=True)
        assert status["query_statuses"]["n"]["isActive"]
        assert status["restarts"]["n"]["attempts"] == 1
        assert not mgr.wait_for_pipeline_done(eid, timeout=0.2)  # still running
        assert "stream_failed" not in _kinds(mgr)
        restart = next(e for e in mgr.events if e["kind"] == "stream_restarted")
        assert restart["node"] == "n" and restart["started"] and "broker" in restart["error"]

    def test_it_gives_up_after_the_last_attempt(self, make_manager):
        mgr = make_manager(streaming_restart_max_attempts=2)
        eid = _start(mgr)
        for attempt in range(3):
            assert _wait(lambda: len(mgr.started) == attempt + 1)
            mgr.started[-1].die("poison record")

        assert mgr.wait_for_pipeline_done(eid, timeout=5)
        status = mgr.get_pipeline_status(eid, force_refresh=True)
        assert len(mgr.started) == 3  # the first start and two restarts
        assert "gave up after 2 restart(s): poison record" in status["failed_nodes"]["n"]
        assert status["status"] == "error"
        assert derive_node_state("n", status).state == "failed"
        assert _kinds(mgr).count("stream_restarted") == 2
        assert "stream_failed" in _kinds(mgr)

    def test_the_backoff_doubles_and_is_capped(self, make_manager):
        mgr = make_manager(streaming_restart_backoff_seconds=10)
        assert [mgr._restart_delay(n) for n in range(7)] == [10, 20, 40, 80, 160, 300, 300]

    def test_restarts_can_be_turned_off(self, make_manager):
        mgr = make_manager(streaming_restart_max_attempts=0)
        eid = _start(mgr)
        mgr.started[0].die()
        assert mgr.wait_for_pipeline_done(eid, timeout=5)
        assert len(mgr.started) == 1
        assert mgr.get_pipeline_status(eid)["status"] == "error"

    def test_a_query_that_ends_cleanly_is_not_restarted(self, make_manager):
        mgr = make_manager()
        eid = _start(mgr)
        mgr.started[0].stop()  # an available_now query that finished its backlog
        assert mgr.wait_for_pipeline_done(eid, timeout=5)
        assert len(mgr.started) == 1
        assert mgr.get_pipeline_status(eid)["status"] == "completed"

    def test_a_stop_cancels_a_scheduled_restart(self, make_manager):
        mgr = make_manager(streaming_restart_backoff_seconds=30)
        eid = _start(mgr)
        mgr.started[0].die()
        assert _wait(lambda: mgr._restart_pending(eid))
        status = mgr.get_pipeline_status(eid, force_refresh=True)
        state = derive_node_state("n", status)
        assert state.state == "restarting" and state.next_restart_in_seconds > 20
        assert mgr.is_query_active(eid)  # its checkpoint is not free to clear
        assert mgr.clear_pipeline_checkpoints("p")["status"] == "error"

        mgr.stop_pipeline(eid)
        time.sleep(0.2)
        assert len(mgr.started) == 1
        assert not mgr._restart_pending(eid)
        assert derive_node_state("n", mgr.get_pipeline_status(eid, True)).state != "restarting"

    def test_a_restart_that_cannot_start_counts_as_an_attempt(self, make_manager):
        mgr = make_manager(streaming_restart_max_attempts=2, streaming_node_start_retries=1)
        eid = _start(mgr)
        mgr.fail_starts = 5  # every restart fails to start
        mgr.started[0].die()
        assert mgr.wait_for_pipeline_done(eid, timeout=5)
        status = mgr.get_pipeline_status(eid, force_refresh=True)
        assert "gave up after 2 restart(s)" in status["failed_nodes"]["n"]
        restarts = [e for e in mgr.events if e["kind"] == "stream_restarted"]
        assert [e["started"] for e in restarts] == [False, False]

    def test_a_stable_query_starts_its_count_again(self, make_manager, monkeypatch):
        mgr = make_manager()
        eid = _start(mgr)
        mgr.started[0].die()
        assert _wait(lambda: len(mgr.started) == 2)
        assert _wait(lambda: (mgr.get_pipeline_status(eid, True).get("restarts") or {}).get("n"))
        monkeypatch.setattr(StreamingPipelineManager, "RESTART_RESET_SECONDS", 0.0)
        assert _wait(lambda: not (mgr.get_pipeline_status(eid, True).get("restarts") or {}))

    def test_the_journal_counts_the_restarts(self, tmp_path):
        run = StreamRunJournal(str(tmp_path), "p", "r", "e", ["n"])
        run.record("progress", {"node": "n", "batch_id": 0, "rows": 5})
        run.record("restart", {"node": "n", "attempt": 1, "started": True, "error": "x"})
        run.record("restart", {"node": "n", "attempt": 2, "started": True, "error": "x"})
        totals = summarize(run.dir)["n"]
        assert totals["restarts"] == 2 and totals["batches"] == 1


# ---------------------------------------------------------------------------
# F2 · what a stateful query and its sources report is kept
# ---------------------------------------------------------------------------


def _progress(**extra: Any) -> SimpleNamespace:
    base = dict(
        name="q",
        id="id-q",
        batchId=3,
        numInputRows=10,
        inputRowsPerSecond=1.0,
        processedRowsPerSecond=2.0,
        durationMs={"triggerExecution": 100},
        eventTime={},
        stateOperators=[],
        sources=[],
    )
    base.update(extra)
    return SimpleNamespace(**base)


class TestStateMetrics:
    def test_watermark_state_late_rows_and_lag(self):
        sink = StreamingProgressSink()
        sink.record(
            _progress(
                eventTime={"watermark": "2026-11-16T10:00:00.000Z", "max": "2026-11-16T10:00:05Z"},
                stateOperators=[
                    SimpleNamespace(
                        numRowsTotal=7, memoryUsedBytes=100, numRowsDroppedByWatermark=2
                    ),
                    SimpleNamespace(
                        numRowsTotal=3, memoryUsedBytes=50, numRowsDroppedByWatermark=1
                    ),
                ],
                sources=[
                    SimpleNamespace(
                        description="KafkaV2[Subscribe[events]]",
                        metrics={"maxOffsetsBehindLatest": "42", "avgOffsetsBehindLatest": "20"},
                    ),
                    SimpleNamespace(
                        description="DeltaSource[/t]", metrics={"numFilesOutstanding": "5"}
                    ),
                ],
            )
        )
        latest = sink.get_latest("q")
        assert latest["watermark"] == "2026-11-16T10:00:00.000Z"
        assert (latest["stateRows"], latest["stateMemoryBytes"], latest["lateRowsDropped"]) == (
            10,
            150,
            3,
        )
        assert latest["sourceLag"] == 42.0
        assert latest["sources"] == ["KafkaV2[Subscribe[events]]", "DeltaSource[/t]"]

        state = derive_node_state(
            "n",
            {"query_statuses": {"n": {"isActive": True}}, "progress_metrics": {"n": latest}},
        )
        assert (state.state_rows, state.late_rows_dropped, state.source_lag) == (10, 3, 42)
        assert state.watermark.startswith("2026-11-16") and len(state.sources) == 2

    def test_a_stateless_query_reports_none(self):
        sink = StreamingProgressSink()
        sink.record(_progress(eventTime=None, stateOperators=None, sources=None))
        latest = sink.get_latest("q")
        assert all(
            latest[k] is None
            for k in ("watermark", "stateRows", "lateRowsDropped", "sourceLag", "sources")
        )
        assert latest["numInputRows"] == 10  # the rest is untouched

    def test_the_journal_keeps_the_last_state_and_sums_late_rows(self, tmp_path):
        run = StreamRunJournal(str(tmp_path), "p", "r", "e", ["n"])
        for batch, (rows, late) in enumerate([(5, 1), (8, 0), (6, 2)]):
            run.record(
                "progress",
                {
                    "node": "n",
                    "batch_id": batch,
                    "rows": 10,
                    "state_rows": rows,
                    "late_rows_dropped": late,
                    "watermark": f"w{batch}",
                    "sources": ["a", "b"],
                },
            )
        totals = summarize(run.dir)["n"]
        assert (totals["state_rows"], totals["late_rows_dropped"], totals["watermark"]) == (
            6,
            3,
            "w2",
        )
        assert totals["sources"] == ["a", "b"]

    def test_the_manager_journals_them(self, make_manager, tmp_path):
        mgr = make_manager()
        eid = _start(mgr)
        qname = mgr.started[0].name
        mgr.progress_sink.record(
            _progress(
                name=qname,
                stateOperators=[
                    SimpleNamespace(numRowsTotal=4, memoryUsedBytes=1, numRowsDroppedByWatermark=1)
                ],
                sources=[SimpleNamespace(description="RateStreamV2", metrics={})] * 2,
            )
        )
        journal_dir = mgr.get_pipeline_status(eid)["journal_dir"]
        from pathlib import Path

        totals = summarize(Path(journal_dir))["n"]
        assert totals["state_rows"] == 4 and totals["late_rows_dropped"] == 1
        assert totals["sources"] == ["RateStreamV2", "RateStreamV2"]


# ---------------------------------------------------------------------------
# F3 · output mode and trigger against the sink, before Spark refuses them
# ---------------------------------------------------------------------------


def _node(fmt="parquet", mode=None, trigger=None, **extra):
    streaming = {}
    if mode:
        streaming["output_mode"] = mode
    if trigger:
        streaming["trigger"] = trigger
    output = {"format": fmt}
    if fmt in ("parquet", "json", "csv", "delta"):
        output["path"] = "/tmp/out"
    if fmt == "kafka":
        output["options"] = {"kafka.bootstrap.servers": "h:9092", "topic": "t"}
    node = {"name": "agg", "input": {"format": "rate"}, "output": output, "streaming": streaming}
    node.update(extra)
    return node


class TestSinkCompatibility:
    @pytest.mark.parametrize(
        "fmt, mode",
        [
            ("parquet", "update"),
            ("json", "complete"),
            ("csv", "update"),
            ("delta", "update"),
            ("memory", "update"),
        ],
    )
    def test_a_mode_the_native_sink_refuses(self, fmt, mode):
        with pytest.raises(StreamingValidationError, match="does not support output_mode"):
            StreamingValidator().validate_streaming_node_config(_node(fmt, mode))

    def test_update_on_a_file_sink_points_at_merge(self):
        with pytest.raises(StreamingValidationError, match="output.mode: merge"):
            StreamingValidator().validate_streaming_node_config(_node("delta", "update"))

    @pytest.mark.parametrize(
        "node",
        [
            _node("delta", "complete"),
            _node("kafka", "update"),
            _node("console", "complete"),
            _node("parquet", "append"),
            # Through foreachBatch every mode is fine.
            _node("parquet", "update", quarantine={"reject_when": "value < 0"}),
            _node(
                "delta",
                "update",
                output={"format": "delta", "path": "/t", "mode": "merge", "merge": {"keys": ["k"]}},
            ),
        ],
    )
    def test_what_spark_accepts_passes(self, node):
        StreamingValidator().validate_streaming_node_config(node)

    @pytest.mark.parametrize(
        "node, why",
        [
            (
                _node("parquet", trigger={"type": "continuous", "interval": "1 second"}),
                "writes only to",
            ),
            (
                _node(
                    "parquet",
                    trigger={"type": "continuous", "interval": "1 second"},
                    data_quality={"checks": [{"type": "not_null", "column": "v"}]},
                ),
                "per micro-batch",
            ),
            (
                _node(
                    "kafka",
                    trigger={"type": "continuous", "interval": "1 second"},
                    streaming={
                        "trigger": {"type": "continuous", "interval": "1 second"},
                        "watermark": {"column": "timestamp", "delay": "5 seconds"},
                    },
                ),
                "event-time state",
            ),
        ],
    )
    def test_what_the_continuous_trigger_cannot_do(self, node, why):
        with pytest.raises(StreamingValidationError, match=why):
            StreamingValidator().validate_streaming_node_config(node)

    def test_continuous_to_kafka_passes(self):
        StreamingValidator().validate_streaming_node_config(
            _node("kafka", trigger={"type": "continuous", "interval": "1 second"})
        )


class TestPlanStateWarning:
    def _plan(self, node, **gs):
        context = SimpleNamespace(
            global_config={"output_path": "/tmp/x", **gs}, output_path="/tmp/x", env="dev"
        )
        return plan_pipeline(context, "p", {"type": "streaming", "nodes": [node]})

    def test_a_stateful_node_without_partitions_is_warned(self):
        node = _node(
            "parquet", streaming={"watermark": {"column": "timestamp", "delay": "5 seconds"}}
        )
        plan = self._plan(node)
        assert any("partition count" in w for w in plan.warnings), plan.warnings
        assert not plan.errors

    @pytest.mark.parametrize(
        "node, gs",
        [
            (
                _node(
                    "parquet",
                    streaming={"watermark": {"column": "timestamp"}, "shuffle_partitions": 16},
                ),
                {},
            ),
            (
                _node("parquet", streaming={"watermark": {"column": "timestamp"}}),
                {"streaming_shuffle_partitions": 16},
            ),
            (_node("parquet"), {}),  # stateless
        ],
    )
    def test_no_warning_when_set_or_stateless(self, node, gs):
        assert not any("partition count" in w for w in self._plan(node, **gs).warnings)

    def test_the_plan_reports_an_unsupported_mode(self):
        plan = self._plan(_node("parquet", "update"))
        assert any("does not support output_mode" in e for e in plan.errors)


def test_a_health_interval_of_zero_turns_the_check_off(make_manager):
    # Documented as "0 turns the check off"; `or 30.0` used to make it 30 seconds.
    mgr = make_manager(streaming_health_interval_seconds=0)
    _start(mgr)
    assert mgr.health_interval_seconds == 0 and mgr._health_thread is None


def test_a_spark_wrapped_python_error_keeps_its_python_line():
    from ducta.stream.pipeline_manager import short_error

    wrapped = (
        "Job aborted due to stage failure: Task 0 in stage 3.0 failed 1 times\n"
        + "\tat org.apache.spark.scheduler.Task.run(Task.scala:141)\n" * 40
        + '  File "t.py", line 19, in boom\n    raise ValueError("poison record 5")\n'
        "ValueError: poison record 5\n\tat org.apache.spark.api.python.X(X.scala:1)\n"
        "org.apache.spark.SparkException: inner\n"
    )
    text = short_error(wrapped)
    assert text.startswith("ValueError: poison record 5 (Job aborted") and len(text) <= 500
    assert short_error("plain failure") == "plain failure"


class TestPlanOfAHybridPipeline:
    """`stream plan` on a `type: hybrid` pipeline planned its batch nodes as streams
    (8 errors on the demo: no input format, transform not registered)."""

    def _plan(self, nodes):
        context = SimpleNamespace(
            global_config={"output_path": "/tmp/x"}, output_path="/tmp/x", env="dev"
        )
        return plan_pipeline(context, "h", {"type": "hybrid", "nodes": nodes})

    def test_batch_nodes_are_not_planned_as_streams(self):
        batch = {"name": "clean", "function": {"key": "c"}, "input": {"customers": "bronze.c"}}
        stream = _node("parquet", name="agg", dependencies=["clean"])
        plan = self._plan([batch, stream])
        assert [n.name for n in plan.nodes] == ["agg"]
        assert plan.batch_phase == ["clean"]
        assert not plan.errors, plan.errors

    def test_a_hybrid_pipeline_with_no_stream_node_is_an_error(self):
        batch = {"name": "clean", "function": {"key": "c"}, "input": {"customers": "bronze.c"}}
        assert any("no streaming nodes" in e for e in self._plan([batch]).errors)

    def test_the_enum_type_is_recognised(self):
        from ducta.stream.constants import PipelineType

        context = SimpleNamespace(
            global_config={"output_path": "/tmp/x"}, output_path="/tmp/x", env="dev"
        )
        batch = {"name": "clean", "function": {"key": "c"}, "input": {"customers": "bronze.c"}}
        plan = plan_pipeline(
            context, "h", {"type": PipelineType.HYBRID, "nodes": [batch, _node("parquet")]}
        )
        assert plan.batch_phase == ["clean"]


class TestStreamSinkEvidence:
    """A hybrid certificate listed the batch tables and not the table its stream wrote,
    and still read evidence_complete=true."""

    def _context(self, spark, **outputs):
        return SimpleNamespace(
            global_config={"enable_data_fingerprinting": True},
            nodes_config={
                name: {"name": name, "output": spec, "streaming": {}}
                for name, spec in outputs.items()
            },
            spark=spark,
        )

    @staticmethod
    def _event(**states):
        return {"nodes": {name: {"state": state} for name, state in states.items()}}

    def test_a_file_sink_is_fingerprinted_under_the_streams_name(self, monkeypatch):
        from unittest.mock import MagicMock

        from ducta.core.executors.streaming import fingerprint_stream_sinks

        fake = MagicMock()
        fake.to_dict.return_value = {"filepath": "data/gold"}
        fake.details = {}
        seen = {}
        monkeypatch.setattr(
            "ducta.gate.fingerprinting.compute_fingerprint",
            lambda manager, **kw: seen.update(kw) or fake,
        )
        monkeypatch.setattr("ducta.gate.fingerprinting.delta_identity", lambda *a: {"v": 3})
        context = self._context(MagicMock(), enrich={"format": "delta", "path": "data/gold"})
        fingerprint_stream_sinks(context, self._event(enrich="stopped"))
        assert context._output_fingerprints == {"stream.enrich": {"filepath": "data/gold"}}
        assert seen["identifier"] == "data/gold" and seen["delta"] == {"v": 3}

    def test_failed_nodes_and_non_file_sinks_are_left_out(self, monkeypatch):
        from unittest.mock import MagicMock

        from ducta.core.executors.streaming import fingerprint_stream_sinks

        called = []
        monkeypatch.setattr(
            "ducta.gate.fingerprinting.compute_fingerprint",
            lambda *a, **k: called.append(1),
        )
        context = self._context(
            MagicMock(),
            broken={"format": "delta", "path": "p"},
            events={"format": "kafka", "options": {"topic": "t"}},
        )
        fingerprint_stream_sinks(context, self._event(broken="failed", events="stopped"))
        assert not called and not getattr(context, "_output_fingerprints", None)

    def test_a_sink_that_cannot_be_read_is_a_gap_not_silence(self, monkeypatch):
        from unittest.mock import MagicMock

        from ducta.core.executors.streaming import fingerprint_stream_sinks
        from ducta.core.ledger import ledger_for

        spark = MagicMock()
        spark.read.format.return_value.load.side_effect = RuntimeError("gone")
        context = self._context(spark, enrich={"format": "parquet", "path": "p"})
        fingerprint_stream_sinks(context, self._event(enrich="stopped"))
        assert any("enrich" in gap for gap in ledger_for(context).record_failures)

    def test_nothing_is_read_when_fingerprinting_is_off(self):
        from unittest.mock import MagicMock

        from ducta.core.executors.streaming import fingerprint_stream_sinks

        spark = MagicMock()
        context = self._context(spark, enrich={"format": "delta", "path": "p"})
        context.global_config["enable_data_fingerprinting"] = False
        fingerprint_stream_sinks(context, self._event(enrich="stopped"))
        spark.read.format.assert_not_called()
