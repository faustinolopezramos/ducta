"""Unit tests for ducta.check.storage: pipeline scoping and
ContextAwareStorageBackend.append_history locking."""

from __future__ import annotations

import sys
import threading
import time
import types

import pytest

from ducta.check.storage import ContextAwareStorageBackend, FileStorageBackend, _exclusive_lock


class TestFileStorageBackendPipelineScoping:
    def test_history_is_isolated_per_pipeline(self, tmp_path):
        """Regression: two pipelines with a node of the same name must not
        share/overwrite each other's history — the whole point of this change."""
        backend = FileStorageBackend(str(tmp_path))
        backend.append_history("ds", {"score": 0.9}, pipeline_name="pipe_a")
        backend.append_history("ds", {"score": 0.1}, pipeline_name="pipe_b")

        history_a = backend.load_history("ds", pipeline_name="pipe_a")
        history_b = backend.load_history("ds", pipeline_name="pipe_b")

        assert [h["score"] for h in history_a] == [0.9]
        assert [h["score"] for h in history_b] == [0.1]

    def test_report_is_isolated_per_pipeline(self, tmp_path):
        backend = FileStorageBackend(str(tmp_path))
        backend.save_report({"score": 0.9}, "run1", "ds", pipeline_name="pipe_a")
        backend.save_report({"score": 0.1}, "run1", "ds", pipeline_name="pipe_b")

        assert backend.load_report("run1", "ds", pipeline_name="pipe_a")["score"] == 0.9
        assert backend.load_report("run1", "ds", pipeline_name="pipe_b")["score"] == 0.1

    def test_default_pipeline_name_is_adhoc(self, tmp_path):
        backend = FileStorageBackend(str(tmp_path))
        backend.save_report({"score": 1.0}, "run1", "ds")
        assert (tmp_path / ".quality" / "_adhoc" / "ds" / "reports" / "run1.json").exists()

    def test_list_datasets_scoped_to_one_pipeline(self, tmp_path):
        backend = FileStorageBackend(str(tmp_path))
        backend.save_report({"score": 1.0}, "run1", "ds_a", pipeline_name="pipe_a")
        backend.save_report({"score": 1.0}, "run1", "ds_b", pipeline_name="pipe_b")

        assert backend.list_datasets(pipeline_name="pipe_a") == ["ds_a"]
        assert backend.list_datasets(pipeline_name="pipe_b") == ["ds_b"]

    def test_list_datasets_aggregates_with_qualified_names(self, tmp_path):
        """Regression: same dataset_name under two pipelines must not be
        ambiguous when listing across every pipeline."""
        backend = FileStorageBackend(str(tmp_path))
        backend.save_report({"score": 1.0}, "run1", "ds", pipeline_name="pipe_a")
        backend.save_report({"score": 1.0}, "run1", "ds", pipeline_name="pipe_b")

        assert backend.list_datasets() == ["pipe_a/ds", "pipe_b/ds"]


class TestAppendHistoryNonJsonLocking:
    def test_concurrent_appends_no_lost_update(self, tmp_path, monkeypatch):
        """Regression: non-JSON formats (parquet/delta/csv) did a plain
        load-modify-save with no locking, unlike the JSON path (which uses
        _exclusive_lock) — concurrent appends could silently drop entries."""
        backend = ContextAwareStorageBackend({}, format="csv", base_path=str(tmp_path))

        # Bypass the real Writer/ReaderFactory I/O stack (irrelevant to the
        # locking behavior under test, and CSV round-tripping isn't wired up
        # in this bare test environment) with an in-memory store.
        store: dict = {}

        def fake_write(data_list, path):
            store[str(path)] = list(data_list)

        def fake_read(path):
            # A tiny delay widens the read-modify-write race window deterministically
            # (without it, the in-memory fake is fast enough that the race may not
            # manifest every run even on unlocked code).
            time.sleep(0.001)
            return store.get(str(path))

        monkeypatch.setattr(backend, "_write_with_io", fake_write)
        monkeypatch.setattr(backend, "_read_with_io", fake_read)

        def worker(i):
            backend.append_history("ds", {"score": i})

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        history = backend.load_history("ds") or []
        assert len(history) == 20


class TestExclusiveLockWindowsFallback:
    def test_uses_msvcrt_when_fcntl_unavailable(self, tmp_path, monkeypatch):
        """Regression: when fcntl isn't available (Windows), the old code
        just yielded without taking any lock at all ("concurrent writes may
        corrupt files"). It must now fall back to msvcrt.locking()."""
        calls = []
        fake_msvcrt = types.SimpleNamespace(
            LK_LOCK=1,
            LK_UNLCK=0,
            locking=lambda fd, mode, nbytes: calls.append((fd, mode, nbytes)),
        )

        monkeypatch.setitem(sys.modules, "fcntl", None)
        monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)

        path = tmp_path / "locked.txt"
        path.write_text("hello")
        with open(path, "r+") as f:
            fd = f.fileno()
            with _exclusive_lock(f):
                pass

        assert calls == [(fd, 1, 1), (fd, 0, 1)]

    def test_yields_without_locking_when_neither_fcntl_nor_msvcrt_exist(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setitem(sys.modules, "fcntl", None)
        monkeypatch.setitem(sys.modules, "msvcrt", None)

        path = tmp_path / "locked.txt"
        path.write_text("hello")
        entered = False
        with open(path, "r+") as f:
            with _exclusive_lock(f):
                entered = True

        assert entered is True


class TestSafeForSparkInference:
    """Regression: ContextAwareStorageBackend.save_report(format="parquet"/etc.)
    silently failed on every successful run — QualityReport.persistence_warnings
    is [] whenever nothing went wrong, and spark.createDataFrame cannot infer
    an element type from a column that is an empty list/None in every sampled
    row (PySparkValueError [CANNOT_DETERMINE_TYPE]). The failure was caught by
    save_report's own `except Exception: logger.warning(...)`, so `reports/`
    stayed empty with no error surfaced to the caller."""

    def test_field_empty_in_every_record_is_json_encoded(self):
        records = [{"a": 1, "w": []}, {"a": 2, "w": []}]
        result = ContextAwareStorageBackend._safe_for_spark_inference(records)
        assert result == [{"a": 1, "w": "[]"}, {"a": 2, "w": "[]"}]

    def test_field_none_in_every_record_is_json_encoded(self):
        records = [{"a": 1, "w": None}]
        result = ContextAwareStorageBackend._safe_for_spark_inference(records)
        assert result == [{"a": 1, "w": "null"}]

    def test_field_with_data_in_at_least_one_record_is_left_alone(self):
        """Spark infers a real type fine here — nothing should be touched."""
        records = [{"a": 1, "w": []}, {"a": 2, "w": ["x"]}]
        result = ContextAwareStorageBackend._safe_for_spark_inference(records)
        assert result == records

    def test_field_non_empty_everywhere_is_left_alone(self):
        records = [{"a": 1, "w": ["x"]}, {"a": 2, "w": ["y"]}]
        result = ContextAwareStorageBackend._safe_for_spark_inference(records)
        assert result == records

    def test_scalar_falsy_values_are_not_touched(self):
        """0 / False / "" are falsy but not container-typed — must not be
        mistaken for the ambiguous-empty-collection case."""
        records = [{"n": 0, "b": False, "s": ""}]
        result = ContextAwareStorageBackend._safe_for_spark_inference(records)
        assert result == records

    def test_empty_record_list_is_returned_unchanged(self):
        assert ContextAwareStorageBackend._safe_for_spark_inference([]) == []

    @pytest.mark.spark
    def test_to_dataframe_no_longer_raises_on_empty_persistence_warnings(self):
        """End-to-end regression check with a real Spark session: the exact
        report shape save_report builds must survive createDataFrame + a
        parquet write, instead of raising CANNOT_DETERMINE_TYPE."""
        from pyspark.sql import SparkSession

        spark = SparkSession.builder.master("local[1]").appName("test_storage").getOrCreate()
        try:
            backend = ContextAwareStorageBackend.__new__(ContextAwareStorageBackend)
            backend.context = types.SimpleNamespace(spark=spark)

            report = {
                "dataset_name": "ds",
                "passed": True,
                "score": 1.0,
                "run_id": "r1",
                "workspace_path": "/tmp",
                "created_at": "2026-01-01T00:00:00",
                "elapsed_seconds": 0.1,
                "results": "[]",
                "errors_count": 0,
                "warnings_count": 0,
                "checks_count": 0,
                "persistence_warnings": [],
            }

            df = backend._to_dataframe([report])
            assert df.count() == 1
        finally:
            spark.stop()
