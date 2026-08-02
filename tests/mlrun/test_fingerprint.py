"""Unit tests for ducta.mlrun.fingerprint.DataFingerprint."""

from __future__ import annotations

import hashlib
import json
import os
import time

import pandas as pd

from ducta.mlrun.fingerprint import DataFingerprint


def _write(tmp_path, name, df):
    p = tmp_path / name
    df.to_csv(p, index=False)
    return str(p)


class TestFastMode:
    def test_produces_fingerprint(self, tmp_path):
        df = pd.DataFrame({"id": [1, 2, 3]})
        path = _write(tmp_path, "a.csv", df)
        fp = DataFingerprint.from_file_and_df("ds", path, df, mode="fast")
        assert fp.fingerprint
        assert fp.row_count == 3

    def test_identical_data_same_fingerprint(self, tmp_path):
        df = pd.DataFrame({"id": [1, 2, 3]})
        p1 = _write(tmp_path, "a.csv", df)
        p2 = _write(tmp_path, "b.csv", df)
        f1 = DataFingerprint.from_file_and_df("ds", p1, df, mode="fast")
        f2 = DataFingerprint.from_file_and_df("ds", p2, df, mode="fast")
        assert f1.fingerprint == f2.fingerprint

    def test_mtime_excluded_from_hash(self, tmp_path):
        df = pd.DataFrame({"id": [1, 2, 3]})
        path = _write(tmp_path, "a.csv", df)
        f1 = DataFingerprint.from_file_and_df("ds", path, df, mode="fast")
        # Bump mtime without changing content
        future = time.time() + 10_000
        os.utime(path, (future, future))
        f2 = DataFingerprint.from_file_and_df("ds", path, df, mode="fast")
        assert f1.fingerprint == f2.fingerprint

    def test_different_data_different_fingerprint(self, tmp_path):
        df1 = pd.DataFrame({"id": [1, 2, 3]})
        df2 = pd.DataFrame({"id": [1, 2, 3, 4]})
        p1 = _write(tmp_path, "a.csv", df1)
        p2 = _write(tmp_path, "b.csv", df2)
        f1 = DataFingerprint.from_file_and_df("ds", p1, df1, mode="fast")
        f2 = DataFingerprint.from_file_and_df("ds", p2, df2, mode="fast")
        assert f1.fingerprint != f2.fingerprint


class TestFullMode:
    def test_identical_files_same_hash(self, tmp_path):
        df = pd.DataFrame({"id": [1, 2, 3]})
        p1 = tmp_path / "a.bin"
        p2 = tmp_path / "b.bin"
        p1.write_bytes(b"same-bytes")
        p2.write_bytes(b"same-bytes")
        f1 = DataFingerprint.from_file_and_df("ds", str(p1), df, mode="full")
        f2 = DataFingerprint.from_file_and_df("ds", str(p2), df, mode="full")
        assert f1.fingerprint == f2.fingerprint

    def test_to_dict(self, tmp_path):
        df = pd.DataFrame({"id": [1]})
        path = _write(tmp_path, "a.csv", df)
        d = DataFingerprint.from_file_and_df("ds", path, df, mode="fast").to_dict()
        assert "fingerprint" in d and d["input_key"] == "ds"

    def test_detects_tail_corruption_that_raw_byte_hash_would_hide_differently(self, tmp_path):
        # Full mode's fingerprint is content-based (not raw-byte-based), so a
        # tail change is reflected regardless of physical file bytes.
        df1 = pd.DataFrame({"id": range(200)})
        df2 = pd.DataFrame({"id": list(range(150)) + [-1] * 50})
        p1 = _write(tmp_path, "a.csv", df1)
        p2 = _write(tmp_path, "b.csv", df2)
        f1 = DataFingerprint.from_file_and_df("ds", p1, df1, mode="full")
        f2 = DataFingerprint.from_file_and_df("ds", p2, df2, mode="full")
        assert f1.fingerprint != f2.fingerprint

    def test_row_order_change_alone_does_not_flip_fingerprint_when_df_unchanged(self, tmp_path):
        # Reordering the physical file's bytes (a non-deterministic re-export)
        # must not produce a different fingerprint when the DataFrame content
        # handed in is the same — full mode hashes DataFrame content, not bytes.
        df = pd.DataFrame({"id": [1, 2, 3]})
        p1 = tmp_path / "a.csv"
        p2 = tmp_path / "b.csv"
        p1.write_text("id\n1\n2\n3\n")
        p2.write_text("id\n3\n2\n1\n")  # different bytes, same df passed below
        f1 = DataFingerprint.from_file_and_df("ds", str(p1), df, mode="full")
        f2 = DataFingerprint.from_file_and_df("ds", str(p2), df, mode="full")
        assert f1.fingerprint == f2.fingerprint
        assert f1.raw_file_hash != f2.raw_file_hash  # raw hash still tells them apart


class TestSampleIndexInsensitivity:
    def test_same_values_different_index_same_sample_hash(self, tmp_path):
        df1 = pd.DataFrame({"id": [1, 2, 3]})
        df2 = pd.DataFrame({"id": [1, 2, 3]}, index=[10, 20, 30])
        path = _write(tmp_path, "a.csv", df1)
        f1 = DataFingerprint.from_file_and_df("ds", path, df1, mode="fast")
        f2 = DataFingerprint.from_file_and_df("ds", path, df2, mode="fast")
        assert f1.sample_hash == f2.sample_hash


class TestTailCorruptionDetectedByFastMode:
    def test_corruption_past_sample_window_is_detected(self, tmp_path):
        # Before the head+tail+middle sampling fix, a change concentrated past
        # row 100 (the old sample_rows default) was invisible to fast mode.
        df1 = pd.DataFrame({"id": range(200)})
        df2 = pd.DataFrame({"id": list(range(150)) + [-1] * 50})
        p1 = _write(tmp_path, "a.csv", df1)
        p2 = _write(tmp_path, "b.csv", df2)
        f1 = DataFingerprint.from_file_and_df("ds", p1, df1, mode="fast")
        f2 = DataFingerprint.from_file_and_df("ds", p2, df2, mode="fast")
        assert f1.fingerprint != f2.fingerprint


class TestSchemaColumns:
    """Coverage for the `columns` field added for schema-drift detection."""

    def test_columns_populated_list_dtypes(self, tmp_path):
        df = pd.DataFrame({"id": [1, 2], "name": ["a", "b"]})
        path = _write(tmp_path, "a.csv", df)
        fp = DataFingerprint.from_file_and_df("ds", path, df, mode="fast")
        assert fp.columns == {"id": str(df["id"].dtype), "name": str(df["name"].dtype)}

    def test_columns_populated_dict_dtypes(self):
        class FakeDf:
            dtypes = {"a": "int64", "b": "string"}

        fp = DataFingerprint(input_key="k", filepath="f")
        fp._capture_schema(FakeDf())
        assert fp.columns == {"a": "int64", "b": "string"}

    def test_schema_hash_unchanged_with_columns_field(self):
        """`columns` must be additive: schema_hash keeps hashing the exact same
        string it always did, so old fingerprints stay comparable after upgrade."""

        class FakeDf:
            dtypes = {"a": "int64", "b": "string"}

        fp = DataFingerprint(input_key="k", filepath="f")
        fp._capture_schema(FakeDf())

        expected_schema_str = json.dumps({"a": "int64", "b": "string"}, sort_keys=True)
        expected_hash = hashlib.sha256(expected_schema_str.encode()).hexdigest()
        assert fp.schema_hash == expected_hash

    def test_columns_included_in_to_dict(self, tmp_path):
        df = pd.DataFrame({"id": [1]})
        path = _write(tmp_path, "a.csv", df)
        d = DataFingerprint.from_file_and_df("ds", path, df, mode="fast").to_dict()
        assert "columns" in d
        assert d["columns"] == {"id": str(df["id"].dtype)}
