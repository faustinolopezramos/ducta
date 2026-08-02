"""Unit tests for LocalStorageBackend.write_dataframe's Spark-style `mode` parity."""

from __future__ import annotations

import pandas as pd

from ducta.mlrun.storage import LocalStorageBackend


def _storage(tmp_path):
    return LocalStorageBackend(base_path=str(tmp_path / "mlops"), enable_circuit_breaker=False)


class TestIgnoreMode:
    def test_ignore_is_a_no_op_when_file_exists(self, tmp_path):
        storage = _storage(tmp_path)
        storage.write_dataframe(pd.DataFrame({"x": [1]}), "data.parquet")
        storage.write_dataframe(pd.DataFrame({"x": [999]}), "data.parquet", mode="ignore")

        result = storage.read_dataframe("data.parquet")
        assert result["x"].tolist() == [1]

    def test_ignore_writes_normally_when_file_absent(self, tmp_path):
        storage = _storage(tmp_path)
        storage.write_dataframe(pd.DataFrame({"x": [1]}), "data.parquet", mode="ignore")
        assert storage.read_dataframe("data.parquet")["x"].tolist() == [1]


class TestAppendMode:
    def test_append_concatenates_onto_existing_rows(self, tmp_path):
        storage = _storage(tmp_path)
        storage.write_dataframe(pd.DataFrame({"x": [1, 2]}), "data.parquet")
        storage.write_dataframe(pd.DataFrame({"x": [3, 4]}), "data.parquet", mode="append")

        result = storage.read_dataframe("data.parquet")
        assert result["x"].tolist() == [1, 2, 3, 4]

    def test_append_creates_file_when_absent(self, tmp_path):
        storage = _storage(tmp_path)
        storage.write_dataframe(pd.DataFrame({"x": [1]}), "data.parquet", mode="append")
        assert storage.read_dataframe("data.parquet")["x"].tolist() == [1]


class TestDefaultAndErrorModes:
    def test_overwrite_replaces_content(self, tmp_path):
        storage = _storage(tmp_path)
        storage.write_dataframe(pd.DataFrame({"x": [1]}), "data.parquet")
        storage.write_dataframe(pd.DataFrame({"x": [2]}), "data.parquet", mode="overwrite")
        assert storage.read_dataframe("data.parquet")["x"].tolist() == [2]

    def test_unknown_mode_fails_if_exists(self, tmp_path):
        import pytest

        storage = _storage(tmp_path)
        storage.write_dataframe(pd.DataFrame({"x": [1]}), "data.parquet")
        with pytest.raises(Exception):
            storage.write_dataframe(pd.DataFrame({"x": [2]}), "data.parquet", mode="error")
