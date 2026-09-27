"""A column the user names explicitly must exist and be evaluated, or the check fails.

Before this, a misspelled column in `null_rate` raised inside the per-column
loop, was logged, and the check reported "all columns within threshold" having
checked nothing. Drift/anomaly/statistical had the same shape: they only failed
when *zero* columns were evaluated, so one good column hid a typo in another.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pytest

from ducta.check import QUALITY_CHECKS_REGISTRY, DFAdapter


def run_check(name: str, df: pd.DataFrame, **config):
    check = QUALITY_CHECKS_REGISTRY[name]()
    return check.run(df, SimpleNamespace(**config), DFAdapter(df))


DF = pd.DataFrame({"id": [1, None, 3], "amount": [10.0, 11.0, 12.0]})


@pytest.mark.parametrize(
    "name, config",
    [
        ("null_rate", {"columns": ["idd"], "threshold": 0.0}),
        ("null_rate", {"columns": ["amount", "idd"], "threshold": 0.5}),
        ("drift_detection", {"columns": ["amount", "idd"], "use_scipy": False}),
        ("anomaly_detection", {"columns": ["amount", "idd"]}),
        ("statistical", {"columns": ["amount", "idd"]}),
    ],
)
def test_misspelled_column_fails_and_names_it(name, config):
    result = run_check(name, DF, **config)

    assert result.passed is False
    assert result.details["missing_columns"] == ["idd"]
    assert "idd" in result.message


def test_null_rate_on_real_columns_is_unchanged():
    assert not run_check("null_rate", DF, columns=["id"], threshold=0.0).passed
    assert run_check("null_rate", DF, columns=["amount"], threshold=0.0).passed


def test_null_rate_without_columns_still_checks_every_column():
    result = run_check("null_rate", DF, threshold=0.0)

    assert result.passed is False
    assert "id" in result.details


def test_null_rate_column_that_errors_is_inconclusive_not_a_pass():
    adapter = MagicMock()
    adapter.get_columns.return_value = ["id"]
    adapter.count.return_value = 3
    adapter.null_count.side_effect = RuntimeError("boom")
    check = QUALITY_CHECKS_REGISTRY["null_rate"]()

    result = check.run(None, SimpleNamespace(columns=["id"], threshold=0.0), adapter)

    assert result.passed is False
    assert result.details["_column_errors"] == {"id": "boom"}


def test_anomaly_one_good_column_does_not_hide_one_that_errors():
    adapter = MagicMock()
    adapter.get_columns.return_value = ["a", "b"]
    adapter.mean_std.side_effect = lambda col: (
        (10.0, 1.0) if col == "a" else (_ for _ in ()).throw(RuntimeError("bad type"))
    )
    config = SimpleNamespace(
        columns=["a", "b"],
        _baseline={"a": {"mean": 10.0, "std": 1.0}, "b": {"mean": 1.0, "std": 1.0}},
    )
    check = QUALITY_CHECKS_REGISTRY["anomaly_detection"]()

    result = check.run(None, config, adapter)

    assert result.passed is False
    assert result.details["_columns_evaluated"] == 1
    assert "b" in result.details["_column_errors"]
