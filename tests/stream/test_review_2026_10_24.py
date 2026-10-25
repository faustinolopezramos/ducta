"""Regressions for the 2026-10-24 review of ``ducta.stream``.

Each class pins one defect that was reproduced before it was fixed. Queries are
fakes (anything with ``isActive``/``stop``/``awaitTermination``), so the manager
runs without a JVM.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from ducta.stream.checkpoints import CheckpointManager
from ducta.stream.exceptions import StreamingError, StreamingValidationError
from ducta.stream.factories import spark_option_value
from ducta.stream.pipeline_manager import StreamingPipelineManager
from ducta.stream.progress_listener import StreamingProgressSink
from ducta.stream.query_manager import StreamingQueryManager
from ducta.stream.readers import BaseStreamingReader
from ducta.stream.trigger_scheduler import TriggerScheduler
from ducta.stream.validators import StreamingValidator
from ducta.stream.writers import ConsoleStreamingWriter

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


class _Recorder:
    def __init__(self):
        self.options = []

    def option(self, key, value):
        self.options.append((key, value))
        return self


@pytest.fixture
def context(tmp_path):
    return {"global_config": {}, "output_path": str(tmp_path), "env": "dev"}


@pytest.fixture
def manager(context):
    mgr = StreamingPipelineManager(context)
    yield mgr
    mgr.shutdown()


def _slow_start(started, gate=None, delay=0.5):
    def start(node_config, execution_id, pipeline_name):
        if gate is not None:
            gate.set()
        time.sleep(delay)  # Spark's .start() takes a while
        query = FakeQuery(f"{pipeline_name}_{node_config['name']}")
        started.append(query)
        return query

    return start


class TestStopDuringStartup:
    def test_query_started_after_stop_is_stopped_not_orphaned(self, manager):
        started, gate = [], threading.Event()
        manager.query_manager.create_and_start_query = _slow_start(started, gate)
        eid = manager.start_pipeline("p", {"type": "streaming", "nodes": [NODE]})
        assert gate.wait(2)
        manager.stop_pipeline(eid)
        assert manager.wait_for_pipeline_done(eid, timeout=3)
        time.sleep(0.8)  # let the in-flight start finish

        assert started and not started[0].isActive()
        status = manager.get_pipeline_status(eid, force_refresh=True)
        assert status["status"] == "stopped"
        assert status["total_queries"] == 0

    def test_restart_refused_once_the_execution_is_stopped(self, manager):
        started = []
        manager.query_manager.create_and_start_query = _slow_start(started, delay=0)
        eid = manager.start_pipeline("p", {"type": "streaming", "nodes": [NODE]})
        assert manager.wait_for_pipeline_started(eid, timeout=3)
        manager.stop_pipeline(eid)

        assert manager.restart_node(eid, "n") is False
        assert len(started) == 1  # nothing new was started

    def test_restart_clears_the_error_of_the_node_it_fixed(self, manager):
        started = []
        manager.query_manager.create_and_start_query = _slow_start(started, delay=0)
        eid = manager.start_pipeline("p", {"type": "streaming", "nodes": [NODE]})
        assert manager.wait_for_pipeline_started(eid, timeout=3)
        manager._handle_node_execution_error(eid, "n", "boom")

        assert manager.restart_node(eid, "n") is True
        status = manager.get_pipeline_status(eid, force_refresh=True)
        assert status["error"] is None
        assert status["status"] == "running"


class TestLiveQueriesNotStatus:
    def _stopped_with_live_query(self, manager):
        """A "stopped" execution whose stop failed for its query."""
        manager.query_manager.create_and_start_query = _slow_start([], delay=0)
        eid = manager.start_pipeline("p", {"type": "streaming", "nodes": [NODE]})
        assert manager.wait_for_pipeline_started(eid, timeout=3)
        with manager._lock:
            manager._running_pipelines[eid]["status"] = "stopped"
            return eid, manager._running_pipelines[eid]["queries"]["n"]

    def test_clear_refuses_while_a_stopped_execution_still_runs(self, manager, tmp_path):
        _, query = self._stopped_with_live_query(manager)
        offsets = tmp_path / "dev" / "streaming_checkpoints" / "p" / "n" / "offsets"
        offsets.mkdir(parents=True)

        result = manager.clear_pipeline_checkpoints("p")

        assert result["status"] == "error"
        assert offsets.exists() and query.isActive()

    def test_shutdown_stops_a_query_a_stopped_execution_still_holds(self, manager):
        _, query = self._stopped_with_live_query(manager)
        manager.shutdown()
        assert not query.isActive()


class TestStringTransform:
    def test_short_form_is_looked_up_by_key(self, context):
        qm = StreamingQueryManager(context)
        df = object()
        qm.transformation_registry.register("enrich", lambda d: d)
        # A plain object is not a DataFrame: reaching that check means the
        # string was resolved as a key (it used to fail with AttributeError).
        with pytest.raises(StreamingError, match="must return a DataFrame"):
            qm._apply_transformations(df, {"name": "n", "function": "enrich"})


class TestCloudCheckpoints:
    @pytest.mark.parametrize(
        "base", ["s3a://bucket/ckpt", "s3n://bucket/ckpt", "wasbs://c@a.blob/ckpt"]
    )
    def test_hadoop_schemes_are_kept_as_uris(self, base):
        assert CheckpointManager.is_cloud_path(base)
        assert CheckpointManager.build_checkpoint_path(base, "p", "n") == f"{base}/p/n"


class TestAdaptiveIgnoresIdleReports:
    def test_idle_reports_do_not_shrink_the_interval(self, context):
        sink = StreamingProgressSink()
        sink.register_history_key("q", "p::n")
        for i in range(3):
            sink.record(
                {
                    "name": "q",
                    "batchId": i,
                    "numInputRows": 10,
                    "durationMs": {"triggerExecution": 20000},
                }
            )
        for _ in range(30):
            sink.record(
                {
                    "name": "q",
                    "batchId": 2,
                    "numInputRows": 0,
                    "durationMs": {"triggerExecution": 5},
                }
            )
        context["global_config"]["streaming_adaptive_max_interval_seconds"] = 120
        trigger = TriggerScheduler(context, StreamingValidator(), sink).configure_trigger(
            {"type": "adaptive"}, "q2", "p::n"
        )
        assert trigger == {"processingTime": "30.000 seconds"}


class TestCheckpointInOutputOptions:
    @pytest.mark.parametrize("key", ["checkpointLocation", "checkpointlocation"])
    def test_validator_rejects_it(self, key):
        node = {**NODE, "output": {"format": "console", "options": {key: "/elsewhere"}}}
        with pytest.raises(StreamingValidationError, match="checkpointLocation"):
            StreamingValidator().validate_streaming_node_config(node)

    def test_project_schema_rejects_it(self):
        from ducta.setting.project.schema import StreamOutput

        with pytest.raises(ValueError, match="checkpointLocation"):
            StreamOutput.model_validate(
                {"format": "console", "options": {"checkpointLocation": "/elsewhere"}}
            )


class TestOptionValues:
    def test_mappings_and_lists_are_json(self):
        assert spark_option_value({"topicA": [0, 1]}) == '{"topicA": [0, 1]}'
        assert spark_option_value(True) == "true"
        assert spark_option_value(5) == "5"

    def test_reader_and_writer_send_json(self, context):
        reader = BaseStreamingReader._apply_options(None, _Recorder(), {"assign": {"t": [0]}})
        assert reader.options == [("assign", '{"t": [0]}')]
        writer = ConsoleStreamingWriter(context)._apply_options(
            _Recorder(), {"startingOffsets": {"t": {"0": -2}}}
        )
        assert writer.options == [("startingOffsets", '{"t": {"0": -2}}')]

    def test_writer_error_log_names_keys_not_values(self, context, monkeypatch):
        logged = []
        monkeypatch.setattr("ducta.stream.writers.logger.error", logged.append)

        class Broken:
            def option(self, *_):
                raise RuntimeError("py4j down")

        with pytest.raises(StreamingError):
            ConsoleStreamingWriter(context)._apply_options(
                Broken(), {"kafka.sasl.jaas.config": "password=hunter2"}
            )
        assert logged and "hunter2" not in logged[0]


class TestTransientRetrySpellings:
    @pytest.mark.parametrize(
        "node",
        [
            {"input": {"format": "delta", "path": "x"}},
            {"inputs": [{"format": "delta_stream", "path": "x"}]},
        ],
    )
    def test_alias_and_list_form_are_retried(self, manager, node):
        assert manager._is_transient_start_error(node, Exception("Path does not exist: x"))


class TestDependencySpellings:
    def test_both_keys_are_validated(self):
        nodes = [
            {**NODE, "name": "a"},
            {**NODE, "name": "b", "depends_on": ["a"], "dependencies": ["ghost"]},
        ]
        with pytest.raises(StreamingError, match="ghost"):
            StreamingValidator().validate_streaming_pipeline_config(
                {"type": "streaming", "nodes": nodes}
            )
