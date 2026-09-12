from unittest.mock import MagicMock, patch

from ducta.gate.context_manager import ContextManager
from ducta.gate.fingerprinting import compute_fingerprint, diff_schema_columns


class TestComputeFingerprint:
    def test_reads_mode_from_global_config(self):
        cm = ContextManager({"global_config": {"fingerprint_mode": "full"}})
        fake_cls = MagicMock()
        with patch.dict(
            "sys.modules", {"ducta.mlrun.fingerprint": MagicMock(DataFingerprint=fake_cls)}
        ):
            compute_fingerprint(cm, key="ds1", identifier="/tmp/ds1.csv", dataframe=MagicMock())
        fake_cls.from_file_and_df.assert_called_once()
        _, kwargs = fake_cls.from_file_and_df.call_args
        assert kwargs["mode"] == "full"
        assert kwargs["sample_rows"] == 100

    def test_explicit_sample_rows_overrides_settings(self):
        cm = ContextManager({"global_config": {"fingerprint_sample_rows": 500}})
        fake_cls = MagicMock()
        with patch.dict(
            "sys.modules", {"ducta.mlrun.fingerprint": MagicMock(DataFingerprint=fake_cls)}
        ):
            compute_fingerprint(
                cm,
                key="ds1",
                identifier="/tmp/ds1.csv",
                dataframe=MagicMock(),
                sample_rows=7,
            )
        _, kwargs = fake_cls.from_file_and_df.call_args
        assert kwargs["sample_rows"] == 7

    def test_defaults_sample_rows_from_settings_when_not_explicit(self):
        cm = ContextManager({"global_config": {"fingerprint_sample_rows": 500}})
        fake_cls = MagicMock()
        with patch.dict(
            "sys.modules", {"ducta.mlrun.fingerprint": MagicMock(DataFingerprint=fake_cls)}
        ):
            compute_fingerprint(cm, key="ds1", identifier="/tmp/ds1.csv", dataframe=MagicMock())
        _, kwargs = fake_cls.from_file_and_df.call_args
        assert kwargs["sample_rows"] == 500


class TestDiffSchemaColumns:
    def test_no_change_returns_none(self):
        cols = {"a": "int64", "b": "string"}
        assert diff_schema_columns(cols, dict(cols)) is None

    def test_added_column(self):
        result = diff_schema_columns({"a": "int64"}, {"a": "int64", "b": "string"})
        assert result == "added=['b']"

    def test_removed_column(self):
        result = diff_schema_columns({"a": "int64", "b": "string"}, {"a": "int64"})
        assert result == "removed=['b']"

    def test_retyped_column(self):
        result = diff_schema_columns({"a": "int64"}, {"a": "float64"})
        assert result == "type_changed=['a']"

    def test_added_removed_retyped_combined(self):
        previous = {"a": "int64", "b": "string", "c": "bool"}
        current = {"a": "float64", "b": "string", "d": "int64"}
        result = diff_schema_columns(previous, current)
        assert result == "added=['d']; removed=['c']; type_changed=['a']"

    def test_none_when_previous_missing(self):
        assert diff_schema_columns(None, {"a": "int64"}) is None

    def test_none_when_current_missing(self):
        assert diff_schema_columns({"a": "int64"}, None) is None

    def test_none_when_both_missing(self):
        assert diff_schema_columns(None, None) is None

    def test_none_when_both_empty(self):
        assert diff_schema_columns({}, {}) is None
