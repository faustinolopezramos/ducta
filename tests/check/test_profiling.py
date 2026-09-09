"""Unit tests for ducta.check.profiling: the assay and the spec it proposes.

The two properties that make a proposed spec worth anything are tested against
data whose defects are known by construction, not against the profiler's own
output:

* it **passes** on the data it was inferred from — otherwise the first thing a
  user sees is their own data failing its own spec;
* it **fails** when that data degrades — a spec that always passes is not a spec.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ducta.check.core import QualityChecksFailed
from ducta.check.engine import ValidationPhaseRunner
from ducta.check.profiling import (
    NOT_INFERABLE_CHECKS,
    classify_dtype,
    infer_spec,
    profile_dataset,
    spec_to_yaml,
)


@pytest.fixture
def dirty():
    """100 rows: 10 nulls in `amount`, `order_id` duplicated 5 times, 4 categories."""
    frame = pd.DataFrame(
        {
            "order_id": list(range(1, 96)) + [1, 2, 3, 4, 5],
            "category": ["a", "b", "c", "d"] * 25,
            "amount": [float(i) for i in range(100)],
        }
    )
    frame.loc[frame.index[:10], "amount"] = np.nan
    return frame


@pytest.fixture
def clean():
    """100 rows, no nulls, `id` genuinely unique."""
    return pd.DataFrame({"id": range(100), "value": [float(i) for i in range(100)]})


def _column(profile, name):
    return next(c for c in profile.columns if c.name == name)


def _verdict(df, spec):
    """Run *spec* and return the names of the checks that failed."""
    runner = ValidationPhaseRunner(workspace_path="/tmp/ducta-test-profiling")
    try:
        report = runner.run(dataset_name="t", df=df, config=spec)
        return [r.check_name for r in report.results if not r.passed]
    except QualityChecksFailed as e:
        return [r.check_name for r in e.results if not r.passed]


class TestClassifyDtype:
    @pytest.mark.parametrize(
        "dtype,expected",
        [
            ("int64", "numeric"),
            ("float64", "numeric"),
            ("IntegerType()", "numeric"),
            ("DoubleType()", "numeric"),
            ("DecimalType(10,2)", "numeric"),
            ("object", "categorical"),
            ("StringType()", "categorical"),
            ("bool", "boolean"),
            ("BooleanType()", "boolean"),
        ],
    )
    def test_engine_type_strings_map_to_a_kind(self, dtype, expected):
        assert classify_dtype(dtype) == expected

    @pytest.mark.parametrize("dtype", ["datetime64[ns]", "TimestampType()", "DateType()"])
    def test_temporal_wins_over_the_digits_in_datetime64(self, dtype):
        # "datetime64[ns]" contains "64"; a numeric test applied first would
        # claim it, and then percentile()/mean_std() would run on a date column.
        assert classify_dtype(dtype) == "temporal"

    def test_an_unknown_type_falls_back_to_categorical(self):
        assert classify_dtype("SomeUdtType()") == "categorical"

    def test_an_empty_type_does_not_raise(self):
        assert classify_dtype("") == "categorical"


class TestProfileDataset:
    def test_it_counts_the_real_rows(self, dirty):
        assert profile_dataset(dirty).row_count == 100

    def test_it_measures_nulls_per_column(self, dirty):
        amount = _column(profile_dataset(dirty), "amount")

        assert amount.null_count == 10
        assert amount.null_rate == pytest.approx(0.10)

    def test_a_complete_column_reports_no_nulls(self, dirty):
        assert _column(profile_dataset(dirty), "category").null_count == 0

    def test_a_unique_complete_column_is_a_key_candidate(self, clean):
        assert _column(profile_dataset(clean), "id").is_key_candidate is True

    def test_a_duplicated_column_is_not_a_key_candidate(self, dirty):
        # 95 distinct ids across 100 rows.
        assert _column(profile_dataset(dirty), "order_id").is_key_candidate is False

    def test_a_column_with_nulls_is_not_a_key_candidate(self, dirty):
        # Unique-where-present is still not something to key on.
        assert _column(profile_dataset(dirty), "amount").is_key_candidate is False

    def test_numeric_columns_get_bounds(self, clean):
        value = _column(profile_dataset(clean), "value")

        assert (value.minimum, value.maximum) == (0.0, 99.0)
        assert value.mean is not None

    def test_categorical_columns_get_top_values_not_bounds(self, dirty):
        category = _column(profile_dataset(dirty), "category")

        assert category.minimum is None
        assert set(category.top_values) == {"a", "b", "c", "d"}

    def test_distinct_beyond_the_cap_reads_as_unknown_not_as_the_cap(self, clean):
        # Reporting the cap would be indistinguishable from a real count.
        profile = profile_dataset(clean, distinct_cap=10)

        assert _column(profile, "id").distinct_count is None
        assert _column(profile, "id").is_key_candidate is False

    def test_an_empty_frame_profiles_without_raising(self):
        profile = profile_dataset(pd.DataFrame({"a": pd.Series([], dtype="float64")}))

        assert profile.row_count == 0
        assert profile.gaps == []

    def test_sampling_keeps_the_row_count_exact_and_says_it_sampled(self, clean):
        profile = profile_dataset(clean, sample_rows=20)

        assert profile.row_count == 100
        assert profile.sampled is True
        assert profile.sample_rows == 20


class TestInferSpec:
    def test_the_proposed_spec_passes_on_its_own_data(self, dirty):
        # The property that makes the whole feature usable.
        assert _verdict(dirty, infer_spec(profile_dataset(dirty))) == []

    @pytest.mark.parametrize("strictness", ["strict", "balanced", "lax"])
    def test_it_passes_on_its_own_data_at_every_strictness(self, dirty, strictness):
        assert _verdict(dirty, infer_spec(profile_dataset(dirty), strictness)) == []

    def test_the_null_threshold_sits_above_what_was_observed(self, dirty):
        checks = infer_spec(profile_dataset(dirty))["checks"]

        assert checks["null_rate_amount"]["threshold"] >= 0.10

    def test_a_column_with_nulls_never_gets_a_zero_threshold(self, dirty):
        checks = infer_spec(profile_dataset(dirty), "strict")["checks"]

        assert "amount" not in checks["null_rate"]["columns"]
        assert checks["null_rate_amount"]["threshold"] > 0

    def test_complete_columns_are_grouped_at_zero(self, dirty):
        checks = infer_spec(profile_dataset(dirty))["checks"]

        assert checks["null_rate"]["threshold"] == 0.0
        assert set(checks["null_rate"]["columns"]) == {"order_id", "category"}

    def test_row_count_leaves_headroom_below_what_was_observed(self, dirty):
        # An exact count would fail on tomorrow's data, which makes the spec
        # useless rather than strict.
        assert infer_spec(profile_dataset(dirty), "strict")["checks"]["row_count"]["min"] < 100

    def test_strictness_orders_the_row_count_floor(self, dirty):
        profile = profile_dataset(dirty)
        floors = [
            infer_spec(profile, s)["checks"]["row_count"]["min"]
            for s in ("strict", "balanced", "lax")
        ]

        assert floors[0] > floors[1] > floors[2]

    def test_duplicates_is_proposed_only_where_uniqueness_was_observed(self, clean, dirty):
        assert "duplicates" in infer_spec(profile_dataset(clean))["checks"]
        assert "duplicates" not in infer_spec(profile_dataset(dirty))["checks"]

    def test_range_is_proposed_per_numeric_column_with_a_type_key(self, dirty):
        checks = infer_spec(profile_dataset(dirty))["checks"]

        assert checks["range_amount"]["type"] == "range"
        assert checks["range_amount"]["column"] == "amount"

    def test_no_range_for_a_categorical_column(self, dirty):
        assert "range_category" not in infer_spec(profile_dataset(dirty))["checks"]

    def test_lax_widens_the_range_rather_than_narrowing_it(self, dirty):
        profile = profile_dataset(dirty)
        balanced = infer_spec(profile, "balanced")["checks"]["range_amount"]
        lax = infer_spec(profile, "lax")["checks"]["range_amount"]

        assert lax["min"] <= balanced["min"]
        assert lax["max"] >= balanced["max"]

    def test_nothing_uninferable_is_invented(self, dirty):
        checks = infer_spec(profile_dataset(dirty))["checks"]
        emitted = {c.get("type", name) for name, c in checks.items()}

        assert emitted.isdisjoint(NOT_INFERABLE_CHECKS)

    def test_an_unknown_strictness_falls_back_instead_of_raising(self, dirty):
        profile = profile_dataset(dirty)

        assert infer_spec(profile, "nonsense") == infer_spec(profile, "balanced")


class TestTheSpecActuallyDiscriminates:
    """A spec that passes on everything would satisfy every test above."""

    def test_extra_nulls_are_caught(self, dirty):
        spec = infer_spec(profile_dataset(dirty))
        degraded = dirty.copy()
        degraded.loc[degraded.index[:60], "amount"] = np.nan

        assert "null_rate_amount" in _verdict(degraded, spec)

    def test_a_missing_column_is_caught(self, dirty):
        spec = infer_spec(profile_dataset(dirty))

        assert "schema" in _verdict(dirty.drop(columns=["category"]), spec)

    def test_a_collapsed_row_count_is_caught(self, dirty):
        spec = infer_spec(profile_dataset(dirty))

        assert "row_count" in _verdict(dirty.head(5), spec)

    def test_out_of_range_values_are_caught(self, dirty):
        spec = infer_spec(profile_dataset(dirty))
        degraded = dirty.copy()
        degraded.loc[degraded.index[0], "amount"] = 10_000.0

        assert "range_amount" in _verdict(degraded, spec)


class TestSpecToYaml:
    def test_it_renders_the_checks_block(self, dirty):
        profile = profile_dataset(dirty)
        rendered = spec_to_yaml(profile, infer_spec(profile))

        assert rendered.startswith("# Spec proposed by")
        assert "checks:" in rendered

    def test_it_names_what_it_could_not_infer(self, dirty):
        profile = profile_dataset(dirty)
        rendered = spec_to_yaml(profile, infer_spec(profile))

        assert "referential_integrity" in rendered

    def test_it_traces_a_threshold_back_to_the_observation(self, dirty):
        profile = profile_dataset(dirty)
        rendered = spec_to_yaml(profile, infer_spec(profile))

        assert "10/100 nulls observed" in rendered

    def test_it_declares_when_the_figures_came_from_a_sample(self, clean):
        profile = profile_dataset(clean, sample_rows=20)
        rendered = spec_to_yaml(profile, infer_spec(profile))

        assert "sampled" in rendered

    def test_the_rendered_yaml_parses_back_to_the_same_checks(self, dirty):
        import yaml

        profile = profile_dataset(dirty)
        spec = infer_spec(profile)

        assert yaml.safe_load(spec_to_yaml(profile, spec)) == spec

    def test_the_rendered_yaml_is_runnable_as_written(self, dirty):
        # The file the user gets must work without being edited first.
        import yaml

        profile = profile_dataset(dirty)
        reloaded = yaml.safe_load(spec_to_yaml(profile, infer_spec(profile)))

        assert _verdict(dirty, reloaded) == []
