"""Regressions for the 2026-11-12 review of ducta.stream, on a real Spark session.

Each test failed on the code before the fix (see the review's reproduction scripts).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from ducta.stream.micro_batch import MARKERS_DIR, MicroBatchSink, _FilePublisher

pytestmark = pytest.mark.spark


@pytest.fixture
def context(spark, tmp_path):
    return SimpleNamespace(
        spark=spark,
        global_config={"output_path": str(tmp_path), "environment": "dev"},
        output_path=str(tmp_path),
        env="dev",
    )


def _rows(spark, n=20):
    return spark.createDataFrame(
        [(i, -1.0 if i % 4 == 0 else float(i), f"r{i % 2}") for i in range(n)],
        "id long, amount double, region string",
    )


def _node(tmp_path, fmt="parquet", **extra):
    node = {"name": "clean", "output": {"format": fmt, "path": str(tmp_path / "out")}}
    node.update(extra)
    return node


def _read(spark, fmt, path):
    reader = spark.read.option("header", "true") if fmt == "csv" else spark.read
    return reader.format(fmt).load(str(path))


# ---------------------------------------------------------------------------
# 1. A file sink written per micro-batch is exactly-once, like Spark's own
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fmt", ["parquet", "json", "csv"])
def test_a_batch_run_again_is_not_written_twice(context, spark, tmp_path, fmt):
    node = _node(tmp_path, fmt, quarantine={"reject_when": "amount < 0"})
    sink = MicroBatchSink(context, node, "p", "/nowhere")
    sink(_rows(spark), 0)
    sink(_rows(spark), 0)  # Spark re-runs a batch whose commit never landed
    assert _read(spark, fmt, tmp_path / "out").count() == 15
    quarantine = Path(context.output_path) / "dev" / "quarantine" / "p" / "clean"
    assert _read(spark, fmt, quarantine).count() == 5


def test_a_crash_after_the_write_does_not_duplicate_on_restart(context, spark, tmp_path):
    source, checkpoint = tmp_path / "src", tmp_path / "ck"
    _rows(spark).write.json(str(source))
    node = _node(tmp_path, quarantine={"reject_when": "amount < 0"})

    def run(crash: bool) -> None:
        sink = MicroBatchSink(context, node, "p", str(checkpoint))
        if crash:
            real = sink._append

            def append_then_crash(df, path, fmt, batch_id, suffix=""):
                real(df, path, fmt, batch_id, suffix)
                if not suffix:
                    raise RuntimeError("crash after the write, before Spark's commit")

            sink._append = append_then_crash
        query = (
            spark.readStream.schema("id long, amount double, region string")
            .json(str(source))
            .writeStream.option("checkpointLocation", str(checkpoint))
            .trigger(availableNow=True)
            .foreachBatch(sink)
            .start()
        )
        try:
            query.awaitTermination()
        except Exception:  # noqa: BLE001 — the simulated crash
            pass

    run(crash=True)
    run(crash=False)
    assert spark.read.parquet(str(tmp_path / "out")).count() == 15


def test_an_interrupted_publish_is_redone_whole(spark, tmp_path):
    """Stopped after moving one file (the marker is open): the next run redoes the batch."""
    target = str(tmp_path / "out")
    publisher = _FilePublisher.for_session(spark)
    df = _rows(spark).repartition(4)

    def write(staging):
        df.write.mode("overwrite").parquet(staging)

    class Stop(Exception):
        pass

    make_path = publisher._path
    moved = []

    class _FS:
        def __init__(self, fs):
            self._fs = fs

        def __getattr__(self, name):
            return getattr(self._fs, name)

        def rename(self, source, destination):
            if moved:
                raise Stop()
            moved.append(destination)
            return self._fs.rename(source, destination)

    class _Path:
        def __init__(self, text):
            self._p = make_path(text)

        def __getattr__(self, name):
            return getattr(self._p, name)

        def getFileSystem(self, conf):  # noqa: N802 — Hadoop's name
            return _FS(self._p.getFileSystem(conf))

    publisher._path = _Path
    with pytest.raises(Stop):
        publisher.publish(write, target, "k", 3)
    publisher._path = make_path
    assert spark.read.parquet(target).count() < 20  # half-published

    publisher.publish(write, target, "k", 3)  # Spark runs batch 3 again
    assert spark.read.parquet(target).count() == 20


def test_partitioned_output_keeps_its_folders(context, spark, tmp_path):
    node = _node(tmp_path, "csv")
    node["output"]["partitionBy"] = ["region"]
    node["output"]["options"] = {"header": "true"}
    node["data_quality"] = {"checks": {"empty_dataset": {}}}
    sink = MicroBatchSink(context, node, "p", "/nowhere")
    sink(_rows(spark), 0)
    sink(_rows(spark), 0)
    out = tmp_path / "out"
    assert sorted(p.name for p in out.iterdir() if not p.name.startswith("_")) == [
        "region=r0",
        "region=r1",
    ]
    assert _read(spark, "csv", out).count() == 20


def test_a_new_query_is_not_mistaken_for_an_old_one(context, spark, tmp_path):
    """A cleared checkpoint is a new query id: its batch 0 is new data, not a re-run."""
    node = _node(tmp_path, quarantine={"reject_when": "amount < 0"})
    first = MicroBatchSink(context, node, "p", "/a", query_id_reader=lambda s, c: "query-1")
    second = MicroBatchSink(context, node, "p", "/b", query_id_reader=lambda s, c: "query-2")
    first(_rows(spark), 0)
    second(_rows(spark), 0)
    assert spark.read.parquet(str(tmp_path / "out")).count() == 30
    assert (tmp_path / "out" / MARKERS_DIR).is_dir()


# ---------------------------------------------------------------------------
# 2 / 3. Quality that cannot run stops the batch; the baseline is kept
# ---------------------------------------------------------------------------


def test_quality_that_cannot_run_writes_nothing(context, spark, tmp_path):
    from ducta.check.core import QualityConfigError

    node = _node(
        tmp_path, data_quality={"checks": {"null_rate": {"columns": ["id"], "severity": "warnig"}}}
    )
    with pytest.raises(QualityConfigError):
        MicroBatchSink(context, node, "p", "/nowhere")(_rows(spark), 0)
    assert not (tmp_path / "out").exists()


def test_the_baseline_is_saved_from_the_first_batch_with_rows(context, spark, tmp_path):
    # The baseline is built with toPandas(): Arrow, if an earlier test turned it on in
    # this shared session, cannot run on JDK 21 with Spark 3.5 (a known local limit).
    arrow = "spark.sql.execution.arrow.pyspark.enabled"
    previous = spark.conf.get(arrow, "false")
    spark.conf.set(arrow, "false")
    try:
        _baseline_is_saved(context, spark, tmp_path)
    finally:
        spark.conf.set(arrow, previous)


def _baseline_is_saved(context, spark, tmp_path):
    node = _node(tmp_path, data_quality={"checks": {"anomaly_detection": {"columns": ["amount"]}}})
    sink = MicroBatchSink(context, node, "p", "/nowhere")
    sink(_rows(spark).limit(0), 0)
    sink(_rows(spark), 1)
    assert list(Path(context.output_path).rglob("baseline.json"))
    history = list(Path(context.output_path).rglob("history.json"))
    assert history, "a local JSON history is written every batch"
