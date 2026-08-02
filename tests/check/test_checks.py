"""Unit tests for the built-in data-quality checks (over pandas)."""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from ducta.check import QUALITY_CHECKS_REGISTRY, DFAdapter


def run_check(name: str, df: pd.DataFrame, **config):
    check = QUALITY_CHECKS_REGISTRY[name]()
    return check.run(df, SimpleNamespace(**config), DFAdapter(df))


class TestEmptyDataset:
    def test_non_empty_passes(self):
        assert run_check("empty_dataset", pd.DataFrame({"id": [1, 2]})).passed

    def test_empty_fails(self):
        assert not run_check("empty_dataset", pd.DataFrame({"id": []})).passed


class TestRowCount:
    def test_within_bounds(self):
        df = pd.DataFrame({"id": [1, 2, 3]})
        assert run_check("row_count", df, min=2, max=10).passed

    def test_below_min_fails(self):
        df = pd.DataFrame({"id": [1, 2, 3]})
        assert not run_check("row_count", df, min=5).passed


class TestDuplicates:
    def test_no_duplicates_passes(self):
        df = pd.DataFrame({"id": [1, 2, 3]})
        assert run_check("duplicates", df, columns=["id"], max_duplicate_rate=0.0).passed

    def test_duplicates_fail(self):
        df = pd.DataFrame({"id": [1, 1, 2]})
        assert not run_check("duplicates", df, columns=["id"], max_duplicate_rate=0.0).passed


class TestRange:
    def test_within_range(self):
        df = pd.DataFrame({"v": [1, 2, 3]})
        assert run_check("range", df, column="v", min_val=0, max_val=10).passed

    def test_out_of_range_fails(self):
        df = pd.DataFrame({"v": [1, 2, 3]})
        assert not run_check("range", df, column="v", min_val=0, max_val=2).passed

    def test_missing_column_param_fails(self):
        df = pd.DataFrame({"v": [1, 2, 3]})
        assert not run_check("range", df).passed

    def test_within_range_min_max_keys(self):
        # Regression: README.md / docs/quality.rst document 'min'/'max' (matching
        # RowCountCheck's convention) — these must work, not just 'min_val'/'max_val'.
        df = pd.DataFrame({"v": [1, 2, 3]})
        assert run_check("range", df, column="v", min=0, max=10).passed

    def test_out_of_range_fails_min_max_keys(self):
        df = pd.DataFrame({"v": [1, 2, 3]})
        assert not run_check("range", df, column="v", min=0, max=2).passed


class TestNullRate:
    def test_no_nulls_passes(self):
        df = pd.DataFrame({"v": [1.0, 2.0, 3.0]})
        assert run_check("null_rate", df, columns=["v"], threshold=0.0).passed

    def test_nulls_exceed_threshold_fails(self):
        df = pd.DataFrame({"v": [1.0, None, 3.0]})
        assert not run_check("null_rate", df, columns=["v"], threshold=0.0).passed


def test_registry_has_expected_checks():
    for name in ("empty_dataset", "null_rate", "row_count", "duplicates", "range", "schema"):
        assert name in QUALITY_CHECKS_REGISTRY
