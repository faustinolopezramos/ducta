"""Gate behaviour against real Spark DataFrames.

The mocked equivalents of these assertions live in tests/gate/output/. They pass
whether or not ``pyspark.sql.DataFrame`` actually resolves to the real class,
because the mock *is* the stand-in. These do not.
"""

from __future__ import annotations

import pandas as pd
import pytest

from ducta.gate.exceptions import ConfigurationError
from ducta.gate.output import _DataFrameManager

pytestmark = pytest.mark.spark


def _manager(spark):
    return _DataFrameManager({"spark": spark})


class TestSparkDataFrameDetection:
    def test_imported_spark_dataframe_is_the_real_class(self):
        """The names the gate does isinstance() against must be pyspark's own.

        Regression guard: ``SparkDataFrame`` and ``ConnectDataFrame`` were imported
        in one try/except, so the ImportError raised by ``pyspark.sql.connect`` on
        Python 3.12+ (it imports the removed ``distutils``) replaced *both* with
        dummy classes and killed the isinstance path entirely.
        """
        from pyspark.sql import DataFrame as RealSparkDataFrame

        from ducta.gate.output import dataframes

        assert dataframes.SparkDataFrame is RealSparkDataFrame

    def test_detects_real_dataframe(self, spark, people_df):
        assert _manager(spark).is_spark_dataframe(people_df) is True

    def test_rejects_pandas_dataframe(self, spark):
        assert _manager(spark).is_spark_dataframe(pd.DataFrame({"a": [1]})) is False

    @pytest.mark.parametrize("value", [None, 42, "SELECT 1", [1, 2, 3], {"a": 1}])
    def test_rejects_non_dataframes(self, spark, value):
        assert _manager(spark).is_spark_dataframe(value) is False


class TestConvertToSpark:
    def test_spark_dataframe_passes_through_unchanged(self, spark, people_df):
        assert _manager(spark).convert_to_spark(people_df) is people_df

    def test_converts_pandas(self, spark):
        pdf = pd.DataFrame({"id": [1, 2], "name": ["ana", "bo"]})
        result = _manager(spark).convert_to_spark(pdf)

        assert _manager(spark).is_spark_dataframe(result) is True
        assert result.count() == 2
        assert sorted(result.columns) == ["id", "name"]

    def test_rejects_unsupported_type(self, spark):
        with pytest.raises(ConfigurationError, match="Unsupported"):
            _manager(spark).convert_to_spark(42)
