"""Unit tests for ducta.mlrun.split.split_dataframe (reproducible ML splits)."""

from __future__ import annotations

import pandas as pd
import pytest

from ducta.mlrun.split import SplitError, split_dataframe


@pytest.fixture
def df():
    return pd.DataFrame(
        {
            "x": range(100),
            "ts": pd.date_range("2026-01-01", periods=100, freq="D"),
            "grp": [f"g{i % 10}" for i in range(100)],
            "label": [i % 2 for i in range(100)],
        }
    )


class TestRandom:
    def test_two_way_split_no_overlap(self, df):
        train, test = split_dataframe(df, {"method": "random", "test_size": 0.2}, default_seed=1)
        assert len(train) + len(test) == 100
        assert set(train.index).isdisjoint(test.index)

    def test_deterministic_with_seed(self, df):
        a = split_dataframe(df, {"method": "random", "test_size": 0.2}, default_seed=7)
        b = split_dataframe(df, {"method": "random", "test_size": 0.2}, default_seed=7)
        assert list(a[1].index) == list(b[1].index)

    def test_three_way_split(self, df):
        train, val, test = split_dataframe(
            df, {"method": "random", "test_size": 0.2, "val_size": 0.2}, default_seed=1
        )
        assert len(train) + len(val) + len(test) == 100
        idx = set(train.index) | set(val.index) | set(test.index)
        assert len(idx) == 100  # all disjoint


class TestTemporal:
    def test_train_precedes_test(self, df):
        train, test = split_dataframe(
            df, {"method": "temporal", "time_col": "ts", "test_size": 0.2}
        )
        assert train["ts"].max() <= test["ts"].min()
        assert len(test) == 20


class TestGroup:
    def test_no_group_on_both_sides(self, df):
        train, test = split_dataframe(df, {"method": "group", "group_col": "grp", "test_size": 0.3})
        assert set(train["grp"]).isdisjoint(set(test["grp"]))

    def test_too_few_groups_raises_instead_of_empty_split(self):
        # Only 2 distinct groups: an 80/20 test_size can degenerate to a 0-row
        # test set depending on which group each hash lands in.
        d = pd.DataFrame({"x": range(10), "grp": ["a"] * 8 + ["b"] * 2})
        with pytest.raises(SplitError, match="empty partition"):
            split_dataframe(
                d, {"method": "group", "group_col": "grp", "test_size": 0.05}, default_seed=1
            )


class TestStratified:
    def test_singleton_class_raises(self):
        d = pd.DataFrame({"x": [1, 2, 3], "label": ["a", "a", "solo"]})
        with pytest.raises(SplitError, match="at least 2 rows per class"):
            split_dataframe(d, {"method": "stratified", "stratify_col": "label", "test_size": 0.2})


class TestErrors:
    def test_unknown_method(self, df):
        with pytest.raises(SplitError, match="Unknown split method"):
            split_dataframe(df, {"method": "nope"})

    def test_bad_test_size(self, df):
        with pytest.raises(SplitError, match="test_size"):
            split_dataframe(df, {"method": "random", "test_size": 1.5})

    def test_val_plus_test_too_large(self, df):
        with pytest.raises(SplitError, match="val_size \\+ test_size"):
            split_dataframe(df, {"method": "random", "test_size": 0.6, "val_size": 0.5})

    def test_negative_val_size_raises(self, df):
        with pytest.raises(SplitError, match="val_size must be >= 0"):
            split_dataframe(df, {"method": "random", "test_size": 0.5, "val_size": -0.2})

    def test_negative_val_size_would_otherwise_leak_rows_in_temporal(self, df):
        # Regression guard for the specific leak this validation closes: before
        # the fix, test_size=0.5 + val_size=-0.2 made cut_train > cut_val in the
        # temporal branch, duplicating rows across train and test.
        with pytest.raises(SplitError):
            split_dataframe(
                df, {"method": "temporal", "time_col": "ts", "test_size": 0.5, "val_size": -0.2}
            )
