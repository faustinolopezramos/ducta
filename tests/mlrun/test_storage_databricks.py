"""``DatabricksStorageBackend``: experiment tracking on a Unity Catalog volume.

No Databricks here: the session and ``dbutils`` are doubles, and the backend
falls back to its local cache when there is no session, which is what a laptop
without databricks-connect gets.
"""

from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace
from typing import Any, Dict

import pytest

from ducta.mlrun import storage as storage_mod
from ducta.mlrun.resilience import (
    STORAGE_RETRY_CONFIG,
    CircuitBreakerOpenError,
    RetryExhaustedError,
)
from ducta.mlrun.storage import DatabricksStorageBackend, LocalStorageBackend

#: The backend's own retry rules (a missing file is not retried), tried once.
NO_RETRY = replace(STORAGE_RETRY_CONFIG, max_attempts=1, initial_delay=0, jitter=False)


class FakeFs:
    """``dbutils.fs`` over a dict: path → text."""

    def __init__(self) -> None:
        self.files: Dict[str, str] = {}
        self.fail = False

    def put(self, path: str, content: str, overwrite: bool = False) -> None:
        if self.fail:
            raise OSError("volume unavailable")
        if path in self.files and not overwrite:
            raise OSError(f"{path} exists")
        self.files[path] = content

    def head(self, path: str, max_bytes: int) -> str:
        if self.fail:
            raise OSError("volume unavailable")
        return self.files[path][:max_bytes]

    def ls(self, path: str) -> Any:
        if not any(p == path or p.startswith(path + "/") for p in self.files):
            raise FileNotFoundError(path)
        return [path]

    def rm(self, path: str, recurse: bool = False) -> None:
        if path not in self.files:
            raise FileNotFoundError(path)
        del self.files[path]


def _backend(tmp_path, monkeypatch, *, spark: Any = None, fs: Any = None):
    monkeypatch.setattr(DatabricksStorageBackend, "_init_spark_session", lambda self: None)
    backend = DatabricksStorageBackend(
        "main", "ml", local_cache=str(tmp_path / "cache"), retry_config=NO_RETRY
    )
    backend._spark = spark
    dbutils = SimpleNamespace(fs=fs) if fs is not None else None
    monkeypatch.setattr(backend, "_get_dbutils", lambda: dbutils)
    return backend


class TestNames:
    def test_volume_path_and_table_name(self, tmp_path, monkeypatch):
        backend = _backend(tmp_path, monkeypatch)
        assert (
            backend._get_volume_path("runs/r1.json")
            == "/Volumes/main/ml/mlops_artifacts/runs/r1.json"
        )
        assert backend._get_table_name("runs/index.parquet") == "main.ml.runs_index"
        assert backend._get_table_name("exp-1/metrics.v2") == "main.ml.exp_1_metrics_v2"


class TestOnTheVolume:
    def test_json_round_trip(self, tmp_path, monkeypatch):
        fs = FakeFs()
        backend = _backend(tmp_path, monkeypatch, spark=object(), fs=fs)
        meta = backend.write_json({"run": "r1", "rmse": 1.5}, "runs/r1")
        assert meta.path == "/Volumes/main/ml/mlops_artifacts/runs/r1.json"
        assert json.loads(fs.files[meta.path]) == {"run": "r1", "rmse": 1.5}
        assert backend.read_json("runs/r1") == {"run": "r1", "rmse": 1.5}
        assert not (tmp_path / "cache" / "runs").exists()  # nothing cached locally

    def test_exists_and_delete(self, tmp_path, monkeypatch):
        fs = FakeFs()
        backend = _backend(tmp_path, monkeypatch, spark=object(), fs=fs)
        backend.write_json({"a": 1}, "runs/r1.json")
        assert backend.exists("runs/r1.json")
        backend.delete("runs/r1.json")
        assert not backend.exists("runs/r1.json")
        with pytest.raises(FileNotFoundError):
            backend.delete("runs/r1.json")

    def test_the_breaker_opens_after_five_failures(self, tmp_path, monkeypatch):
        fs = FakeFs()
        fs.fail = True
        backend = _backend(tmp_path, monkeypatch, spark=object(), fs=fs)
        for _ in range(5):
            with pytest.raises(RetryExhaustedError):
                backend.write_json({"a": 1}, "runs/r1")
        with pytest.raises(CircuitBreakerOpenError):
            backend.write_json({"a": 1}, "runs/r1")
        assert backend._stats["errors"] == 5


class TestLocalFallback:
    """Without a session the backend works on its local cache instead."""

    def test_json_round_trip(self, tmp_path, monkeypatch):
        backend = _backend(tmp_path, monkeypatch)
        meta = backend.write_json({"a": 1}, "runs/r1")
        assert meta.path == str(tmp_path / "cache" / "runs" / "r1.json")
        assert backend.read_json("runs/r1") == {"a": 1}
        assert backend.exists("runs/r1.json")

    def test_dataframe_round_trip(self, tmp_path, monkeypatch):
        pd = pytest.importorskip("pandas")
        pytest.importorskip("pyarrow")
        backend = _backend(tmp_path, monkeypatch)
        df = pd.DataFrame({"run": ["r1", "r2"], "rmse": [1.5, 1.2]})
        backend.write_dataframe(df, "runs/index")
        pd.testing.assert_frame_equal(backend.read_dataframe("runs/index"), df)

    def test_the_write_modes_mean_what_they_do_on_local_storage(self, tmp_path, monkeypatch):
        """An append replaced the cached rows with the new ones."""
        pd = pytest.importorskip("pandas")
        pytest.importorskip("pyarrow")
        backend = _backend(tmp_path, monkeypatch)
        backend.write_dataframe(pd.DataFrame({"run": ["r1"]}), "runs/index")
        backend.write_dataframe(pd.DataFrame({"run": ["r2"]}), "runs/index", mode="append")
        assert list(backend.read_dataframe("runs/index")["run"]) == ["r1", "r2"]

        backend.write_dataframe(pd.DataFrame({"run": ["r3"]}), "runs/index", mode="ignore")
        assert list(backend.read_dataframe("runs/index")["run"]) == ["r1", "r2"]

        with pytest.raises(storage_mod.StorageBackendError):
            backend.write_dataframe(pd.DataFrame({"run": ["r4"]}), "runs/index", mode="error")

        backend.write_dataframe(pd.DataFrame({"run": ["r5"]}), "runs/index", mode="overwrite")
        assert list(backend.read_dataframe("runs/index")["run"]) == ["r5"]
        assert [p.name for p in (tmp_path / "cache" / "runs").iterdir()] == ["index.parquet"]

    def test_missing_files_are_not_found(self, tmp_path, monkeypatch):
        backend = _backend(tmp_path, monkeypatch)
        with pytest.raises(FileNotFoundError):
            backend.read_json("runs/none")
        with pytest.raises(FileNotFoundError):
            backend.read_dataframe("runs/none")
        with pytest.raises(FileNotFoundError):
            backend.read_artifact("models/none", str(tmp_path / "out"))

    def test_artifact_round_trip(self, tmp_path, monkeypatch):
        backend = _backend(tmp_path, monkeypatch)
        model = tmp_path / "model"
        model.mkdir()
        (model / "weights.bin").write_bytes(b"123")
        meta = backend.write_artifact(str(model), "models/m1")
        assert meta.size_bytes == 3
        backend.read_artifact("models/m1", str(tmp_path / "restored"))
        assert (tmp_path / "restored" / "weights.bin").read_bytes() == b"123"
        backend.delete("models/m1")
        assert not backend.exists("models/m1")


class TestLocalDiskSpace:
    def _local(self, tmp_path) -> LocalStorageBackend:
        return LocalStorageBackend(str(tmp_path), retry_config=NO_RETRY)

    def test_ten_percent_headroom_is_required(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            storage_mod.shutil, "disk_usage", lambda _p: SimpleNamespace(free=1_050)
        )
        backend = self._local(tmp_path)
        backend._validate_disk_space(900)  # needs 990
        with pytest.raises(storage_mod.DiskSpaceError):
            backend._validate_disk_space(1_000)  # needs 1 100


class TestCredentialsItDoesNotUse:
    """``workspace_url`` and ``token`` were accepted and silently dropped."""

    def test_they_are_named_in_a_warning(self, tmp_path, monkeypatch):
        from loguru import logger

        monkeypatch.setattr(DatabricksStorageBackend, "_init_spark_session", lambda self: None)
        lines = []
        sink = logger.add(lambda m: lines.append(m.record["message"]), level="WARNING")
        logger.enable("ducta")
        try:
            DatabricksStorageBackend(
                "main", "ml", local_cache=str(tmp_path), token="dapi-x", workspace_url=None
            )
        finally:
            logger.disable("ducta")
            logger.remove(sink)
        assert any("ignores token" in line for line in lines)
        assert not any("dapi-x" in line for line in lines)  # never the value
