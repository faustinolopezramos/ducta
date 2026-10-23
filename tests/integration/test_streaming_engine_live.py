"""The stream engine against a real Spark session: the new sources and sink, the
session settings a start must not leak, and an idle query that is healthy.

Everything else under ``tests/stream`` runs on fakes; these are the checks that
only genuine Spark objects can answer.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from ducta.stream.pipeline_manager import QueryHealthMonitor, StreamingPipelineManager

pytestmark = pytest.mark.spark


@pytest.fixture
def manager(spark, tmp_path):
    context = SimpleNamespace(
        spark=spark,
        global_config={"streaming_node_start_retries": 1},
        output_path=str(tmp_path),
        env="dev",
        format_policy=None,
        nodes_config={},
        pipelines_config={},
    )
    mgr = StreamingPipelineManager(context)
    yield mgr
    mgr.shutdown(timeout_seconds=20)


def _node(name, source, sink, trigger="1 second"):
    return {
        "name": name,
        "input": source,
        "output": sink,
        "streaming": {"trigger": {"type": "processing_time", "interval": trigger}},
    }


def _start(manager, nodes):
    eid = manager.start_pipeline("live", {"type": "streaming", "nodes": nodes})
    assert manager.wait_for_pipeline_started(eid, 60)
    status = manager.get_pipeline_status(eid, force_refresh=True)
    assert status["status"] == "running", status
    return eid


def test_rate_source_to_memory_sink_runs_end_to_end(manager, spark):
    node = _node(
        "gen",
        {"format": "rate", "options": {"rowsPerSecond": 20}},
        {"format": "memory"},
    )
    eid = _start(manager, [node])
    query = manager._running_pipelines[eid]["queries"]["gen"]

    deadline = time.time() + 60
    rows = 0
    while time.time() < deadline and rows == 0:
        rows = spark.table(query.name).count()
        time.sleep(0.5)
    assert rows > 0, "the memory sink never received rows from the rate source"
    assert {"timestamp", "value"} <= set(spark.table(query.name).columns)


def test_starting_a_query_leaves_the_session_settings_alone(manager, spark):
    before = spark.conf.get("spark.sql.shuffle.partitions")
    node = _node("gen", {"format": "rate", "options": {"rowsPerSecond": 1}}, {"format": "memory"})
    node["streaming"]["shuffle_partitions"] = 3
    _start(manager, [node])
    assert spark.conf.get("spark.sql.shuffle.partitions") == before


def test_an_idle_stream_is_not_reported_as_stalled(manager, spark, tmp_path):
    """Spark keeps ``batchId`` while no data arrives but still reports progress;
    the monitor used to read the constant batchId as a hang."""
    spark.conf.set("spark.sql.streaming.noDataProgressEventInterval", "500")
    source_dir = tmp_path / "empty_source"
    source_dir.mkdir()
    node = _node(
        "idle",
        {
            "format": "file_stream",
            "file_format": "json",
            "options": {"path": str(source_dir)},
            "schema": "a string",
        },
        {"format": "memory"},
    )
    eid = _start(manager, [node])
    query = manager._running_pipelines[eid]["queries"]["idle"]
    monitor = QueryHealthMonitor(query, "idle", timeout_seconds=2.0)

    deadline = time.time() + 30
    while time.time() < deadline and not query.lastProgress:
        time.sleep(0.25)
    assert query.lastProgress, "Spark reported no progress for an idle query"

    assert monitor.check_health() == (True, None)
    time.sleep(4.0)  # twice the timeout, with no data and an unchanged batchId
    healthy, error = monitor.check_health()
    assert healthy, error


def test_an_adaptive_trigger_written_in_yaml_runs(spark, tmp_path, monkeypatch):
    """`trigger: adaptive` had to clear the project schema, the stream validator and the
    scheduler; each rejected or ignored it."""
    from ducta.api.execution.runner import normalize_execution_context_paths
    from ducta.console.template import TemplateGenerator, TemplateType
    from ducta.core.executors import PipelineExecutor
    from ducta.setting.project_loader import load_project_v2

    root = tmp_path / "sb"
    TemplateGenerator(root).generate_project(TemplateType.STREAMING_BASIC, "sb")
    config = root / "ducta.yaml"
    config.write_text(
        config.read_text().replace(
            "streaming: {trigger: 5s, output_mode: append}",
            "streaming: {trigger: adaptive, output_mode: append}",
        )
    )
    monkeypatch.chdir(root)
    monkeypatch.syspath_prepend(str(root))
    context = load_project_v2(root, "dev")
    normalize_execution_context_paths(context, root)
    engine = PipelineExecutor(context)
    try:
        engine.run_streaming_pipeline("events_stream", mode="async")
        report = engine.wait_for_streaming_startup(engine.get_active_streaming_execution_id(), 60)
        assert report["failed"] == {} and report["skipped"] == {}, report
        assert sorted(report["started"]) == ["clean_events", "ingest_events"]
    finally:
        engine.shutdown()
