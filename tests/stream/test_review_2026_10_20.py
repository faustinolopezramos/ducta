"""Regressions for the 2026-10-20 review of ``ducta.stream`` and its executors.

Each class pins one defect that was reproduced before it was fixed. The fakes
stand in for Spark: a query is anything with ``isActive``/``stop``/
``awaitTermination``, and the reader/writer factories are given classes that
build them, so the whole manager runs without a JVM.
"""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ducta.stream.checkpoints import CheckpointManager
from ducta.stream.exceptions import (
    StreamingConfigurationError,
    StreamingValidationError,
)
from ducta.stream.pipeline_manager import QueryHealthMonitor, StreamingPipelineManager
from ducta.stream.progress_listener import StreamingProgressSink
from ducta.stream.query_manager import single_spec
from ducta.stream.readers import BaseStreamingReader, StreamingReaderFactory
from ducta.stream.trigger_scheduler import TriggerScheduler
from ducta.stream.validators import StreamingValidator
from ducta.stream.writers import BaseStreamingWriter, StreamingWriterFactory

# --------------------------------------------------------------------------- fakes


class FakeQuery:
    def __init__(self, name, await_fail=False):
        self.name = name
        self.id = name
        self._active = True
        self._await_fail = await_fail
        self.lastProgress = None

    @property
    def isActive(self):
        return self._active

    def stop(self):
        self._active = False

    def awaitTermination(self, timeout=None):
        if self._await_fail:
            self._active = False
            raise RuntimeError("upstream query exploded")
        return not self._active

    def exception(self):
        return None


class _Chain:
    name = None

    def outputMode(self, *_):
        return self

    def queryName(self, name):
        self.name = name
        return self

    def option(self, *_):
        return self

    def trigger(self, **_):
        return self


class FakeDF:
    columns = ["a"]
    dtypes = [("a", "string")]
    sparkSession = MagicMock()

    @property
    def writeStream(self):
        return _Chain()


class FakeReader(BaseStreamingReader):
    def read_stream(self, config):
        return FakeDF()


class FakeWriter(BaseStreamingWriter):
    def write_stream(self, write_stream, config):
        opts = config.get("options") or {}
        if opts.get("fail"):
            raise RuntimeError("sink refused to start")
        return FakeQuery(write_stream.name, await_fail=bool(opts.get("await_fail")))


def node(name, **overrides):
    cfg = {
        "name": name,
        "input": {
            "format": "kafka",
            "options": {"kafka.bootstrap.servers": "x:9092", "subscribe": "t"},
        },
        "output": {"format": "console", "options": {}},
        "streaming": {"trigger": {"type": "processing_time", "interval": "10 seconds"}},
    }
    cfg.update(overrides)
    return cfg


@pytest.fixture
def make_manager(tmp_path):
    managers = []

    def factory(**global_config):
        context = SimpleNamespace(
            spark=MagicMock(),
            global_config={"streaming_node_start_retries": 1, **global_config},
            output_path=str(tmp_path),
            env="dev",
            format_policy=None,
            nodes_config={},
            pipelines_config={},
        )
        manager = StreamingPipelineManager(context)
        manager.query_manager.reader_factory.register_custom_reader("kafka", FakeReader)
        manager.query_manager.writer_factory.register_custom_writer("console", FakeWriter)
        managers.append(manager)
        return manager

    yield factory
    for manager in managers:
        manager.shutdown(timeout_seconds=2)


def run(manager, name, nodes):
    eid = manager.start_pipeline(name, {"type": "streaming", "nodes": nodes})
    assert manager.wait_for_pipeline_started(eid, 10)
    return eid


def query_of(manager, eid, node_name):
    return manager._running_pipelines[eid]["queries"][node_name]


def status_of(manager, eid):
    return manager.get_pipeline_status(eid, force_refresh=True)


# --------------------------------------------------------------- end-of-run status


class TestPartialFailureIsNotReportedAsSuccess:
    def test_a_node_that_never_started_keeps_the_run_partial_when_the_rest_finishes(
        self, make_manager
    ):
        manager = make_manager()
        ok = node("a", streaming={"trigger": {"type": "available_now"}})
        bad = node("b", output={"format": "console", "options": {"fail": 1}})
        eid = run(manager, "p", [ok, bad])
        query_of(manager, eid, "a")._active = False  # finished on its own

        assert manager.wait_for_pipeline_done(eid, 10)
        status = status_of(manager, eid)
        assert status["status"] == "partial_failure"
        assert list(status["failed_nodes"]) == ["b"]

    def test_a_clean_run_still_completes(self, make_manager):
        manager = make_manager()
        eid = run(manager, "p", [node("a", streaming={"trigger": {"type": "available_now"}})])
        query_of(manager, eid, "a")._active = False
        assert manager.wait_for_pipeline_done(eid, 10)
        assert status_of(manager, eid)["status"] == "completed"

    def test_when_no_node_starts_the_pipeline_failed_and_is_not_active(self, make_manager):
        manager = make_manager()
        eid = run(manager, "p", [node("a", output={"format": "console", "options": {"fail": 1}})])
        assert manager.wait_for_pipeline_done(eid, 10)
        assert status_of(manager, eid)["status"] == "failed"
        assert manager.is_query_active(eid) is False

    def test_partial_failure_with_a_live_query_is_active(self, make_manager):
        manager = make_manager()
        eid = run(
            manager,
            "p",
            [node("a"), node("b", output={"format": "console", "options": {"fail": 1}})],
        )
        assert status_of(manager, eid)["status"] == "partial_failure"
        assert manager.is_query_active(eid) is True


class TestFailedTerminatingUpstream:
    def test_dependants_are_skipped_when_the_upstream_dies(self, make_manager):
        manager = make_manager()
        up = node(
            "up",
            output={"format": "console", "options": {"await_fail": 1}},
            streaming={"trigger": {"type": "available_now"}},
        )
        eid = run(manager, "p", [up, node("down", depends_on=["up"])])
        status = status_of(manager, eid)
        assert "down" not in status["query_statuses"]
        assert "down" in status["skipped_nodes"]
        assert "up" in status["failed_nodes"]


# ------------------------------------------------------------ checkpoint ownership


class TestEndedQueriesReleaseTheirCheckpoint:
    def test_restart_node_works_on_a_query_that_already_ended(self, make_manager):
        manager = make_manager()
        eid = run(manager, "p", [node("a")])
        query_of(manager, eid, "a")._active = False  # the node failed
        assert manager.restart_node(eid, "a") is True
        assert query_of(manager, eid, "a").isActive

    def test_a_finished_run_does_not_block_the_next_one(self, make_manager):
        manager = make_manager()
        once = node("a", streaming={"trigger": {"type": "available_now"}})
        first = run(manager, "p", [once])
        query_of(manager, first, "a")._active = False
        second = run(manager, "p", [once])
        assert status_of(manager, second)["status"] == "running"

    def test_a_live_query_still_owns_its_checkpoint(self, make_manager):
        manager = make_manager()
        run(manager, "p", [node("a")])
        second = run(manager, "p", [node("a")])
        failed = status_of(manager, second)["failed_nodes"]
        assert "already in use" in failed["a"]

    def test_the_reservation_check_ignores_entries_it_cannot_judge(self):
        def boom(_query):
            raise RuntimeError("py4j hiccup")

        import threading

        active = {"k": {"query": object(), "resolved_checkpoint": "/c", "node_name": "n"}}
        with pytest.raises(StreamingConfigurationError):
            CheckpointManager(SimpleNamespace()).validate_and_reserve(
                "/c", "other", active, threading.Lock(), is_active=boom
            )


# ------------------------------------------------------------------------ shutdown


class TestShutdownReachesPartialFailurePipelines:
    def test_shutdown_stops_the_live_queries_of_a_partial_failure_pipeline(self, make_manager):
        manager = make_manager()
        eid = run(
            manager,
            "p",
            [node("a"), node("b", output={"format": "console", "options": {"fail": 1}})],
        )
        live = query_of(manager, eid, "a")
        assert status_of(manager, eid)["status"] == "partial_failure" and live.isActive
        manager.shutdown(timeout_seconds=2)
        assert not live.isActive

    def test_list_running_pipelines_includes_it_while_a_query_is_up(self, make_manager):
        manager = make_manager()
        manager._status_cache_ttl = 0  # read live state, not the 2 s cache
        eid = run(
            manager,
            "p",
            [node("a"), node("b", output={"format": "console", "options": {"fail": 1}})],
        )
        assert [s["execution_id"] for s in manager.list_running_pipelines()] == [eid]
        query_of(manager, eid, "a")._active = False
        assert manager.list_running_pipelines() == []

    def test_a_shut_down_manager_says_so(self, make_manager):
        manager = make_manager()
        assert manager.is_shut_down is False
        manager.shutdown(timeout_seconds=1)
        assert manager.is_shut_down is True


# -------------------------------------------------------------------- health monitor


class TestHealthMonitorLiveness:
    @staticmethod
    def _query(progress):
        query = FakeQuery("q")
        query.lastProgress = progress
        return query

    def test_an_idle_query_whose_report_timestamp_moves_is_not_stalled(self):
        query = self._query({"batchId": 3, "timestamp": "t0"})
        monitor = QueryHealthMonitor(query, "q", timeout_seconds=0.05)
        assert monitor.check_health() == (True, None)
        time.sleep(0.08)
        query.lastProgress = {"batchId": 3, "timestamp": "t1"}  # no new batch, still reporting
        assert monitor.check_health() == (True, None)

    def test_a_query_that_reports_nothing_new_is_stalled(self):
        query = self._query({"batchId": 3, "timestamp": "t0"})
        monitor = QueryHealthMonitor(query, "q", timeout_seconds=0.05)
        monitor.check_health()
        time.sleep(0.08)
        healthy, error = monitor.check_health()
        assert healthy is False and "stalled" in error

    def test_the_stall_timeout_never_undercuts_the_trigger_interval(self, make_manager):
        manager = make_manager()
        hourly = node("a", streaming={"trigger": {"type": "processing_time", "interval": "1 hour"}})
        assert manager._stall_timeout_seconds(hourly) == 3 * 3600
        assert manager._stall_timeout_seconds(node("a")) == manager.MIN_STALL_TIMEOUT_SECONDS
        assert manager._stall_timeout_seconds({"name": "a"}) == manager.MIN_STALL_TIMEOUT_SECONDS


# ---------------------------------------------------------------------- status data


class TestStatusSnapshot:
    def test_the_snapshot_does_not_carry_connector_options(self, make_manager):
        manager = make_manager()
        cfg = node("a")
        cfg["input"]["options"]["kafka.sasl.jaas.config"] = "password='hunter2'"
        eid = run(manager, "p", [cfg])
        status = status_of(manager, eid)
        assert "pipeline_config" not in status
        assert "hunter2" not in repr(status)

    def test_conflict_checks_get_the_definitions_of_live_pipelines_only(self, make_manager):
        manager = make_manager()
        eid = run(manager, "p", [node("a")])
        assert [c["nodes"][0]["name"] for c in manager.running_pipeline_configs()] == ["a"]
        manager.stop_pipeline(eid)
        assert manager.running_pipeline_configs() == []

    def test_a_cached_status_is_a_copy(self, make_manager):
        manager = make_manager()
        eid = run(manager, "p", [node("a")])
        first = manager.get_pipeline_status(eid)
        first["injected"] = True
        assert "injected" not in manager.get_pipeline_status(eid)

    def test_finished_executions_are_pruned_beyond_the_cap(self, make_manager):
        manager = make_manager()
        manager.MAX_FINISHED_EXECUTIONS = 2
        ids = []
        for _ in range(5):
            eid = run(manager, "p", [node("a")])
            manager.stop_pipeline(eid)
            ids.append(eid)
        run(manager, "p", [node("a")])  # starting one more triggers the prune
        kept = set(manager._running_pipelines)
        assert ids[-1] in kept and ids[0] not in kept
        assert len(kept) <= 4  # 2 finished + the running ones


# ---------------------------------------------------------------- clear checkpoints


def _write_checkpoint(directory: Path):
    (directory / "offsets").mkdir(parents=True)
    (directory / "offsets" / "0").write_text("v1")
    (directory / "metadata").write_text("{}")


class TestClearPipelineCheckpoints:
    def test_clears_node_level_checkpoint_locations_too(self, make_manager, tmp_path):
        manager = make_manager()
        custom = tmp_path / "elsewhere"
        cfg = node(
            "a",
            streaming={
                "trigger": {"type": "processing_time", "interval": "10 seconds"},
                "checkpoint_location": str(custom),
            },
        )
        manager.context.pipelines_config["p"] = {"nodes": [cfg]}
        _write_checkpoint(custom / "p" / "a")

        result = manager.clear_pipeline_checkpoints("p")

        assert result["status"] == "success"
        assert not (custom / "p").exists()
        assert str(custom / "p") in {str(Path(c)) for c in result["cleared"]} or any(
            c.endswith("elsewhere/p") for c in result["cleared"]
        )

    def test_clears_the_default_location_and_names_it(self, make_manager, tmp_path):
        manager = make_manager()
        default = tmp_path / "dev" / "streaming_checkpoints" / "p"
        _write_checkpoint(default / "a")
        result = manager.clear_pipeline_checkpoints("p")
        assert result["status"] == "success" and not default.exists()
        assert Path(result["path"]).name == "p"

    def test_cloud_checkpoints_are_reported_not_pretended(self, make_manager):
        manager = make_manager()
        cfg = node(
            "a",
            streaming={
                "trigger": {"type": "processing_time", "interval": "10 seconds"},
                "checkpoint_location": "s3://bucket/ckpt",
            },
        )
        manager.context.pipelines_config["p"] = {"nodes": [cfg]}
        result = manager.clear_pipeline_checkpoints("p")
        assert result["manual"] == ["s3://bucket/ckpt/p"]

    def test_refuses_a_directory_that_holds_other_files(self, make_manager, tmp_path):
        manager = make_manager()
        default = tmp_path / "dev" / "streaming_checkpoints" / "p"
        default.mkdir(parents=True)
        (default / "notes.txt").write_text("not a checkpoint")
        result = manager.clear_pipeline_checkpoints("p")
        assert result["status"] == "error" and (default / "notes.txt").exists()

    def test_removes_the_empty_directories_of_a_query_that_never_wrote(
        self, make_manager, tmp_path
    ):
        manager = make_manager()
        default = tmp_path / "dev" / "streaming_checkpoints" / "p"
        (default / "a").mkdir(parents=True)
        assert manager.clear_pipeline_checkpoints("p")["status"] == "success"
        assert not default.exists()

    def test_refuses_while_the_pipeline_is_up(self, make_manager):
        manager = make_manager()
        run(manager, "p", [node("a")])
        assert manager.clear_pipeline_checkpoints("p")["status"] == "error"


# -------------------------------------------------------------------------- adaptive


class TestAdaptiveTrigger:
    def test_the_validator_accepts_it_without_an_interval(self):
        StreamingValidator().validate_streaming_node_config(
            node("n", streaming={"trigger": {"type": "adaptive"}})
        )

    def test_history_survives_the_run_that_produced_it(self):
        sink = StreamingProgressSink()
        sink.register_history_key("p_a_exec1", "p::a")
        sink.record({"name": "p_a_exec1", "durationMs": {"triggerExecution": 4000.0}})
        assert sink.get_latest("p_a_exec1")
        sink.forget("p_a_exec1")  # the run ended
        assert sink.get_latest("p_a_exec1") is None
        assert sink.avg_trigger_ms("p::a") == 4000.0

    def test_the_next_run_starts_from_the_measured_interval(self):
        sink = StreamingProgressSink()
        sink.register_history_key("p_a_exec1", "p::a")
        sink.record({"name": "p_a_exec1", "durationMs": {"triggerExecution": 4000.0}})
        scheduler = TriggerScheduler({}, StreamingValidator(), sink)
        trigger = scheduler.configure_trigger(
            {"type": "adaptive"}, query_name="p_a_exec2", history_key="p::a"
        )
        assert trigger == {"processingTime": "6.000 seconds"}  # 4s x 1.5

    def test_without_history_it_uses_the_base_interval(self):
        scheduler = TriggerScheduler({}, StreamingValidator(), StreamingProgressSink())
        assert scheduler.configure_trigger({"type": "adaptive"}, "q", "p::a") == {
            "processingTime": "5 seconds"
        }

    def test_a_query_without_a_history_key_still_forgets_its_window(self):
        sink = StreamingProgressSink()
        sink.record({"name": "q", "durationMs": {"triggerExecution": 10.0}})
        sink.forget("q")
        assert sink.avg_trigger_ms("q") is None

    def test_the_query_manager_registers_the_key_when_it_starts_a_node(self, make_manager):
        manager = make_manager()
        eid = run(manager, "p", [node("a")])
        name = query_of(manager, eid, "a").name
        assert manager.progress_sink._history_key[name] == "p::a"


# ---------------------------------------------------------------------- session conf


class TestSchedulingSettingsAreRestored:
    def test_shuffle_partitions_and_pool_come_back_after_the_start(self):
        conf = {"spark.sql.shuffle.partitions": "200"}
        props = {"spark.scheduler.pool": "default"}
        spark = MagicMock()
        spark.conf.get.side_effect = lambda k, d=None: conf.get(k, d)
        spark.conf.set.side_effect = lambda k, v: conf.__setitem__(k, v)
        spark.sparkContext.getLocalProperty.side_effect = lambda k: props.get(k)
        spark.sparkContext.setLocalProperty.side_effect = lambda k, v: props.__setitem__(k, v)
        spark = MagicMock(
            spec=["conf", "sparkContext"],
            **{"conf": spark.conf, "sparkContext": spark.sparkContext},
        )
        df = SimpleNamespace(sparkSession=spark)

        scheduler = TriggerScheduler({}, StreamingValidator())
        restore = scheduler.apply_query_scheduling(df, "a", {"shuffle_partitions": 4})
        assert conf["spark.sql.shuffle.partitions"] == "4"
        assert props["spark.scheduler.pool"] == "streaming_a"
        restore()
        assert conf["spark.sql.shuffle.partitions"] == "200"
        assert props["spark.scheduler.pool"] == "default"


# ---------------------------------------------------------------------- validators


class TestValidatorMatchesWhatTheEngineCanRun:
    def test_more_than_one_input_or_output_is_rejected(self):
        validator = StreamingValidator()
        two_inputs = node("n")
        two_inputs["inputs"] = [two_inputs.pop("input")] * 2
        with pytest.raises(StreamingValidationError, match="exactly one source"):
            validator.validate_streaming_node_config(two_inputs)
        two_outputs = node("n")
        two_outputs["outputs"] = [two_outputs.pop("output")] * 2
        with pytest.raises(StreamingValidationError, match="exactly one sink"):
            validator.validate_streaming_node_config(two_outputs)

    @pytest.mark.parametrize("key", ["input", "output"])
    def test_a_bare_string_is_rejected(self, key):
        cfg = node("n")
        cfg[key] = "some/path"
        with pytest.raises(StreamingValidationError, match="must be a dictionary"):
            StreamingValidator().validate_streaming_node_config(cfg)

    def test_a_one_element_list_is_what_the_query_manager_runs(self):
        cfg = node("n")
        cfg["inputs"] = [cfg.pop("input")]
        StreamingValidator().validate_streaming_node_config(cfg)
        assert single_spec(cfg, "input")["format"] == "kafka"
        assert single_spec(cfg, "output")["format"] == "console"

    def test_formats_and_trigger_types_are_case_insensitive_like_the_runtime(self):
        cfg = node("n")
        cfg["input"]["format"] = "KAFKA"
        cfg["output"]["format"] = "Console"
        cfg["streaming"] = {"trigger": {"type": "Available_Now"}}
        StreamingValidator().validate_streaming_node_config(cfg)

    def test_a_long_watermark_is_allowed_with_a_warning(self):
        from loguru import logger

        messages = []
        logger.enable("ducta")  # the library is silent until the CLI turns it on
        sink_id = logger.add(lambda m: messages.append(str(m)), level="WARNING")
        try:
            cfg = node("n", streaming={"watermark": {"column": "ts", "delay": "3 hours"}})
            StreamingValidator().validate_streaming_node_config(cfg)
        finally:
            logger.remove(sink_id)
            logger.disable("ducta")
        assert any("exceeds 60 minutes" in m for m in messages)

    def test_an_empty_bootstrap_server_is_rejected(self):
        cfg = node("n")
        cfg["input"]["options"]["kafka.bootstrap.servers"] = ""
        with pytest.raises(StreamingValidationError, match="cannot be empty"):
            StreamingValidator().validate_streaming_node_config(cfg)

    def test_the_default_policy_only_lists_inputs_the_factory_can_build(self):
        from ducta.setting.validators import FormatPolicy

        factory = StreamingReaderFactory({})
        buildable = set(factory.list_supported_formats())
        assert set(FormatPolicy().get_supported_input_formats()) <= buildable

    def test_every_default_output_has_a_writer(self):
        from ducta.setting.validators import FormatPolicy

        factory = StreamingWriterFactory({})
        assert set(FormatPolicy().get_supported_output_formats()) <= set(
            factory.list_supported_formats()
        )

    def test_socket_input_needs_host_and_port(self):
        cfg = node("n", input={"format": "socket", "options": {"host": "h"}})
        with pytest.raises(StreamingValidationError, match="port"):
            StreamingValidator().validate_streaming_node_config(cfg)
        cfg["input"]["options"]["port"] = 9999
        StreamingValidator().validate_streaming_node_config(cfg)


# --------------------------------------------------------------------- transforms


class TestTransformModules:
    def test_an_import_failure_is_part_of_the_not_registered_error(self, make_manager):
        qm = make_manager().query_manager
        with pytest.raises(StreamingConfigurationError, match="could not be imported"):
            qm._get_transform_function({"key": "k", "module": "no_such_module_for_ducta_test"})

    def test_register_transforms_runs_once_per_module(self, make_manager, monkeypatch, tmp_path):
        qm = make_manager().query_manager
        (tmp_path / "ducta_review_transforms.py").write_text(
            "CALLS = []\n"
            "def register_transforms(registry):\n"
            "    CALLS.append(1)\n"
            "    registry.register('t', lambda df: df)\n"
        )
        monkeypatch.syspath_prepend(str(tmp_path))
        cfg = {"key": "t", "module": "ducta_review_transforms"}
        qm._get_transform_function(cfg)
        qm._get_transform_function(cfg)
        import ducta_review_transforms

        assert ducta_review_transforms.CALLS == [1]

    def test_the_hint_no_longer_points_to_a_missing_file(self, make_manager):
        qm = make_manager().query_manager
        with pytest.raises(StreamingConfigurationError) as info:
            qm._get_registered_transformation("missing")
        assert "run_streaming_fraud" not in str(info.value)

    def test_an_unhashable_callable_can_still_be_inspected(self, make_manager):
        class Transform:
            __hash__ = None  # defines __eq__-style unhashability

            def __call__(self, df):
                return df

        qm = make_manager().query_manager
        assert qm._call_transform_function(Transform(), "df", None) == "df"


# ------------------------------------------------------------------ small hardening


class TestSmallHardening:
    def test_a_dict_context_is_honoured_by_the_manager(self, tmp_path):
        context = {
            "spark": MagicMock(),
            "global_config": {"streaming_node_start_retries": 3},
            "output_path": str(tmp_path),
        }
        manager = StreamingPipelineManager(context)
        try:
            assert manager.node_start_retry_attempts == 3
        finally:
            manager.shutdown(timeout_seconds=1)

    def test_error_context_may_be_none(self):
        error = StreamingConfigurationError("x", config_section="s", context=None)
        assert "config_section=s" in str(error)
        assert StreamingValidationError("x", field="f", context=None).context == {"field": "f"}

    def test_the_callers_context_dict_is_not_mutated(self):
        shared = {"a": 1}
        StreamingValidationError("x", field="f", context=shared)
        assert shared == {"a": 1}

    def test_kinesis_without_a_connector_explains_itself(self):
        from ducta.stream.readers import KinesisStreamingReader

        spark = MagicMock()
        spark.readStream.format.return_value.option.return_value.option.return_value.load.side_effect = RuntimeError(
            "Failed to find data source: kinesis"
        )
        reader = KinesisStreamingReader({"spark": spark})
        from ducta.stream.exceptions import StreamingError

        with pytest.raises(StreamingError, match="no built-in Kinesis source"):
            reader.read_stream({"options": {"streamName": "s", "region": "r"}})


class TestNewSourcesAndSinks:
    def test_rate_and_socket_readers_apply_their_options(self):
        spark = MagicMock()
        factory = StreamingReaderFactory({"spark": spark})
        factory.get_reader("rate").read_stream({"options": {"rowsPerSecond": 5}})
        spark.readStream.format.assert_called_with("rate")
        spark.readStream.format.return_value.option.assert_called_with("rowsPerSecond", "5")

        factory.get_reader("socket").read_stream({"options": {"host": "h", "port": 1}})
        spark.readStream.format.assert_called_with("socket")

    def test_delta_is_an_alias_of_delta_stream(self):
        factory = StreamingReaderFactory({"spark": MagicMock()})
        assert type(factory.get_reader("delta")).__name__ == "DeltaStreamingReader"

    def test_the_memory_writer_starts_a_memory_sink(self):
        write_stream = MagicMock()
        writer = StreamingWriterFactory({}).get_writer("memory")
        writer.write_stream(write_stream, {"options": {}})
        write_stream.format.assert_called_with("memory")
        write_stream.format.return_value.start.assert_called_once()


# ----------------------------------------------------------------------- executors


class TestExecutorsKeepStreamsAlive:
    def test_unified_state_cleanup_can_leave_the_streams_running(self):
        from ducta.core.pipeline_state import NodeType, UnifiedPipelineState

        stopped = []
        state = UnifiedPipelineState()
        state.register_node("s", NodeType.STREAMING, [])
        state.register_streaming_query("s", "EXEC")
        state.set_streaming_stopper(lambda eid: stopped.append(eid) or True)
        state.cleanup(stop_streaming=False)
        assert stopped == []

        state.register_node("s", NodeType.STREAMING, [])
        state.register_streaming_query("s", "EXEC")
        state.set_streaming_stopper(lambda eid: stopped.append(eid) or True)
        state.cleanup()
        assert stopped == ["EXEC"]

    def test_a_streaming_run_is_not_bounded_by_the_execution_timeout(self):
        from ducta.core.executors.streaming import StreamingExecutor

        executor = StreamingExecutor.__new__(StreamingExecutor)
        executor.streaming_manager = MagicMock()
        executor.timeout_seconds = 3600
        executor._wait_for_streaming_pipeline("eid")
        executor.streaming_manager.wait_for_pipeline_done.assert_called_once_with(
            "eid", timeout=None
        )

    def test_the_executor_replaces_a_manager_that_a_sync_run_shut_down(self):
        from ducta.core.executors.streaming import StreamingExecutor

        executor = StreamingExecutor.__new__(StreamingExecutor)
        executor.context = SimpleNamespace(spark=None, global_config={})
        executor._max_streaming_pipelines = 2
        old = MagicMock(is_shut_down=True)
        executor.streaming_manager = old
        executor._ensure_manager()
        try:
            assert executor.streaming_manager is not old
            assert executor.streaming_manager.is_shut_down is False
        finally:
            executor.streaming_manager.shutdown(timeout_seconds=1)

    def test_the_hybrid_executor_waits_without_a_deadline_and_can_shut_down(self):
        from ducta.core.executors.hybrid import HybridExecutor

        executor = HybridExecutor.__new__(HybridExecutor)
        executor.streaming_manager = MagicMock()
        executor._wait_for_streaming_completion(["a", "b"])
        calls = executor.streaming_manager.wait_for_pipeline_done.call_args_list
        assert [c.kwargs["timeout"] for c in calls] == [None, None]
        executor.shutdown()
        executor.streaming_manager.shutdown.assert_called_once()

    def test_the_cli_treats_a_node_that_never_started_as_a_failure(self, monkeypatch):
        from ducta.console import execution

        class Executor:
            def wait_for_streaming_startup(self, *a, **k):
                return {}

            def get_streaming_pipeline_status(self, _eid):
                return {
                    "active_queries": 0,
                    "failed_queries": 0,
                    "status": "completed",
                    "failed_nodes": {"b": "boom"},
                }

        monkeypatch.setattr(execution.time, "sleep", lambda _s: None)
        code = execution._stay_in_foreground(Executor(), "p", "eid")
        assert code == execution.ExitCode.EXECUTION_ERROR.value


# ------------------------------------------------------------ UX of running a stream


class TestWhatTheStatusSaysAboutANode:
    def test_a_started_node_carries_its_summary(self, make_manager):
        manager = make_manager()
        eid = run(manager, "p", [node("a")])
        summary = status_of(manager, eid)["node_summaries"]["a"]
        assert summary["source"] == "kafka topic t"
        assert summary["sink"] == "console"
        assert summary["trigger"] == "every 10 seconds"
        assert summary["checkpoint"].endswith("p/a")

    def test_the_summary_never_carries_connection_options(self, make_manager):
        manager = make_manager()
        cfg = node("a")
        cfg["input"]["options"]["kafka.sasl.jaas.config"] = "password='hunter2'"
        eid = run(manager, "p", [cfg])
        assert "hunter2" not in repr(status_of(manager, eid))

    def test_a_node_that_did_not_start_has_none(self, make_manager):
        manager = make_manager()
        eid = run(manager, "p", [node("a", output={"format": "console", "options": {"fail": 1}})])
        assert "a" not in status_of(manager, eid).get("node_summaries", {})

    def test_a_restart_refreshes_it(self, make_manager):
        manager = make_manager()
        eid = run(manager, "p", [node("a")])
        manager._running_pipelines[eid]["node_summaries"].clear()
        assert manager.restart_node(eid, "a") is True
        assert "a" in status_of(manager, eid)["node_summaries"]

    def test_a_started_pipeline_lists_its_nodes_upstream_first(self, make_manager):
        manager = make_manager()
        eid = run(manager, "p", [node("silver", depends_on=["bronze"]), node("bronze")])
        assert status_of(manager, eid)["node_order"] == ["bronze", "silver"]

    def test_the_manager_knows_which_executions_it_started(self, make_manager):
        manager = make_manager()
        eid = run(manager, "p", [node("a")])
        assert manager.has_execution(eid) and not manager.has_execution("other")


class TestFacadeRestartsInTheOwningManager:
    def test_it_asks_the_manager_that_started_the_execution(self):
        from ducta.core.executors.facade import PipelineExecutor

        calls = []

        def manager(owns):
            return SimpleNamespace(
                has_execution=lambda eid: owns,
                restart_node=lambda eid, n: calls.append((eid, n)) or True,
            )

        facade = PipelineExecutor.__new__(PipelineExecutor)
        facade._streaming_executor = SimpleNamespace(streaming_manager=manager(False))
        facade._hybrid_executor = SimpleNamespace(streaming_manager=manager(True))
        assert facade.restart_streaming_node("e1", "n") is True
        assert calls == [("e1", "n")]

    def test_nobody_owning_it_is_a_plain_false(self):
        from ducta.core.executors.facade import PipelineExecutor

        facade = PipelineExecutor.__new__(PipelineExecutor)
        facade._streaming_executor = None
        facade._hybrid_executor = None
        assert facade.restart_streaming_node("e1", "n") is False


class TestTheLogIsQuieter:
    def test_a_query_is_announced_on_one_line(self, make_manager):
        from loguru import logger

        manager = make_manager()
        messages = []
        logger.enable("ducta")
        sink_id = logger.add(lambda m: messages.append(m.record["message"]), level="INFO")
        try:
            run(manager, "p", [node("a")])
        finally:
            logger.remove(sink_id)
            logger.disable("ducta")
        configuring = [m for m in messages if "Configuring streaming query" in m]
        assert len(configuring) == 1
        assert "mode=append" in configuring[0] and "processingTime 10 seconds" in configuring[0]
        assert not any(m.strip().startswith("- Output mode") for m in messages)

    def test_the_scheduler_pool_warning_is_silenced_once_per_context(self):
        from ducta.stream import trigger_scheduler

        context = MagicMock()
        trigger_scheduler._QUIETED_CONTEXTS.discard(id(context))
        trigger_scheduler._quiet_fair_pool_warning(context)
        trigger_scheduler._quiet_fair_pool_warning(context)
        configurator = context._jvm.org.apache.logging.log4j.core.config.Configurator
        configurator.setLevel.assert_called_once()
        assert (
            configurator.setLevel.call_args.args[0]
            == "org.apache.spark.scheduler.FairSchedulableBuilder"
        )

    def test_a_spark_without_log4j2_keeps_the_warning_and_still_starts(self):
        from ducta.stream import trigger_scheduler

        class NoJvm:
            @property
            def _jvm(self):
                raise RuntimeError("no jvm")

        context = NoJvm()
        trigger_scheduler._quiet_fair_pool_warning(context)  # must not raise


class TestWhatARunProcessed:
    def test_a_stopped_pipeline_keeps_the_totals_the_sink_forgets(self, make_manager):
        manager = make_manager()
        eid = run(manager, "p", [node("a")])
        name = query_of(manager, eid, "a").name
        manager.progress_sink.record({"name": name, "batchId": 0, "numInputRows": 30})
        manager.progress_sink.record({"name": name, "batchId": 1, "numInputRows": 12})
        assert status_of(manager, eid)["totals"]["a"] == {"rows": 42.0, "batches": 2}  # live
        manager.stop_pipeline(eid)
        assert manager.progress_sink.totals(name) is None  # the sink let go of it
        assert status_of(manager, eid)["totals"]["a"] == {
            "rows": 42.0,
            "batches": 2,
        }  # the run kept it

    def test_the_stop_sequence_is_not_logged_at_info(self, make_manager):
        from loguru import logger

        manager = make_manager()
        eid = run(manager, "p", [node("a")])
        messages = []
        logger.enable("ducta")
        sink_id = logger.add(lambda m: messages.append(m.record["message"]), level="INFO")
        try:
            manager.stop_pipeline(eid)
        finally:
            logger.remove(sink_id)
            logger.disable("ducta")
        assert not any("Stopping query" in m or "stopped successfully" in m for m in messages)
