from datetime import datetime

import pytest

from ducta.gate.exceptions import ConfigurationError
from ducta.gate.output import DataOutputManager, parse_iso_datetime, validate_date_range


class TestParseISODatetime:
    def test_valid(self):
        result = parse_iso_datetime("2024-01-15T10:30:00")
        assert isinstance(result, datetime)

    def test_invalid(self):
        with pytest.raises(ConfigurationError, match="Invalid ISO-8601"):
            parse_iso_datetime("not-a-date")


class TestValidateDateRange:
    def test_valid_range(self):
        start, end = validate_date_range("2024-01-01", "2024-01-31")
        assert start < end

    def test_invalid_range(self):
        with pytest.raises(ConfigurationError, match="start_date"):
            validate_date_range("2024-01-31", "2024-01-01")


class TestDataOutputManager:
    def test_init(self, dict_context):
        dom = DataOutputManager(dict_context)
        assert dom.df_manager is not None
        assert dom.path_manager is not None
        assert dom.uc_manager is not None
        assert dom.writer_factory is not None

    def test_is_output_materialized_no_config(self, dict_context):
        dom = DataOutputManager(dict_context)
        assert dom.is_output_materialized("nonexistent") is False

    def test_is_output_materialized_cloud_path(self, dict_context):
        dict_context["output_config"] = {"sch.sub.tbl": {"format": "parquet"}}
        dict_context["output_path"] = "s3://bucket"
        dom = DataOutputManager(dict_context)
        assert dom.is_output_materialized("sch.sub.tbl") is False

    def test_is_output_materialized_local_no_data(self, dict_context):
        dict_context["output_config"] = {
            "sch.sub.tbl": {"format": "parquet", "table_name": "tbl", "schema": "sch"},
        }
        dict_context["output_path"] = "/nonexistent"
        dom = DataOutputManager(dict_context)
        assert dom.is_output_materialized("sch.sub.tbl") is False

    def test_path_has_data_file(self, temp_dir):
        p = temp_dir / "test.txt"
        p.write_text("data")
        assert DataOutputManager._path_has_data(str(p)) is True

    def test_path_has_data_empty_file(self, temp_dir):
        p = temp_dir / "empty.txt"
        p.touch()
        assert DataOutputManager._path_has_data(str(p)) is False

    def test_path_has_data_missing(self, temp_dir):
        assert DataOutputManager._path_has_data(str(temp_dir / "missing")) is False

    def test_path_has_data_dir_with_success(self, temp_dir):
        d = temp_dir / "out.parquet"
        d.mkdir()
        (d / "part-00000.parquet").write_text("data")
        (d / "_SUCCESS").write_text("")
        assert DataOutputManager._path_has_data(str(d)) is True

    def test_path_has_data_empty_dir(self, temp_dir):
        d = temp_dir / "empty"
        d.mkdir()
        assert DataOutputManager._path_has_data(str(d)) is False

    def test_path_has_data_dir_with_delta_log(self, temp_dir):
        d = temp_dir / "delta"
        d.mkdir()
        (d / "part-00000.parquet").write_text("data")
        dl = d / "_delta_log"
        dl.mkdir()
        (dl / "000000.json").write_text("{}")
        assert DataOutputManager._path_has_data(str(d)) is True

    def test_save_output_empty_df(self, dict_context_with_spark, spark_dataframe_spec):
        spark_dataframe_spec.isEmpty.return_value = True
        dom = DataOutputManager(dict_context_with_spark)
        dom.save_output("dev", {"output": ["sch.sub.tbl"], "name": "test"}, spark_dataframe_spec)

    def test_get_output_keys(self, dict_context):
        dom = DataOutputManager(dict_context)
        result = dom._get_output_keys({"output": ["a", "b"]})
        assert result == ["a", "b"]

    def test_get_output_keys_single_string(self, dict_context):
        dom = DataOutputManager(dict_context)
        result = dom._get_output_keys({"output": "single"})
        assert result == ["single"]

    def test_get_output_keys_invalid_type(self, dict_context):
        dom = DataOutputManager(dict_context)
        with pytest.raises(ConfigurationError):
            dom._get_output_keys({"output": 42})

    def test_get_output_keys_deduplicates(self, dict_context):
        dom = DataOutputManager(dict_context)
        result = dom._get_output_keys({"output": ["a", "b", "a"]})
        assert result == ["a", "b"]

    def test_get_output_keys_empty_string(self, dict_context):
        dom = DataOutputManager(dict_context)
        with pytest.raises(ConfigurationError):
            dom._get_output_keys({"output": [""]})

    def test_output_mtime_no_config(self, dict_context):
        dom = DataOutputManager(dict_context)
        assert dom.output_mtime("nonexistent") is None

    def test_output_mtime_cloud_path(self, dict_context):
        dict_context["output_config"] = {"sch.tbl": {"format": "parquet"}}
        dict_context["output_path"] = "s3://bucket"
        dom = DataOutputManager(dict_context)
        assert dom.output_mtime("sch.tbl") is None

    def test_output_mtime_local(self, dict_context, temp_dir):
        dict_context["output_config"] = {
            "sch.sub.tbl": {"format": "parquet", "table_name": "tbl", "schema": "sch"},
        }
        dict_context["output_path"] = str(temp_dir)
        (temp_dir / "sch").mkdir()
        (temp_dir / "sch" / "sub").mkdir()
        (temp_dir / "sch" / "sub" / "tbl").mkdir()
        dom = DataOutputManager(dict_context)
        result = dom.output_mtime("sch.sub.tbl")
        assert result is not None
