from unittest.mock import MagicMock

import pytest

from ducta.gate.exceptions import ConfigurationError, WriteOperationError
from ducta.gate.output import _DataFrameManager


class TestDataFrameManager:
    def _make_dfm(self, spark=None):
        return _DataFrameManager({"spark": spark})

    def test_is_spark_dataframe(self, spark_dataframe_spec):
        dfm = self._make_dfm(spark=MagicMock())
        assert dfm.is_spark_dataframe(spark_dataframe_spec) is True

    def test_is_spark_dataframe_non_spark(self):
        dfm = self._make_dfm(spark=MagicMock())
        assert dfm.is_spark_dataframe("not_a_df") is False

    def test_is_spark_dataframe_none(self):
        dfm = self._make_dfm(spark=MagicMock())
        assert dfm.is_spark_dataframe(None) is False

    def test_convert_to_spark_no_spark(self, spark_dataframe):
        dfm = self._make_dfm(spark=None)
        with pytest.raises(WriteOperationError, match="Spark session unavailable"):
            dfm.convert_to_spark(spark_dataframe)

    def test_convert_to_spark_already_spark(self, spark_session, spark_dataframe_spec):
        dfm = self._make_dfm(spark=spark_session)
        result = dfm.convert_to_spark(spark_dataframe_spec)
        assert result is spark_dataframe_spec

    def test_convert_to_spark_unsupported_type(self, spark_session):
        dfm = self._make_dfm(spark=spark_session)
        with pytest.raises(ConfigurationError, match="Unsupported"):
            dfm.convert_to_spark(42)
