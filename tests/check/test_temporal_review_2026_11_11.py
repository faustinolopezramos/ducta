"""anomaly_detection and freshness gaps found in the 2026-11-11 review."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace as NS

import pandas as pd
import pytest

from ducta.check.checks.temporal import AnomalyDetectionCheck, FreshnessCheck
from ducta.check.core import DFAdapter

BASELINE = {"amount": {"mean": 100.0, "std": 10.0}}


def _anomaly(values):
    df = pd.DataFrame({"amount": values})
    cfg = NS(enabled=True, columns=["amount"], z_score_threshold=3.0, _baseline=BASELINE)
    return AnomalyDetectionCheck()._run_impl(df, cfg, DFAdapter(df))


@pytest.mark.parametrize("constant", [0.0, 1e6])
def test_column_collapsed_to_a_constant_is_an_anomaly(constant):
    # Its std is 0: the column used to be skipped and the check passed.
    result = _anomaly([constant] * 5)
    assert not result.passed
    assert "z-score" in result.message


def test_constant_at_the_baseline_mean_is_not_an_anomaly():
    assert _anomaly([100.0] * 5).passed


def test_normal_values_pass():
    assert _anomaly([95.0, 100.0, 105.0]).passed


def _freshness(latest, **params):
    df = pd.DataFrame({"ts": [latest]})
    cfg = NS(enabled=True, column="ts", **params)
    return FreshnessCheck()._run_impl(df, cfg, DFAdapter(df))


@pytest.mark.parametrize(
    "params", [{"max_age_hours": 24}, {"max_age_business_days": 2, "weekends_included": True}]
)
def test_future_timestamp_fails(params):
    result = _freshness(datetime.now(timezone.utc) + timedelta(days=400), **params)
    assert not result.passed
    assert "in the future" in result.message


def test_slight_clock_skew_is_tolerated():
    result = _freshness(datetime.now(timezone.utc) + timedelta(minutes=20), max_age_hours=24)
    assert result.passed


def test_recent_timestamp_passes():
    result = _freshness(datetime.now(timezone.utc) - timedelta(hours=2), max_age_hours=24)
    assert result.passed


def test_today_as_a_date_is_fresh():
    assert _freshness(date.today(), max_age_hours=48).passed
