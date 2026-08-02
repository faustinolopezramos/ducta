import sys
from unittest.mock import MagicMock

import pytest

from ducta.gate.exceptions import ConfigurationError, DataValidationError
from ducta.gate.validators import ConfigValidator, DataValidator


class TestConfigValidatorValidateOutputKey:
    def test_valid_three_part_key(self):
        cv = ConfigValidator()
        result = cv.validate_output_key("schema.sub_folder.table")
        assert result == {"schema": "schema", "sub_folder": "sub_folder", "table_name": "table"}

    def test_valid_with_slash(self):
        cv = ConfigValidator()
        result = cv.validate_output_key("schema/sub_folder/table")
        assert result == {"schema": "schema", "sub_folder": "sub_folder", "table_name": "table"}

    def test_valid_with_colon_prefix(self):
        cv = ConfigValidator()
        result = cv.validate_output_key("prefix:schema.sub_folder.table")
        assert result == {"schema": "schema", "sub_folder": "sub_folder", "table_name": "table"}

    def test_invalid_too_few_parts(self):
        cv = ConfigValidator()
        with pytest.raises(ConfigurationError, match="Invalid format"):
            cv.validate_output_key("schema.table")

    def test_invalid_too_many_parts(self):
        cv = ConfigValidator()
        with pytest.raises(ConfigurationError, match="Invalid format"):
            cv.validate_output_key("a.b.c.d")

    def test_empty_key_raises(self):
        cv = ConfigValidator()
        with pytest.raises(ConfigurationError, match="non-empty"):
            cv.validate_output_key("")

    def test_none_key_raises(self):
        cv = ConfigValidator()
        with pytest.raises(ConfigurationError, match="non-empty"):
            cv.validate_output_key(None)

    def test_invalid_characters(self):
        cv = ConfigValidator()
        with pytest.raises(ConfigurationError, match="Invalid characters"):
            cv.validate_output_key("schema.sub@folder.table")

    def test_empty_component_filtered_by_split(self):
        cv = ConfigValidator()
        with pytest.raises(ConfigurationError, match="Invalid format"):
            cv.validate_output_key("schema..table")

    def test_valid_names_with_hyphens(self):
        cv = ConfigValidator()
        result = cv.validate_output_key("my-schema.my_sub.table-1")
        assert result["schema"] == "my-schema"


class TestConfigValidatorValidateDateFormat:
    def test_valid_date(self):
        assert ConfigValidator.validate_date_format("2024-01-15") is True

    def test_invalid_format(self):
        assert ConfigValidator.validate_date_format("01-15-2024") is False

    def test_invalid_date(self):
        assert ConfigValidator.validate_date_format("2024-13-01") is False

    def test_empty_string(self):
        assert ConfigValidator.validate_date_format("") is False

    def test_none(self):
        assert ConfigValidator.validate_date_format(None) is False

    def test_non_string(self):
        assert ConfigValidator.validate_date_format(123) is False


class TestDataValidatorValidateDataFrame:
    def test_none_dataframe_raises(self):
        dv = DataValidator()
        with pytest.raises(DataValidationError, match="cannot be None"):
            dv.validate_dataframe(None)

    def test_valid_spark_dataframe(self):
        dv = DataValidator()
        df = MagicMock()
        df.isEmpty.return_value = False
        dv.validate_dataframe(df)

    def test_empty_spark_dataframe_raises(self):
        dv = DataValidator()
        df = MagicMock()
        df.isEmpty.return_value = True
        with pytest.raises(DataValidationError, match="DataFrame is empty"):
            dv.validate_dataframe(df)

    def test_allow_empty(self):
        dv = DataValidator()
        df = MagicMock()
        df.isEmpty.return_value = True
        dv.validate_dataframe(df, allow_empty=True)

    def test_spark_isEmpty_raises_during_check(self):
        # Regression: a genuine Spark failure (lost executor, bad query, ...)
        # while checking isEmpty() used to be swallowed and fall through as
        # if the DataFrame had been validated — we genuinely don't know
        # whether it's empty, which is not the same as "it's not empty".
        dv = DataValidator()
        df = MagicMock()
        df.isEmpty.side_effect = RuntimeError("no spark context")
        with pytest.raises(DataValidationError, match="Could not determine if DataFrame is empty"):
            dv.validate_dataframe(df)

    def test_dataframe_without_isEmpty(self):
        dv = DataValidator()
        df = object()
        dv.validate_dataframe(df)


class TestDataValidatorValidateColumnsExist:
    def test_columns_exist(self):
        dv = DataValidator()
        df = MagicMock()
        df.columns = ["a", "b", "c"]
        dv.validate_columns_exist(df, ["a", "b"])

    def test_columns_missing(self):
        dv = DataValidator()
        df = MagicMock()
        df.columns = ["a", "b"]
        with pytest.raises(DataValidationError, match="Columns not found"):
            dv.validate_columns_exist(df, ["a", "x"])

    def test_no_columns_attr(self):
        dv = DataValidator()
        df = object()
        with pytest.raises(DataValidationError, match="does not have columns"):
            dv.validate_columns_exist(df, ["a"])

    def test_get_columns_from_schema(self):
        dv = DataValidator()
        df = MagicMock()
        df.columns = None
        df.schema.names = ["x", "y"]
        result = dv._get_columns(df)
        assert result == ["x", "y"]
