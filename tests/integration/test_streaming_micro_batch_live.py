"""The micro-batch path (quarantine, quality gate) against a real Spark session.

Parquet sinks: the Delta parts (idempotent appends, MERGE) need a delta-spark that
matches the installed Spark, and run in the Delta live tests when there is one.
"""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from ducta.stream.micro_batch import MicroBatchSink
from ducta.stream.pipeline_manager import StreamingPipelineManager

pytestmark = pytest.mark.spark


@pytest.fixture
def context(spark, tmp_path):
    return SimpleNamespace(
        spark=spark,
        global_config={"output_path": str(tmp_path), "streaming_node_start_retries": 1},
        output_path=str(tmp_path),
        env="dev",
        format_policy=None,
        nodes_config={},
        pipelines_config={},
    )


def _orders(spark):
    return spark.createDataFrame(
        [(1, 10.0), (2, -5.0), (None, 3.0), (4, 7.5)], "order_id int, amount double"
    )


def _node(tmp_path, **extra):
    node = {
        "name": "orders",
        "input": {"format": "rate"},
        "output": {"format": "parquet", "path": str(tmp_path / "silver")},
    }
    node.update(extra)
    return node


def _sink(context, node):
    return MicroBatchSink(context, node, "sales", "/nowhere", run_id="run-1")


def test_rejected_rows_go_to_quarantine_with_the_reason(context, spark, tmp_path):
    batches = []
    node = _node(tmp_path, quarantine={"reject_when": "order_id IS NULL OR amount < 0"})
    sink = _sink(context, node)
    sink.on_batch = batches.append

    sink(_orders(spark), 0)

    kept = spark.read.parquet(str(tmp_path / "silver"))
    assert sorted(r.order_id for r in kept.collect()) == [1, 4]
    rejected = spark.read.parquet(str(tmp_path / "dev" / "quarantine" / "sales" / "orders"))
    rows = rejected.collect()
    assert sorted(r.amount for r in rows) == [-5.0, 3.0]
    assert {r._ducta_reason for r in rows} == {"reject_when: order_id IS NULL OR amount < 0"}
    assert {r._ducta_batch_id for r in rows} == {0}
    assert {r._ducta_run_id for r in rows} == {"run-1"}
    assert batches == [
        {
            "node": "orders",
            "batch_id": 0,
            "rows_in": 4,
            "rows_written": 2,
            "rows_quarantined": 2,
            "gate": None,
            "duration_ms": batches[0]["duration_ms"],
        }
    ]


def test_a_blocking_gate_quarantines_the_whole_batch(context, spark, tmp_path):
    batches = []
    node = _node(
        tmp_path,
        data_quality={"checks": {"row_count": {"min": 1000}}, "quality_gate": {"max_errors": 0}},
    )
    sink = _sink(context, node)
    sink.on_batch = batches.append

    sink(_orders(spark), 3)

    assert not (tmp_path / "silver").exists()
    rejected = spark.read.parquet(str(tmp_path / "dev" / "quarantine" / "sales" / "orders"))
    assert rejected.count() == 4
    assert all(r._ducta_reason.startswith("quality_gate: ") for r in rejected.collect())
    assert batches[0]["gate"] == "block"
    assert batches[0]["rows_written"] == 0


def test_a_passing_gate_writes_the_batch(context, spark, tmp_path):
    batches = []
    node = _node(
        tmp_path,
        data_quality={"checks": {"row_count": {"min": 1}}, "quality_gate": {"max_errors": 0}},
    )
    sink = _sink(context, node)
    sink.on_batch = batches.append

    sink(_orders(spark), 0)

    assert spark.read.parquet(str(tmp_path / "silver")).count() == 4
    assert batches[0]["gate"] == "pass"


def test_a_stream_quarantines_while_it_runs(context, spark, tmp_path):
    manager = StreamingPipelineManager(context)
    node = {
        **_node(tmp_path, quarantine={"reject_when": "value % 2 = 1"}),
        "input": {"format": "rate", "options": {"rowsPerSecond": 20}},
        "streaming": {"trigger": {"type": "processing_time", "interval": "1 second"}},
    }
    seen = []
    manager.query_manager.batch_listener = lambda pipeline, eid, stats: seen.append(stats)
    try:
        eid = manager.start_pipeline("sales", {"type": "streaming", "nodes": [node]})
        assert manager.wait_for_pipeline_started(eid, 60)
        deadline = time.time() + 60
        while time.time() < deadline and not any(s["rows_quarantined"] for s in seen):
            time.sleep(0.5)
    finally:
        manager.shutdown(timeout_seconds=20)

    assert any(s["rows_quarantined"] for s in seen), seen
    kept = spark.read.parquet(str(tmp_path / "silver")).collect()
    assert kept and all(r.value % 2 == 0 for r in kept)


def test_a_stream_journals_its_batches(context, spark, tmp_path):
    from ducta.stream.journal import find_run, iter_lines

    manager = StreamingPipelineManager(context)
    node = {
        **_node(tmp_path, quarantine={"reject_when": "value % 2 = 1"}),
        "input": {"format": "rate", "options": {"rowsPerSecond": 20}},
        "streaming": {"trigger": {"type": "processing_time", "interval": "1 second"}},
    }
    events = []
    manager.add_listener(events.append)
    base = str(tmp_path / "dev" / ".ducta" / "streams")
    try:
        eid = manager.start_pipeline(
            "sales", {"type": "streaming", "nodes": [node]}, run_id="live-run"
        )
        assert manager.wait_for_pipeline_started(eid, 60)
        deadline = time.time() + 60
        while time.time() < deadline:
            run = find_run(base, "sales", run_id="live-run")
            lines = list(iter_lines(Path(run["journal_dir"]))) if run else []
            # Progress lines arrive through Spark's listener bus, after the batch.
            quarantined = any(
                line["kind"] == "batch" and line["rows_quarantined"] for line in lines
            )
            if quarantined and any(line["kind"] == "progress" for line in lines):
                break
            time.sleep(0.5)
        manager.stop_pipeline(eid)
    finally:
        manager.shutdown(timeout_seconds=20)

    run = find_run(base, "sales", run_id="live-run")
    assert run["status"] == "stopped"
    kinds = {line["kind"] for line in iter_lines(Path(run["journal_dir"]))}
    assert kinds == {"progress", "batch"}
    finished = [e for e in events if e["kind"] == "finished"]
    assert finished and finished[0]["nodes"]["orders"]["journal"]["rows_quarantined"] > 0
    assert any(e["kind"] == "stream_quarantine" for e in events)
