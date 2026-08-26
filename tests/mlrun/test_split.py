"""Unit tests for ducta.mlrun.split.split_dataframe (reproducible ML splits)."""

from __future__ import annotations

import pandas as pd
import pytest

from ducta.mlrun.split import SplitError, cross_validate, kfold_splits, split_dataframe


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

    def test_result_identical_to_row_wise_hash(self):
        # Regression test for the unique()-first vectorization of
        # _stable_fraction: build a reference split via the original per-row
        # hash and confirm the vectorized path produces the identical
        # train/test assignment on a dataset with heavy group repetition.
        from ducta.mlrun.split import _stable_fraction

        d = pd.DataFrame({"x": range(1000), "grp": [f"g{i % 20}" for i in range(1000)]})
        seed = 3
        reference_fractions = d["grp"].map(lambda v: _stable_fraction(v, seed))
        reference_test_mask = reference_fractions > (1 - 0.3)

        train, test = split_dataframe(
            d, {"method": "group", "group_col": "grp", "test_size": 0.3}, default_seed=seed
        )

        assert set(test.index) == set(d.index[reference_test_mask])
        assert set(train.index) == set(d.index[~reference_test_mask])

    def test_kfold_result_identical_to_row_wise_hash(self):
        from ducta.mlrun.split import _stable_fraction

        d = pd.DataFrame({"x": range(500), "grp": [f"g{i % 15}" for i in range(500)]})
        seed = 5
        reference_fractions = d["grp"].map(lambda v: _stable_fraction(v, seed))
        reference_fold_ids = (reference_fractions * 4).astype(int).clip(upper=3)

        folds = kfold_splits(d, {"method": "group", "group_col": "grp"}, n_splits=4, default_seed=seed)

        for fold_index, (train_part, val_part) in enumerate(folds):
            expected_val_mask = reference_fold_ids == fold_index
            assert set(val_part.index) == set(d.index[expected_val_mask])
            assert set(train_part.index) == set(d.index[~expected_val_mask])


class TestSplitApplied:
    def test_split_dataframe_marks_flag_on_dict_context(self, df):
        ctx = {}
        split_dataframe(df, {"method": "random", "test_size": 0.2}, default_seed=1, ml_context=ctx)
        assert ctx["split_applied"] is True

    def test_split_dataframe_without_ml_context_does_not_raise(self, df):
        train, test = split_dataframe(df, {"method": "random", "test_size": 0.2}, default_seed=1)
        assert len(train) + len(test) == 100

    def test_split_dataframe_marks_flag_on_mlnodecontext(self, df):
        from ducta.core.ml_context import MLNodeContext

        ctx = MLNodeContext()
        assert ctx.split_applied is False
        split_dataframe(df, {"method": "random", "test_size": 0.2}, default_seed=1, ml_context=ctx)
        assert ctx.split_applied is True

    def test_kfold_splits_marks_flag(self, df):
        ctx = {}
        kfold_splits(df, {"method": "random"}, n_splits=4, default_seed=1, ml_context=ctx)
        assert ctx["split_applied"] is True

    def test_kfold_splits_without_ml_context_does_not_raise(self, df):
        folds = kfold_splits(df, {"method": "random"}, n_splits=4, default_seed=1)
        assert len(folds) == 4


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


class TestCrossValidate:
    """cv_folds was accepted by HyperparamConfig and resolved onto
    ml_context.cv_folds, and kfold_splits could already build folds — but
    nothing in the engine ever tied them together, so model selection always
    rested on a single hold-out."""

    @staticmethod
    def _fit(train_df, val_df):
        # A deterministic "model": the mean of x on the training fold.
        return train_df["x"].mean()

    @staticmethod
    def _score(model, val_df, _val_df_again):
        # Score = negative mean absolute deviation from the "model" (higher
        # is better), so folds naturally produce varying scores.
        return -((val_df["x"] - model).abs().mean())

    def test_returns_mean_std_across_folds(self, df):
        result = cross_validate(
            self._fit,
            self._score,
            ml_context={"split": {"method": "random"}, "cv_folds": 4, "node_seed": 1},
            df=df,
        )
        assert set(result.keys()) == {"score_mean", "score_std", "score_folds"}
        assert len(result["score_folds"]) == 4
        assert result["score_mean"] == pytest.approx(
            sum(result["score_folds"]) / len(result["score_folds"])
        )
        assert result["score_std"] >= 0

    def test_uses_ml_context_split_and_cv_folds(self, df, monkeypatch):
        calls = {}

        def fake_kfold_splits(df_arg, split_config, n_splits, default_seed):
            calls["split_config"] = split_config
            calls["n_splits"] = n_splits
            calls["default_seed"] = default_seed
            return [(df_arg.iloc[:5], df_arg.iloc[5:10])]

        monkeypatch.setattr("ducta.mlrun.split.kfold_splits", fake_kfold_splits)

        cross_validate(
            self._fit,
            self._score,
            ml_context={"split": {"method": "temporal", "time_col": "ts"}, "cv_folds": 7, "node_seed": 99},
            df=df,
        )

        assert calls["split_config"] == {"method": "temporal", "time_col": "ts"}
        assert calls["n_splits"] == 7
        assert calls["default_seed"] == 99

    def test_works_with_mlnodecontext_object(self, df):
        from ducta.core.ml_context import MLNodeContext

        ctx = MLNodeContext(split={"method": "random"}, cv_folds=3, node_seed=1)
        result = cross_validate(self._fit, self._score, ml_context=ctx, df=df)
        assert len(result["score_folds"]) == 3

    def test_logs_metrics_when_mlops_context_present(self, df):
        from unittest.mock import MagicMock

        tracker = MagicMock()
        mlops_context = MagicMock(experiment_tracker=tracker)
        ctx = {
            "split": {"method": "random"},
            "cv_folds": 3,
            "node_seed": 1,
            "mlops_context": mlops_context,
            "mlops_run_id": "run-1",
        }

        result = cross_validate(self._fit, self._score, ml_context=ctx, df=df, metric_name="f1")

        tracker.log_metric.assert_any_call("run-1", "f1_mean", result["f1_mean"])
        tracker.log_metric.assert_any_call("run-1", "f1_std", result["f1_std"])

    def test_no_mlops_context_does_not_raise(self, df):
        result = cross_validate(
            self._fit, self._score, ml_context={"split": {"method": "random"}, "cv_folds": 3}, df=df
        )
        assert "score_mean" in result

    def test_missing_df_raises_split_error(self):
        with pytest.raises(SplitError, match="requires df"):
            cross_validate(self._fit, self._score, ml_context={}, df=None)

    def test_default_cv_folds_is_five_when_unset(self, df):
        result = cross_validate(self._fit, self._score, ml_context={}, df=df)
        assert len(result["score_folds"]) == 5
