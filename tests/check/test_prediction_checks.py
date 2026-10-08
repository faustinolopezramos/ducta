"""Checks on what a model produced: prediction_rate, prediction_contract, prediction_drift."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ducta.check.core import QUALITY_CHECKS_REGISTRY, DFAdapter
from ducta.check.params import CHECK_PARAMS


def _run(name, df, context=None, **params):
    check = QUALITY_CHECKS_REGISTRY[name]()
    config = type("CheckConfig", (), params)()
    return check.run(df, config, DFAdapter(df), context)


def _scores(n=1000, seed=0, loc=0.3):
    rng = np.random.default_rng(seed)
    return pd.DataFrame({"score": np.clip(rng.normal(loc, 0.1, n), 0, 1)})


class TestPredictionRate:
    def test_a_rate_inside_the_bounds_passes(self):
        df = pd.DataFrame({"score": [0.1, 0.2, 0.9, 0.95]})
        result = _run("prediction_rate", df, column="score", threshold=0.5, min=0.1, max=0.6)
        assert result.passed and result.details["rate"] == 0.5

    def test_a_model_that_flags_everything_fails(self):
        df = pd.DataFrame({"score": [0.9] * 10})
        result = _run("prediction_rate", df, column="score", threshold=0.5, max=0.2)
        assert not result.passed
        assert "flags 100.00% of rows, above the maximum 20.00%" in result.message

    def test_a_model_that_flags_nothing_fails(self):
        df = pd.DataFrame({"label": [0] * 10})
        result = _run("prediction_rate", df, column="label", min=0.01)
        assert not result.passed and "below the minimum" in result.message

    def test_labels_and_nulls(self):
        df = pd.DataFrame({"label": [1, 0, 0, None]})
        result = _run("prediction_rate", df, column="label", max=0.5)
        assert result.passed
        assert (result.details["flagged"], result.details["scored_rows"]) == (1, 3)

    def test_no_bounds_checks_nothing_and_says_so(self):
        result = _run("prediction_rate", pd.DataFrame({"s": [1]}), column="s")
        assert not result.passed and "needs min and/or max" in result.message


class TestPredictionContract:
    def test_scores_in_range_pass(self):
        assert _run("prediction_contract", _scores(), column="score", min=0, max=1).passed

    def test_out_of_range_and_missing_predictions_are_named(self):
        df = pd.DataFrame({"score": [0.5, 1.4, None]})
        result = _run("prediction_contract", df, column="score", min=0, max=1)
        assert not result.passed
        assert "1 row(s) without a prediction" in result.message
        assert "maximum 1.4 is above 1" in result.message

    def test_nulls_can_be_allowed(self):
        df = pd.DataFrame({"score": [0.5, None]})
        assert _run("prediction_contract", df, column="score", allow_null=True).passed


class TestPredictionDrift:
    @pytest.mark.parametrize("method", ["psi", "ks"])
    def test_the_same_distribution_does_not_drift(self, method):
        context = {"val_scores": _scores(seed=1)}
        result = _run(
            "prediction_drift",
            _scores(seed=2),
            context,
            column="score",
            reference="val_scores",
            method=method,
        )
        assert result.passed, result.message

    @pytest.mark.parametrize("method", ["psi", "ks"])
    def test_a_shifted_distribution_drifts(self, method):
        context = {"val_scores": _scores(seed=1)}
        result = _run(
            "prediction_drift",
            _scores(seed=2, loc=0.6),
            context,
            column="score",
            reference="val_scores",
            method=method,
        )
        assert not result.passed
        assert f"drifted from 'val_scores': {method}" in result.message

    def test_a_reference_column_with_another_name(self):
        context = {"val": _scores(seed=1).rename(columns={"score": "p"})}
        result = _run(
            "prediction_drift",
            _scores(seed=2),
            context,
            column="score",
            reference="val",
            reference_column="p",
        )
        assert result.passed

    def test_a_missing_reference_is_not_a_pass(self):
        result = _run("prediction_drift", _scores(), {}, column="score", reference="val")
        assert not result.passed and "'val' not available" in result.message


def test_every_parameter_is_described():
    for name in ("prediction_rate", "prediction_contract", "prediction_drift"):
        declared = QUALITY_CHECKS_REGISTRY[name].CONFIG_PARAMS
        assert set(CHECK_PARAMS[name]) == set(declared)
