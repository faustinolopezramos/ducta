from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ducta.gate.exceptions import ConfigurationError
from ducta.gate.output import _newest_mtime, _PathComponents, _PathManager, join_cloud_path


class TestPathComponents:
    def test_valid(self):
        pc = _PathComponents(table_name="tbl", schema="sch", sub_folder="sub")
        assert pc.table_name == "tbl"
        assert pc.schema == "sch"
        assert pc.sub_folder == "sub"

    def test_empty_table_name_raises(self):
        with pytest.raises(ConfigurationError, match="table_name"):
            _PathComponents(table_name="", schema="sch")

    def test_empty_schema_raises(self):
        with pytest.raises(ConfigurationError, match="schema"):
            _PathComponents(table_name="tbl", schema="")

    def test_path_traversal_in_table_name_rejected(self):
        """Regression: an explicit `dataset_config` override used to bypass
        VALID_NAME_PATTERN entirely (only values parsed from a declarative
        `out_key` were validated), so `table_name: "../../etc"` escaped
        `output_path` via `Path.joinpath`."""
        with pytest.raises(ConfigurationError, match="Invalid characters"):
            _PathComponents(table_name="../../etc", schema="sch")

    def test_path_traversal_in_schema_rejected(self):
        with pytest.raises(ConfigurationError, match="Invalid characters"):
            _PathComponents(table_name="tbl", schema="../../etc")

    def test_path_traversal_in_sub_folder_rejected(self):
        with pytest.raises(ConfigurationError, match="Invalid characters"):
            _PathComponents(table_name="tbl", schema="sch", sub_folder="../../etc")

    def test_absolute_path_in_table_name_rejected(self):
        with pytest.raises(ConfigurationError, match="Invalid characters"):
            _PathComponents(table_name="/etc/passwd", schema="sch")

    def test_empty_sub_folder_is_still_allowed(self):
        # sub_folder is optional — must not require the pattern on "".
        pc = _PathComponents(table_name="tbl", schema="sch", sub_folder="")
        assert pc.sub_folder == ""


class TestJoinCloudPath:
    def test_basic_join(self):
        result = join_cloud_path("s3://bucket", "prefix", "key")
        assert result == "s3://bucket/prefix/key"

    def test_with_trailing_slashes(self):
        result = join_cloud_path("s3://bucket/", "/prefix/", "/key/")
        assert result == "s3://bucket/prefix/key"

    def test_single_part(self):
        result = join_cloud_path("s3://bucket/key")
        assert result == "s3://bucket/key"

    def test_empty_parts(self):
        result = join_cloud_path("", "")
        assert result == ""

    def test_none_parts(self):
        result = join_cloud_path("s3://bucket", None, "key")
        assert result == "s3://bucket/key"

    def test_local_path(self):
        result = join_cloud_path("/base", "sch", "tbl")
        assert result == "/base/sch/tbl"

    def test_no_tail(self):
        result = join_cloud_path("s3://bucket")
        assert result == "s3://bucket"


class TestNewestMtime:
    def test_nonexistent_path(self):
        assert _newest_mtime(Path("/nonexistent/path")) is None

    def test_file(self, temp_dir):
        p = temp_dir / "test.txt"
        p.write_text("hello")
        mtime = _newest_mtime(p)
        assert mtime is not None
        assert isinstance(mtime, float)


class TestPathManager:
    def test_resolve_output_path(self, dict_context):
        dict_context["output_path"] = "/base/path"
        pm = _PathManager(dict_context, MagicMock())
        pm.config_validator.validate_output_key.return_value = {
            "schema": "sch",
            "sub_folder": "sub",
            "table_name": "tbl",
        }
        result = pm.resolve_output_path({}, "sch.sub.tbl", "dev")
        assert "sch" in result
        assert "sub" in result
        assert "tbl" in result

    def test_resolve_output_path_rejects_table_name_override_traversal(self, dict_context):
        """Regression: `dataset_config`'s explicit `table_name`/`schema`/
        `sub_folder` override bypassed VALID_NAME_PATTERN entirely."""
        dict_context["output_path"] = "/base/path"
        pm = _PathManager(dict_context, MagicMock())
        pm.config_validator.validate_output_key.return_value = {
            "schema": "sch",
            "sub_folder": "sub",
            "table_name": "tbl",
        }
        with pytest.raises(ConfigurationError, match="Invalid characters"):
            pm.resolve_output_path({"table_name": "../../etc"}, "sch.sub.tbl", "dev")
