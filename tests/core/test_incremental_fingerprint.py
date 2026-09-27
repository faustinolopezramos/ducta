"""Fingerprint cost proportional to the batch, not to the table.

Before: every input was hashed in full *before* the node filtered its date
window — a daily run over three years of history scanned three years, every
day, just for the certificate — and `exact` paid a second full scan for a
separate `count()`.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pytest

from ducta.gate.exceptions import ReadOperationError
from ducta.gate.fingerprinting import delta_identity
from ducta.gate.input import InputLoader
from ducta.mlrun.fingerprint import (
    ALGO_DELTA_VERSION,
    ALGO_PANDAS_EXACT,
    ALGO_PANDAS_SAMPLE,
    DataFingerprint,
    comparable,
)

DF = pd.DataFrame(
    {
        "order_date": ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"],
        "amount": [10, 20, 30, 40],
    }
)


def _fp(df=DF, **kw):
    return DataFingerprint.from_file_and_df("k", "/nonexistent", df, mode="auto", **kw)


class TestAuto:
    def test_small_or_unsized_input_is_hashed_in_full(self):
        fp = _fp()
        assert fp.algorithm == ALGO_PANDAS_EXACT
        assert fp.row_count == 4
        assert "auto_selected" in fp.details

    def test_a_windowed_input_is_hashed_in_full_and_says_which_window(self):
        window = {"column": "order_date", "start": "2026-01-02", "end": "2026-01-03"}
        fp = _fp(DF.iloc[1:3], window=window)
        assert fp.algorithm == ALGO_PANDAS_EXACT
        assert fp.details["window"] == window

    def test_an_input_over_the_size_limit_is_sampled_and_says_why(self, tmp_path):
        big = tmp_path / "big.csv"
        big.write_text("x" * 5000)
        fp = DataFingerprint.from_file_and_df("k", str(big), DF, mode="auto", exact_max_bytes=1000)
        assert fp.algorithm == ALGO_PANDAS_SAMPLE
        assert "fingerprint_exact_max_bytes" in fp.details["auto_selected"]
        assert fp.degraded_reason is None  # a policy choice, not a failure

    def test_a_delta_input_is_identified_by_its_commit_without_scanning(self):
        df = MagicMock()  # any access to the data would be a scan
        fp = DataFingerprint.from_file_and_df(
            "k", "/lake/sales", df, mode="auto", delta={"table_id": "t-1", "version": 42}
        )
        assert fp.algorithm == ALGO_DELTA_VERSION
        assert fp.details["delta_version"] == 42
        assert not df.method_calls

    def test_different_delta_versions_are_different_content(self):
        a = _fp(delta={"table_id": "t-1", "version": 41}).to_dict()
        b = _fp(delta={"table_id": "t-1", "version": 42}).to_dict()
        assert comparable(a, b) == (True, None)
        assert a["content_hash"] != b["content_hash"]

    def test_explicit_exact_ignores_the_size_limit(self, tmp_path):
        big = tmp_path / "big.csv"
        big.write_text("x" * 5000)
        fp = DataFingerprint.from_file_and_df("k", str(big), DF, mode="exact", exact_max_bytes=1)
        assert fp.algorithm == ALGO_PANDAS_EXACT


class TestWindowedRead:
    def _loader(self, input_config, fingerprints=None):
        loader = InputLoader.__new__(InputLoader)
        loader._get_dataset_config = lambda key: input_config[key]
        loader._get_filepath = lambda config, key: "/data/" + key
        loader.reader_factory = SimpleNamespace(
            get_reader=lambda fmt: SimpleNamespace(read=lambda path, config: DF.copy())
        )
        loader.context = SimpleNamespace()
        loader._ctx_spark = lambda: None
        recorded = {}

        def record(scope, key, identifier, dataframe, **options):
            recorded[key] = (dataframe, options)
            return None

        loader._record_fingerprint = record
        return loader, recorded

    def test_only_the_window_is_read_and_fingerprinted(self):
        loader, recorded = self._loader(
            {"sales": {"format": "csv", "incremental": {"column": "order_date"}}}
        )
        df = loader._load_single_dataset("sales", "2026-01-02", "2026-01-03")

        assert list(df["amount"]) == [20, 30]
        fingerprinted, options = recorded["sales"]
        assert len(fingerprinted) == 2
        assert options["window"] == {
            "column": "order_date",
            "start": "2026-01-02",
            "end": "2026-01-03",
        }

    def test_without_incremental_the_whole_input_is_read(self):
        loader, recorded = self._loader({"sales": {"format": "csv"}})
        assert len(loader._load_single_dataset("sales", "2026-01-02", "2026-01-03")) == 4
        assert recorded["sales"][1]["window"] is None

    def test_incremental_without_a_column_is_a_clear_error(self):
        loader, _ = self._loader({"sales": {"format": "csv", "incremental": {}}})
        with pytest.raises(ReadOperationError, match="needs a 'column'"):
            loader._load_single_dataset("sales", "2026-01-02", "2026-01-03")


def test_delta_identity_is_none_for_a_non_delta_source(monkeypatch):
    import ducta.gate.fingerprinting as fpm

    monkeypatch.setattr(fpm, "_delta_table", lambda spark, source: None)
    assert delta_identity(MagicMock(), "/data/x") is None


def test_delta_identity_uses_the_pinned_version_when_the_read_was_pinned(monkeypatch):
    import ducta.gate.fingerprinting as fpm

    table = MagicMock()
    table.detail.return_value.first.return_value = {"id": "t-1", "numFiles": 3, "sizeInBytes": 100}
    table.history.return_value.first.return_value = {"version": 99}
    monkeypatch.setattr(fpm, "_delta_table", lambda spark, source: table)
    assert delta_identity(MagicMock(), "/lake/sales", pinned_version=7)["version"] == 7
    assert delta_identity(MagicMock(), "/lake/sales")["version"] == 99
