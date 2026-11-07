"""What a value means must survive the pandas <-> Spark crossing.

A dependency upgrade can keep every other test green and still change data: with
pandas 3, a ``None`` in a text column reaches Spark as the string ``'NaN'`` (Spark
3.5) or ``'nan'`` (Spark 4.2), no error raised. Ducta crosses here when a Python
node returns a pandas DataFrame (``gate/output/dataframes.py``) and when quality
checks read a Spark DataFrame with ``toPandas()`` (``check/core.py``).

Only what holds on every supported stack, with and without Arrow, is asserted.
Arrow itself changes some results (a float NaN becomes null, a naive timestamp
is read in the driver's time zone), so those are left out on purpose.
"""

from __future__ import annotations

import datetime as dt
import decimal

import pandas as pd
import pytest

from ducta.gate.output import _DataFrameManager

pytestmark = pytest.mark.spark

ARROW = "spark.sql.execution.arrow.pyspark.enabled"


@pytest.fixture(params=["false", "true"], ids=["rows", "arrow"])
def arrow(request, spark):
    """Both conversion paths Ducta's sessions can take (Ducta enables Arrow with fallback)."""
    before = spark.conf.get(ARROW, "false")
    spark.conf.set(ARROW, request.param)
    yield request.param
    spark.conf.set(ARROW, before)


def _to_spark(spark, pdf):
    return _DataFrameManager({"spark": spark}).convert_to_spark(pdf)


class TestPandasToSpark:
    def test_a_missing_text_value_stays_null(self, spark, arrow):
        result = _to_spark(spark, pd.DataFrame({"s": ["x", None]}))

        assert [row.s for row in result.collect()] == ["x", None]

    def test_missing_values_of_every_kind_are_null(self, spark, arrow):
        pdf = pd.DataFrame(
            {
                "s": ["x", None],
                "t": pd.to_datetime(["2026-01-01 10:00", None]),
                "d": [dt.date(2026, 1, 1), None],
                "b": [True, None],
                "m": [decimal.Decimal("1.10"), None],
            }
        )
        result = _to_spark(spark, pdf)

        nulls = {c: result.filter(result[c].isNull()).count() for c in result.columns}
        assert nulls == {"s": 1, "t": 1, "d": 1, "b": 1, "m": 1}

    def test_column_types_are_kept(self, spark, arrow):
        pdf = pd.DataFrame(
            {
                "s": ["x"],
                "t": pd.to_datetime(["2026-01-01 10:00"]),
                "d": [dt.date(2026, 1, 1)],
                "b": [True],
                "m": [decimal.Decimal("1.10")],
            }
        )
        types = dict(_to_spark(spark, pdf).dtypes)

        assert {c: types[c] for c in "stdb"} == {
            "s": "string",
            "t": "timestamp",
            "d": "date",
            "b": "boolean",
        }
        assert types["m"].startswith("decimal(")


class TestSparkToPandas:
    """Arrow off only: Spark 3.5 cannot run Arrow on Java 21, and toPandas does not fall back."""

    QUERY = (
        "select * from values "
        "('x', 1, timestamp'2026-01-01 10:00:00', date'2026-01-01', cast(1.10 as decimal(10,2))), "
        "(null, null, null, null, null) as t(s, i, t, d, m)"
    )

    def test_nulls_are_still_missing_in_pandas(self, spark):
        pdf = spark.sql(self.QUERY).toPandas()

        assert pdf.isna().sum().to_dict() == {"s": 1, "i": 1, "t": 1, "d": 1, "m": 1}

    def test_values_are_unchanged(self, spark):
        row = spark.sql(self.QUERY).toPandas().iloc[0]

        assert row["s"] == "x"
        assert row["i"] == 1
        assert row["t"] == pd.Timestamp("2026-01-01 10:00:00")
        assert row["d"] == dt.date(2026, 1, 1)
        assert row["m"] == decimal.Decimal("1.10")
