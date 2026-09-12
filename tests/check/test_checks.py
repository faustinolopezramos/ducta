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


class TestSchema:
    def test_matching_schema_passes(self):
        df = pd.DataFrame({"a": [1], "b": [2]})
        assert run_check("schema", df, expected_columns=["a", "b"]).passed

    def test_missing_column_fails(self):
        df = pd.DataFrame({"a": [1]})
        assert not run_check("schema", df, expected_columns=["a", "b"]).passed

    def test_extra_column_non_strict_passes(self):
        df = pd.DataFrame({"a": [1], "b": [2]})
        assert run_check("schema", df, expected_columns=["a"], strict=False).passed

    def test_extra_column_strict_fails(self):
        df = pd.DataFrame({"a": [1], "b": [2]})
        result = run_check("schema", df, expected_columns=["a"], strict=True)
        assert not result.passed


class TestSchemaDrift:
    def test_no_baseline_passes_and_reports_first_run(self):
        df = pd.DataFrame({"a": [1]})
        result = run_check("schema_drift", df)
        assert result.passed

    def test_missing_column_detected_by_default(self):
        df = pd.DataFrame({"a": [1]})
        result = run_check("schema_drift", df, baseline_schema={"a": "int64", "b": "int64"})
        assert not result.passed
        assert "missing_columns" in result.details

    def test_new_column_ignored_by_default(self):
        df = pd.DataFrame({"a": [1], "b": [2]})
        result = run_check("schema_drift", df, baseline_schema={"a": "int64"})
        assert result.passed

    def test_new_column_detected_when_enabled(self):
        df = pd.DataFrame({"a": [1], "b": [2]})
        result = run_check("schema_drift", df, baseline_schema={"a": "int64"}, detect_new_cols=True)
        assert not result.passed
        assert "new_columns" in result.details

    def test_type_change_detected(self):
        df = pd.DataFrame({"a": pd.Series([1], dtype="int64")})
        result = run_check("schema_drift", df, baseline_schema={"a": "float64"})
        assert not result.passed
        assert "type_changes" in result.details

    def test_type_change_allowed_when_enabled(self):
        df = pd.DataFrame({"a": pd.Series([1], dtype="int64")})
        result = run_check(
            "schema_drift", df, baseline_schema={"a": "float64"}, allow_type_changes=True
        )
        assert result.passed


class TestReferentialIntegrity:
    def test_all_values_exist_in_reference_passes(self):
        df = pd.DataFrame({"customer_id": [1, 2]})
        ref = pd.DataFrame({"id": [1, 2, 3]})
        check = QUALITY_CHECKS_REGISTRY["referential_integrity"]()
        config = SimpleNamespace(
            column="customer_id", reference_dataset="customers", reference_column="id"
        )
        result = check.run(df, config, DFAdapter(df), {"customers": ref})
        assert result.passed

    def test_missing_value_fails(self):
        df = pd.DataFrame({"customer_id": [1, 99]})
        ref = pd.DataFrame({"id": [1, 2, 3]})
        check = QUALITY_CHECKS_REGISTRY["referential_integrity"]()
        config = SimpleNamespace(
            column="customer_id", reference_dataset="customers", reference_column="id"
        )
        result = check.run(df, config, DFAdapter(df), {"customers": ref})
        assert not result.passed

    def test_missing_reference_dataset_fails(self):
        df = pd.DataFrame({"customer_id": [1]})
        check = QUALITY_CHECKS_REGISTRY["referential_integrity"]()
        config = SimpleNamespace(
            column="customer_id", reference_dataset="customers", reference_column="id"
        )
        result = check.run(df, config, DFAdapter(df), {})
        assert not result.passed


class TestCrossTableReferentialIntegrity:
    def test_is_an_alias_of_the_base_referential_check(self):
        df = pd.DataFrame({"customer_id": [1, 2]})
        ref = pd.DataFrame({"id": [1, 2]})
        check = QUALITY_CHECKS_REGISTRY["cross_table_referential"]()
        config = SimpleNamespace(
            column="customer_id", reference_dataset="customers", reference_column="id"
        )
        result = check.run(df, config, DFAdapter(df), {"customers": ref})
        assert result.passed
        assert result.check_name == "cross_table_referential"


class TestDatasetCompleteness:
    def test_complete_a_to_b_passes(self):
        df = pd.DataFrame({"id": [1, 2]})
        ref = pd.DataFrame({"id": [1, 2, 3]})
        check = QUALITY_CHECKS_REGISTRY["dataset_completeness"]()
        config = SimpleNamespace(
            column="id", reference_dataset="ref", reference_column="id", direction="a->b"
        )
        result = check.run(df, config, DFAdapter(df), {"ref": ref})
        assert result.passed

    def test_incomplete_a_to_b_fails(self):
        df = pd.DataFrame({"id": [1, 2, 99]})
        ref = pd.DataFrame({"id": [1, 2, 3]})
        check = QUALITY_CHECKS_REGISTRY["dataset_completeness"]()
        config = SimpleNamespace(
            column="id", reference_dataset="ref", reference_column="id", direction="a->b"
        )
        result = check.run(df, config, DFAdapter(df), {"ref": ref})
        assert not result.passed

    def test_bidirectional_detects_missing_both_ways(self):
        df = pd.DataFrame({"id": [1, 99]})
        ref = pd.DataFrame({"id": [1, 2]})
        check = QUALITY_CHECKS_REGISTRY["dataset_completeness"]()
        config = SimpleNamespace(
            column="id", reference_dataset="ref", reference_column="id", direction="bidirectional"
        )
        result = check.run(df, config, DFAdapter(df), {"ref": ref})
        assert not result.passed
        assert result.details["a_to_b_missing_count"] == 1
        assert result.details["b_to_a_missing_count"] == 1


def test_registry_has_expected_checks():
    for name in (
        "empty_dataset",
        "null_rate",
        "row_count",
        "duplicates",
        "range",
        "schema",
        "schema_drift",
        "referential_integrity",
        "cross_table_referential",
        "dataset_completeness",
    ):
        assert name in QUALITY_CHECKS_REGISTRY
