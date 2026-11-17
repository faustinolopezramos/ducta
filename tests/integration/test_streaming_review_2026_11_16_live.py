"""The stream's second step (2026-11-16 review) on a real Spark session.

T1 a query that dies while running is restarted (and given up on when the failure
is deterministic); T2 a windowed aggregation reports its watermark and state; T3 a
join written in the transform shows the sources Spark really reads. Before the
change: T1 left the node dead for good, T2/T3 kept none of it.
"""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from ducta.stream import StreamingPipelineManager
from ducta.stream.journal import summarize
from ducta.stream.node_state import derive_node_state

pytestmark = pytest.mark.spark


def _manager(spark, tmp_path, **settings):
    context = SimpleNamespace(
        spark=spark,
        output_path=str(tmp_path),
        env="dev",
        global_config={
            "output_path": str(tmp_path),
            "streaming_health_interval_seconds": 0,
            "streaming_restart_backoff_seconds": 0.5,
            **settings,
        },
        pipelines_config={},
    )
    manager = StreamingPipelineManager(context)
    manager.events = []  # type: ignore[attr-defined]
    manager.add_listener(manager.events.append)  # type: ignore[attr-defined]
    return manager


def _node(tmp_path, name, transform=None, **streaming):
    node = {
        "name": name,
        "input": {"format": "rate", "options": {"rowsPerSecond": 10}},
        "output": {"format": "parquet", "path": str(tmp_path / name)},
        "streaming": {"trigger": {"type": "processing_time", "interval": "1 second"}, **streaming},
    }
    if transform:
        node["function"] = {"key": transform}
    return node


def _wait(predicate, timeout=60.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.25)
    return False


def test_a_transient_failure_is_restarted_and_the_stream_goes_on(spark, tmp_path):
    from pyspark.sql import functions as F

    flag = tmp_path / "failed_once"

    @F.udf("long")
    def flaky(value):
        if value >= 5 and not flag.exists():  # one failure, as a broker hiccup would be
            flag.touch()
            raise RuntimeError("transient hiccup")
        return value

    manager = _manager(spark, tmp_path)
    manager.query_manager.transformation_registry.register(
        "flaky", lambda df: df.withColumn("value", flaky("value"))
    )
    eid = manager.start_pipeline(
        "p", {"type": "streaming", "nodes": [_node(tmp_path, "n", "flaky")]}
    )
    try:
        assert manager.wait_for_pipeline_started(eid, 90)
        assert _wait(lambda: any(e["kind"] == "stream_restarted" for e in manager.events))
        assert _wait(
            lambda: derive_node_state("n", manager.get_pipeline_status(eid, True)).state == "active"
            and spark.read.parquet(str(tmp_path / "n")).where("value > 20").count() > 0
        )
        status = manager.get_pipeline_status(eid, True)
        assert status["restarts"]["n"]["attempts"] == 1
        assert not status.get("failed_nodes")
    finally:
        manager.shutdown(20)


def test_a_poisoned_record_is_given_up_on(spark, tmp_path):
    from pyspark.sql import functions as F

    @F.udf("long")
    def poison(value):
        if value == 5:
            raise ValueError("poison record 5")
        return value

    manager = _manager(spark, tmp_path, streaming_restart_max_attempts=2)
    manager.query_manager.transformation_registry.register(
        "poison", lambda df: df.withColumn("value", poison("value"))
    )
    eid = manager.start_pipeline(
        "p", {"type": "streaming", "nodes": [_node(tmp_path, "n", "poison")]}
    )
    try:
        assert manager.wait_for_pipeline_done(eid, 180)
        status = manager.get_pipeline_status(eid, True)
        assert "gave up after 2 restart(s)" in status["failed_nodes"]["n"]
        assert "poison record 5" in status["failed_nodes"]["n"]
        kinds = [e["kind"] for e in manager.events]
        assert kinds.count("stream_restarted") == 2 and "stream_failed" in kinds
        totals = summarize(Path(status["journal_dir"]))["n"]
        assert totals["restarts"] == 2
    finally:
        manager.shutdown(20)


def test_a_windowed_aggregation_reports_its_state(spark, tmp_path):
    from pyspark.sql import functions as F

    manager = _manager(spark, tmp_path)
    manager.query_manager.transformation_registry.register(
        "agg",
        lambda df: df.groupBy(F.window("timestamp", "2 seconds"))
        .agg(F.count("*").alias("n"))
        .select(F.col("window.start").alias("start"), "n"),
    )
    node = _node(
        tmp_path,
        "agg",
        "agg",
        watermark={"column": "timestamp", "delay": "1 second"},
        shuffle_partitions=2,
    )
    eid = manager.start_pipeline("p", {"type": "streaming", "nodes": [node]})
    try:
        assert manager.wait_for_pipeline_started(eid, 90)

        def state():
            return derive_node_state("agg", manager.get_pipeline_status(eid, True))

        # A batch with rows (the rate source's first one is empty) and a state.
        assert _wait(lambda: (state().state_rows or 0) > 0 and (state().last_batch_id or 0) >= 3)
        current = state()
        assert current.state_memory_bytes and current.late_rows_dropped is not None
        assert current.watermark > "1970"  # the epoch until the first window closes
    finally:
        manager.shutdown(20)
    totals = summarize(Path(manager.get_pipeline_status(eid)["journal_dir"]))["agg"]
    assert totals["state_rows"] is not None and totals["watermark"]


def test_a_join_in_the_transform_shows_both_sources(spark, tmp_path):
    from pyspark.sql import functions as F

    def join(df):
        other = (
            df.sparkSession.readStream.format("rate")
            .option("rowsPerSecond", 10)
            .load()
            .withWatermark("timestamp", "5 seconds")
            .select(F.col("value").alias("v2"), F.col("timestamp").alias("t2"))
        )
        return df.join(
            other,
            F.expr(
                "value = v2 AND t2 BETWEEN timestamp - interval 5 seconds "
                "AND timestamp + interval 5 seconds"
            ),
        )

    manager = _manager(spark, tmp_path)
    manager.query_manager.transformation_registry.register("join", join)
    node = _node(
        tmp_path, "joined", "join", watermark={"column": "timestamp", "delay": "5 seconds"}
    )
    eid = manager.start_pipeline("p", {"type": "streaming", "nodes": [node]})
    try:
        assert manager.wait_for_pipeline_started(eid, 90)
        assert _wait(
            lambda: len(
                derive_node_state("joined", manager.get_pipeline_status(eid, True)).sources or []
            )
            == 2
        )
    finally:
        manager.shutdown(20)
