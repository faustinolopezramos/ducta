"""Python business rules collect the data once, and only when the driver can hold it.

A Spark frame was collected whole with ``toPandas()`` for every rule, with no row
guard (review 2026-11-11): a large table took the driver down instead of failing
the check.
"""

from __future__ import annotations

from types import SimpleNamespace as NS

import pandas as pd

from ducta.check.checks.business import BusinessRulesCheck

RULES = ["lambda row: row['amount'] > 0", "lambda row: row['qty'] >= 1"]


class _SparkishAdapter:
    """What the check reads of a Spark adapter: its engine, ``limit().count()``,
    ``to_pandas()`` — counting how often the data was collected."""

    engine = "spark"

    def __init__(self, pdf: pd.DataFrame) -> None:
        self.pdf = pdf
        self.collected = 0
        rows = len(pdf)
        self.df = NS(limit=lambda n: NS(count=lambda: min(n, rows)))

    def to_pandas(self) -> pd.DataFrame:
        self.collected += 1
        return self.pdf


def _run(adapter, **params):
    cfg = NS(enabled=True, rules=RULES, rule_type="python", **params)
    return BusinessRulesCheck()._run_impl(None, cfg, adapter)


def test_over_max_rows_fails_without_collecting():
    adapter = _SparkishAdapter(pd.DataFrame({"amount": [1, 2, 3, 4], "qty": [1, 1, 1, 1]}))
    result = _run(adapter, max_rows=3)
    assert not result.passed
    assert "more than 3 rows" in result.message
    assert "rule_type: sql" in result.message
    assert adapter.collected == 0


def test_within_max_rows_collects_once_for_every_rule():
    adapter = _SparkishAdapter(pd.DataFrame({"amount": [1, -2, 3], "qty": [1, 1, 0]}))
    result = _run(adapter, max_rows=10)
    assert adapter.collected == 1
    assert result.details["violations_by_rule"] == {RULES[0]: 1, RULES[1]: 1}


def test_default_limit_applies_when_max_rows_is_not_set():
    adapter = _SparkishAdapter(pd.DataFrame({"amount": [1], "qty": [1]}))
    assert _run(adapter).passed
