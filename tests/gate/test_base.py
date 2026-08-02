from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ducta.gate.base import BaseIO
from ducta.gate.exceptions import ConfigurationError, IOManagerError


class TestBaseIOInit:
    def test_with_dict_context(self):
        io = BaseIO({"key": "val"})
        assert io.context == {"key": "val"}
        assert io.config_validator is not None
        assert io.context_manager is not None

    def test_with_none_raises(self):
        with pytest.raises(ConfigurationError, match="Context cannot be None"):
            BaseIO(None)


class TestBaseIOContextSetter:
    def test_set_new_context(self):
        io = BaseIO({"old": "ctx"})
        io.context = {"new": "ctx"}
        assert io.context == {"new": "ctx"}

    def test_set_none_raises(self):
        io = BaseIO({"a": 1})
        with pytest.raises(ConfigurationError, match="Context cannot be None"):
            io.context = None


class TestBaseIOCtxGet:
    def test_get_from_dict(self):
        io = BaseIO({"key": "value"})
        assert io._ctx_get("key") == "value"

    def test_get_default(self):
        io = BaseIO({"a": 1})
        assert io._ctx_get("missing", "default") == "default"


class TestBaseIOSpark:
    def test_no_spark(self):
        io = BaseIO({"spark": None})
        assert io._ctx_spark() is None

    def test_spark_available(self):
        spark = object()
        io = BaseIO({"spark": spark})
        assert io._ctx_spark() is spark


class TestBaseIOExecutionMode:
    def test_local(self):
        io = BaseIO({"execution_mode": "local"})
        assert io._get_execution_mode() == "local"
        assert io._is_local() is True

    def test_distributed(self):
        io = BaseIO({"execution_mode": "distributed"})
        assert io._is_local() is False


class TestBaseIOSparkAvailable:
    def test_available(self):
        io = BaseIO({"spark": object()})
        assert io._spark_available() is True

    def test_not_available(self):
        io = BaseIO({"spark": None})
        assert io._spark_available() is False


class TestBaseIOPrepareLocalDirectory:
    def test_creates_directory(self, temp_dir):
        io = BaseIO({"execution_mode": "local"})
        path = str(temp_dir / "new_dir" / "file.txt")
        io._prepare_local_directory(path)
        assert (temp_dir / "new_dir").exists()

    def test_creates_directory_for_dir_path(self, temp_dir):
        io = BaseIO({"execution_mode": "local"})
        path = str(temp_dir / "new_dir") + "/"
        io._prepare_local_directory(path)
        assert (temp_dir / "new_dir").exists()

    def test_skips_cloud_path(self, temp_dir):
        io = BaseIO({"execution_mode": "local"})
        io._prepare_local_directory("s3://bucket/key")
        assert not (temp_dir / "s3").exists()

    def test_skips_existing_directory(self, temp_dir):
        io = BaseIO({"execution_mode": "local"})
        path = str(temp_dir)
        io._prepare_local_directory(path)

    @patch("ducta.gate.base.Path.mkdir")
    def test_raises_on_os_error(self, mock_mkdir):
        mock_mkdir.side_effect = OSError("permission denied")
        io = BaseIO({"execution_mode": "local"})
        with pytest.raises(IOManagerError, match="Failed to create directory"):
            io._prepare_local_directory("/no-perm/dir/file.txt")


class TestBaseIOSanitizeSQL:
    def test_sanitize_valid_query(self):
        sql = BaseIO.sanitize_sql_query("SELECT 1 AS col")
        assert sql == "SELECT 1 AS col"

    def test_sanitize_invalid_query(self):
        from ducta.gate.exceptions import ConfigurationError

        with pytest.raises(ConfigurationError):
            BaseIO.sanitize_sql_query("DROP TABLE t")


class TestBaseIORecordFingerprint:
    def test_disabled_returns_none_without_importing_mlrun(self):
        io = BaseIO({"global_settings": {"enable_data_fingerprinting": False}})
        with patch("ducta.gate.fingerprinting.compute_fingerprint") as mock_compute:
            result = io._record_fingerprint("input", "ds1", "/tmp/ds1.csv", MagicMock())
        mock_compute.assert_not_called()
        assert result is None

    def test_mlrun_unavailable_returns_none(self):
        io = BaseIO({"global_settings": {"enable_data_fingerprinting": True}})
        with patch(
            "ducta.gate.fingerprinting.compute_fingerprint",
            side_effect=ImportError("no mlrun"),
        ):
            result = io._record_fingerprint("input", "ds1", "/tmp/ds1.csv", MagicMock())
        assert result is None
        assert "_input_fingerprints" not in io.context

    def test_stores_under_input_scope_dict_context(self):
        context = {"global_settings": {"enable_data_fingerprinting": True}}
        io = BaseIO(context)
        fake_fingerprint = MagicMock()
        fake_fingerprint.to_dict.return_value = {"fingerprint": "abc"}
        with patch("ducta.gate.fingerprinting.compute_fingerprint", return_value=fake_fingerprint):
            result = io._record_fingerprint("input", "ds1", "/tmp/ds1.csv", MagicMock())
        assert result is fake_fingerprint
        assert context["_input_fingerprints"]["ds1"] == {"fingerprint": "abc"}

    def test_stores_under_output_scope_object_context(self):
        class Ctx:
            global_settings = {"enable_data_fingerprinting": True}

        ctx = Ctx()
        io = BaseIO(ctx)
        fake_fingerprint = MagicMock()
        fake_fingerprint.to_dict.return_value = {"fingerprint": "xyz"}
        with patch("ducta.gate.fingerprinting.compute_fingerprint", return_value=fake_fingerprint):
            result = io._record_fingerprint("output", "out1", "tbl", MagicMock())
        assert result is fake_fingerprint
        assert ctx._output_fingerprints["out1"] == {"fingerprint": "xyz"}

    def test_accumulates_across_calls(self):
        context = {"global_settings": {"enable_data_fingerprinting": True}}
        io = BaseIO(context)

        def fake_compute(context_manager, *, key, identifier, dataframe, sample_rows=None):
            fp = MagicMock()
            fp.to_dict.return_value = {"key": key}
            return fp

        with patch("ducta.gate.fingerprinting.compute_fingerprint", side_effect=fake_compute):
            io._record_fingerprint("input", "ds1", "/tmp/ds1.csv", MagicMock())
            io._record_fingerprint("input", "ds2", "/tmp/ds2.csv", MagicMock())

        assert context["_input_fingerprints"] == {
            "ds1": {"key": "ds1"},
            "ds2": {"key": "ds2"},
        }
