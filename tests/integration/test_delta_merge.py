"""MERGE / upsert into Delta, against a real local Delta Lake session.

Skipped when Spark or the Delta jar is not available (it is resolved from the
local Ivy cache or Maven, like any `spark.jars.packages` entry).
"""

from __future__ import annotations

import pytest

from ducta.core.preflight import PreflightReport, _check_merge_outputs
from ducta.gate.exceptions import ConfigurationError, WriteOperationError
from ducta.gate.fingerprinting import delta_identity, delta_last_operation
from ducta.gate.writers import DeltaWriter, ParquetWriter, validate_merge_spec

pyspark = pytest.importorskip("pyspark")
pytest.importorskip("delta")


@pytest.fixture(scope="module")
def spark(tmp_path_factory):
    """A Delta-enabled session of our own — never someone else's.

    Delta needs its jar on the JVM classpath at SparkContext start. If another
    test already started Spark in this process, getOrCreate would hand back
    that context without the jar *and* leave `spark_catalog = DeltaCatalog` set
    on it, breaking every later test that uses Spark. So: skip instead, and
    stop our session afterwards so later tests start a clean one. Run
    `pytest tests/integration/test_delta_merge.py` on its own to exercise it.
    """
    from pyspark import SparkContext
    from pyspark.sql import SparkSession

    from ducta.setting.session import local_delta_configs

    if SparkContext._active_spark_context is not None:
        pytest.skip("a Spark context without Delta is already running in this process")

    builder = SparkSession.builder.master("local[2]").appName("ducta-merge-tests")
    for key, value in local_delta_configs().items():
        builder = builder.config(key, value)
    session = builder.getOrCreate()
    try:
        probe = str(tmp_path_factory.mktemp("probe") / "t")
        session.range(1).write.format("delta").save(probe)
    except Exception as e:  # noqa: BLE001
        session.stop()
        pytest.skip(f"local Delta session unavailable: {e}")
    session.sparkContext.setLogLevel("ERROR")
    yield session
    session.stop()


def _writer():
    return DeltaWriter({})


def _merge(spark, rows, path, **spec):
    df = spark.createDataFrame(rows, "id INT, amount INT, _deleted BOOLEAN")
    config = {"write_mode": "merge", "merge": {"keys": ["id"], **spec}}
    _writer().write(df, str(path), config)


def _table(spark, path):
    rows = [(r["id"], r["amount"]) for r in spark.read.format("delta").load(str(path)).collect()]
    return sorted(rows, key=lambda r: (r[0] is not None, r[0] or 0, r[1]))


class TestMerge:
    def test_first_merge_creates_the_table(self, spark, tmp_path):
        _merge(spark, [(1, 10, False), (2, 20, False)], tmp_path / "t")
        assert _table(spark, tmp_path / "t") == [(1, 10), (2, 20)]

    def test_upsert_updates_matches_and_inserts_the_rest(self, spark, tmp_path):
        path = tmp_path / "t"
        _merge(spark, [(1, 10, False), (2, 20, False)], path)
        _merge(spark, [(2, 99, False), (3, 30, False)], path)
        assert _table(spark, path) == [(1, 10), (2, 99), (3, 30)]

    def test_the_same_batch_twice_is_idempotent(self, spark, tmp_path):
        path = tmp_path / "t"
        batch = [(1, 10, False), (None, 5, False)]
        _merge(spark, batch, path)
        _merge(spark, batch, path)
        # Null keys match null-safely, so the NULL-keyed row is not duplicated.
        assert _table(spark, path) == [(None, 5), (1, 10)]

    def test_delete_when_removes_matches_and_never_inserts_flagged_rows(self, spark, tmp_path):
        path = tmp_path / "t"
        _merge(spark, [(1, 10, False), (2, 20, False)], path)
        _merge(
            spark,
            [(1, 10, True), (3, 30, True)],
            path,
            delete_when="s._deleted = true",
        )
        assert _table(spark, path) == [(2, 20)]

    def test_update_only_named_columns(self, spark, tmp_path):
        path = tmp_path / "t"
        _merge(spark, [(1, 10, False)], path)
        _merge(spark, [(1, 99, True)], path, when_matched={"update": ["amount"]})
        row = spark.read.format("delta").load(str(path)).collect()[0]
        assert (row["amount"], row["_deleted"]) == (99, False)

    def test_duplicate_keys_in_the_batch_fail_clearly_before_merging(self, spark, tmp_path):
        path = tmp_path / "t"
        _merge(spark, [(1, 10, False)], path)
        with pytest.raises(WriteOperationError, match="appear more than once"):
            _merge(spark, [(1, 11, False), (1, 12, False)], path)
        assert _table(spark, path) == [(1, 10)]

    def test_the_commit_metrics_reach_the_fingerprint_layer(self, spark, tmp_path):
        path = tmp_path / "t"
        _merge(spark, [(1, 10, False)], path)
        _merge(spark, [(1, 11, False), (2, 20, False)], path)
        commit = delta_last_operation(spark, str(path))
        assert commit["operation"] == "MERGE"
        assert commit["metrics"]["numTargetRowsUpdated"] == "1"
        assert commit["metrics"]["numTargetRowsInserted"] == "1"
        identity = delta_identity(spark, str(path))
        assert identity["version"] == commit["version"]


class TestConfiguration:
    def test_merge_on_parquet_is_refused(self, spark, tmp_path):
        df = spark.createDataFrame([(1,)], "id INT")
        with pytest.raises(Exception, match="only for format 'delta'"):
            ParquetWriter.__new__(ParquetWriter)._configure_spark_writer(
                df, {"write_mode": "merge"}
            )

    @pytest.mark.parametrize(
        "spec",
        [
            None,
            {},
            {"keys": ["id"], "when_matched": "upsert"},
            {"keys": ["id"], "when_not_matched": "update"},
            {"keys": ["id"], "delete_when": "1=1; DROP TABLE x"},
        ],
    )
    def test_malformed_spec_is_rejected(self, spec):
        with pytest.raises(ConfigurationError):
            validate_merge_spec(spec)

    def test_preflight_catches_merge_on_non_delta_and_missing_keys(self):
        report = PreflightReport(pipeline_name="p")
        node = {"output": ["a", "b"]}
        outputs = {
            "a": {"format": "parquet", "write_mode": "merge", "merge": {"keys": ["id"]}},
            "b": {"format": "delta", "write_mode": "merge"},
        }
        _check_merge_outputs(report, "n", node, outputs)
        assert len(report.errors) == 2


class TestTimeTravel:
    def test_version_zero_is_honoured_not_treated_as_unset(self, spark, tmp_path):
        """`versionAsOf: 0` used to read the *latest* version: `0 or None` is None.
        A reproduction pinned to a table's first commit then compared against
        data the original run never saw — while its certificate said v0."""
        from ducta.gate.readers import DeltaReader

        path = str(tmp_path / "t")
        spark.range(3).write.format("delta").save(path)
        spark.range(3, 5).write.format("delta").mode("append").save(path)

        reader = DeltaReader({"spark": spark})
        assert reader.read(path, {"versionAsOf": 0}).count() == 3
        assert reader.read(path, {}).count() == 5
