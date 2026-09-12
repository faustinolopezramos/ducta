import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ducta.gate.exceptions import ConfigurationError, MissingDependencyError, ReadOperationError
from ducta.gate.input import InputLoader


class TestInputLoaderInit:
    def test_init_with_dict_context(self, dict_context):
        loader = InputLoader(dict_context)
        assert loader.reader_factory is not None

    def test_init_with_spark_context(self, dict_context_with_spark):
        loader = InputLoader(dict_context_with_spark)
        assert loader.reader_factory is not None


class TestGetInputKeys:
    def test_list_of_strings(self):
        loader = InputLoader({"execution_mode": "local", "input_config": {}})
        result = loader._get_input_keys({"input": ["a", "b"]})
        assert result == ["a", "b"]

    def test_single_string(self):
        loader = InputLoader({"execution_mode": "local", "input_config": {}})
        result = loader._get_input_keys({"input": "single"})
        assert result == ["single"]

    def test_named_map(self):
        loader = InputLoader({"execution_mode": "local", "input_config": {}})
        result = loader._get_input_keys({"input": {"param1": "ds1", "param2": "ds2"}})
        assert result == ["ds1", "ds2"]

    def test_none_input(self):
        loader = InputLoader({"execution_mode": "local", "input_config": {}})
        result = loader._get_input_keys({"input": None})
        assert result == []

    def test_missing_input(self):
        loader = InputLoader({"execution_mode": "local", "input_config": {}})
        result = loader._get_input_keys({})
        assert result == []

    def test_invalid_type(self):
        loader = InputLoader({"execution_mode": "local", "input_config": {}})
        with pytest.raises(ConfigurationError, match="Invalid input format"):
            loader._get_input_keys({"input": 42})

    def test_empty_string_in_list(self):
        loader = InputLoader({"execution_mode": "local", "input_config": {}})
        with pytest.raises(ConfigurationError, match="Invalid input key"):
            loader._get_input_keys({"input": ["valid", ""]})


class TestIsNamedInputMap:
    def test_valid_map(self):
        assert InputLoader._is_named_input_map({"p1": "d1", "p2": "d2"}) is True

    def test_empty_map(self):
        assert InputLoader._is_named_input_map({}) is False

    def test_not_a_map(self):
        assert InputLoader._is_named_input_map(["a", "b"]) is False

    def test_none(self):
        assert InputLoader._is_named_input_map(None) is False


class TestGetInputParamNames:
    def test_with_named_map(self):
        loader = InputLoader({"execution_mode": "local", "input_config": {}})
        result = loader.get_input_param_names({"input": {"p1": "d1", "p2": "d2"}})
        assert result == ["p1", "p2"]

    def test_with_list(self):
        loader = InputLoader({"execution_mode": "local", "input_config": {}})
        result = loader.get_input_param_names({"input": ["a", "b"]})
        assert result is None


class TestGetDatasetConfig:
    def test_valid_config(self, dict_context):
        dict_context["input_config"] = {"ds1": {"format": "csv", "filepath": "/data.csv"}}
        loader = InputLoader(dict_context)
        result = loader._get_dataset_config("ds1")
        assert result["format"] == "csv"

    def test_missing_config(self, dict_context):
        loader = InputLoader(dict_context)
        with pytest.raises(ConfigurationError, match="Missing configuration"):
            loader._get_dataset_config("nonexistent")

    def test_invalid_config_type(self, dict_context):
        dict_context["input_config"] = {"ds1": "not_a_dict"}
        loader = InputLoader(dict_context)
        with pytest.raises(ConfigurationError, match="Invalid configuration format"):
            loader._get_dataset_config("ds1")


class TestGetFilepath:
    def test_cloud_path(self, dict_context):
        loader = InputLoader(dict_context)
        result = loader._get_filepath({"filepath": "s3://bucket/data.csv"}, "ds1")
        assert result == "s3://bucket/data.csv"

    def test_local_path_missing(self, dict_context):
        dict_context["execution_mode"] = "local"
        loader = InputLoader(dict_context)
        with pytest.raises(ConfigurationError, match="does not exist"):
            loader._get_filepath({"filepath": "/nonexistent/path"}, "ds1")

    def test_missing_filepath(self, dict_context):
        loader = InputLoader(dict_context)
        with pytest.raises(ConfigurationError, match="Missing filepath"):
            loader._get_filepath({}, "ds1")

    def test_local_glob_pattern_no_match(self, dict_context, temp_dir):
        dict_context["execution_mode"] = "local"
        loader = InputLoader(dict_context)
        pattern = str(temp_dir / "nonexistent_*.csv")
        with pytest.raises(ConfigurationError, match="matched no files"):
            loader._get_filepath({"filepath": pattern}, "ds1")


class TestContainsGlobPattern:
    def test_asterisk(self):
        assert InputLoader._contains_glob_pattern("/path/to/*.csv") is True

    def test_question_mark(self):
        assert InputLoader._contains_glob_pattern("/path/to/file?.csv") is True

    def test_brackets(self):
        assert InputLoader._contains_glob_pattern("/path/to/[ab].csv") is True

    def test_no_glob(self):
        assert InputLoader._contains_glob_pattern("/path/to/file.csv") is False


class TestInputsAvailable:
    def test_with_query_skips_check(self, dict_context):
        dict_context["input_config"] = {"ds1": {"format": "query", "query": "SELECT 1"}}
        loader = InputLoader(dict_context)
        available, missing = loader._inputs_available({"input": ["ds1"]})
        assert available is True

    def test_missing_config(self, dict_context):
        loader = InputLoader(dict_context)
        available, missing = loader._inputs_available({"input": ["nonexistent"]})
        assert available is False
        assert "nonexistent" in missing


class TestMaxInputMtime:
    def test_no_inputs(self, dict_context):
        loader = InputLoader(dict_context)
        result = loader.max_input_mtime({"input": []})
        assert result is None

    def test_cloud_path_skipped(self, dict_context):
        dict_context["input_config"] = {
            "ds1": {"format": "csv", "filepath": "s3://bucket/data.csv"},
        }
        loader = InputLoader(dict_context)
        result = loader.max_input_mtime({"input": ["ds1"]})
        assert result is None


class TestGetConfiguredFormats:
    def test_various_formats(self, dict_context):
        dict_context["input_config"] = {
            "a": {"format": "csv"},
            "b": {"format": "parquet"},
            "c": {"format": "delta"},
        }
        loader = InputLoader(dict_context)
        result = loader._get_configured_formats()
        assert result == {"csv", "parquet", "delta"}

    def test_empty_config(self, dict_context):
        loader = InputLoader(dict_context)
        result = loader._get_configured_formats()
        assert result == set()


class TestLoadInputsParallel:
    def test_fail_fast_does_not_wait_for_blocked_datasets(self, dict_context):
        dict_context["global_config"]["max_input_workers"] = 4
        loader = InputLoader(dict_context)
        release = threading.Event()

        def fake_load(input_key):
            if input_key == "bad":
                raise ReadOperationError("boom")
            release.wait(timeout=5)
            return input_key

        with patch.object(loader, "_load_single_dataset", side_effect=fake_load):
            start = time.monotonic()
            with pytest.raises(ReadOperationError, match="bad"):
                loader._load_inputs_parallel(["bad", "slow1", "slow2", "slow3"], fail_fast=True)
            elapsed = time.monotonic() - start

        assert elapsed < 1.0
        release.set()

    def test_fill_none_on_error_preserves_order(self, dict_context):
        dict_context["global_config"]["max_input_workers"] = 3
        dict_context["global_config"]["fill_none_on_error"] = True
        loader = InputLoader(dict_context)

        def fake_load(input_key):
            if input_key == "bad":
                raise ReadOperationError("boom")
            return input_key.upper()

        with patch.object(loader, "_load_single_dataset", side_effect=fake_load):
            results = loader._load_inputs_parallel(["a", "bad", "b"], fail_fast=False)

        assert results == ["A", None, "B"]

    def test_no_fill_none_raises_with_error_count(self, dict_context):
        dict_context["global_config"]["fill_none_on_error"] = False
        loader = InputLoader(dict_context)

        def fake_load(input_key):
            if input_key in ("bad1", "bad2"):
                raise ReadOperationError("boom")
            return input_key

        with patch.object(loader, "_load_single_dataset", side_effect=fake_load):
            with pytest.raises(ReadOperationError, match="2 dataset\\(s\\) failed to load"):
                loader._load_inputs_parallel(["ok", "bad1", "bad2"], fail_fast=False)


class TestEnforceFingerprintPolicy:
    #: The policy only compares fingerprints measured the same way, so both
    #: sides of every case below must carry a matching algorithm/engine — see
    #: `test_a_changed_algorithm_is_not_reported_as_drift` for the other branch.
    ALGO = "xxhash64-multiset/v2"
    ENGINE = "spark"

    def _previous(self, **overrides):
        """A previously-recorded fingerprint dict, comparable by default."""
        base = {
            "fingerprint": "old_hash",
            "algorithm": self.ALGO,
            "engine": self.ENGINE,
            "row_count": 8,
            "file_mtime": "1.0",
        }
        base.update(overrides)
        return base

    def _make_fingerprint(
        self, fingerprint="new_hash", row_count=10, file_mtime="2.0", columns=None, algorithm=None
    ):
        fp = MagicMock()
        fp.fingerprint = fingerprint
        fp.row_count = row_count
        fp.file_mtime = file_mtime
        fp.columns = columns
        # `_enforce_fingerprint_policy` asks the fingerprint to describe itself
        # before comparing, so a mock has to answer with a real dict.
        fp.to_dict.return_value = {
            "fingerprint": fingerprint,
            "algorithm": algorithm or self.ALGO,
            "engine": self.ENGINE,
            "row_count": row_count,
            "columns": columns,
        }
        return fp

    def test_warn_message_includes_schema_drift_detail(self, dict_context):
        dict_context["global_config"]["fingerprint_policy"] = "warn"
        dict_context["_previous_input_fingerprints"] = {
            "ds1": self._previous(columns={"a": "int64", "b": "string"})
        }
        loader = InputLoader(dict_context)
        fingerprint = self._make_fingerprint(columns={"a": "int64", "c": "bool"})

        with patch("ducta.gate.input.logger") as mock_logger:
            loader._enforce_fingerprint_policy("ds1", fingerprint)

        message = mock_logger.warning.call_args[0][1]
        assert "schema drift" in message
        assert "removed=['b']" in message
        assert "added=['c']" in message

    def test_warn_message_without_schema_drift_has_no_detail(self, dict_context):
        dict_context["global_config"]["fingerprint_policy"] = "warn"
        dict_context["_previous_input_fingerprints"] = {
            "ds1": self._previous(columns={"a": "int64"})
        }
        loader = InputLoader(dict_context)
        fingerprint = self._make_fingerprint(columns={"a": "int64"})

        with patch("ducta.gate.input.logger") as mock_logger:
            loader._enforce_fingerprint_policy("ds1", fingerprint)

        message = mock_logger.warning.call_args[0][1]
        assert "changed since the previous" in message
        assert "schema drift" not in message

    def test_fail_policy_raises_with_schema_drift(self, dict_context):
        dict_context["global_config"]["fingerprint_policy"] = "fail"
        dict_context["_previous_input_fingerprints"] = {
            "ds1": self._previous(columns={"a": "int64"})
        }
        loader = InputLoader(dict_context)
        fingerprint = self._make_fingerprint(columns={"a": "float64"})

        with pytest.raises(ReadOperationError, match="schema drift: type_changed=\\['a'\\]"):
            loader._enforce_fingerprint_policy("ds1", fingerprint)

    def test_record_policy_does_nothing(self, dict_context):
        dict_context["global_config"]["fingerprint_policy"] = "record"
        dict_context["_previous_input_fingerprints"] = {"ds1": self._previous()}
        loader = InputLoader(dict_context)
        fingerprint = self._make_fingerprint(fingerprint="new_hash")

        loader._enforce_fingerprint_policy("ds1", fingerprint)  # must not raise

    def test_a_changed_algorithm_is_not_reported_as_drift(self, dict_context):
        # Upgrading Ducta changes every fingerprint's value. Reporting that as
        # "the input changed" would fire on every dataset the first time anyone
        # upgrades — and with policy=fail, abort the pipeline over it.
        dict_context["global_config"]["fingerprint_policy"] = "fail"
        dict_context["_previous_input_fingerprints"] = {
            "ds1": self._previous(algorithm="legacy/v1")
        }
        loader = InputLoader(dict_context)
        fingerprint = self._make_fingerprint(algorithm="xxhash64-multiset/v2")

        loader._enforce_fingerprint_policy("ds1", fingerprint)  # must not raise

    def test_a_changed_engine_is_not_reported_as_drift(self, dict_context):
        dict_context["global_config"]["fingerprint_policy"] = "fail"
        previous = self._previous()
        previous["engine"] = "pandas"
        dict_context["_previous_input_fingerprints"] = {"ds1": previous}
        loader = InputLoader(dict_context)

        loader._enforce_fingerprint_policy("ds1", self._make_fingerprint())  # must not raise


class TestReadFallbackPaths:
    """Set by parallel sweep/search trials (core.sweep_worker): trial 1
    materializes the trial-invariant upstream prefix into a shared directory,
    and trials 2..N fall back to reading from it when a dataset isn't (yet)
    in their own isolated output_path."""

    def test_resolves_from_fallback_when_missing_in_own_output_path(self, dict_context, temp_dir):
        own = temp_dir / "trial_2"
        shared = temp_dir / "_shared"
        own.mkdir()
        (shared / "schema" / "table").mkdir(parents=True)
        (shared / "schema" / "table" / "part.parquet").write_text("data")

        dict_context["execution_mode"] = "local"
        dict_context["output_path"] = str(own)
        dict_context["_read_fallback_paths"] = [str(shared)]
        loader = InputLoader(dict_context)

        missing_path = str(own / "schema" / "table" / "part.parquet")
        result = loader._get_filepath({"filepath": missing_path}, "ds1")

        assert Path(result).resolve() == (shared / "schema" / "table" / "part.parquet").resolve()

    def test_does_not_apply_to_inputs_outside_own_output_path(self, dict_context, temp_dir):
        # An externally-declared input path (outside output_path) has nothing
        # to do with trial isolation — it must raise normally, not silently
        # search the fallback prefix for something with a matching relative path.
        shared = temp_dir / "_shared"
        shared.mkdir()
        external = temp_dir / "external.csv"  # never created

        dict_context["execution_mode"] = "local"
        dict_context["output_path"] = str(temp_dir / "trial_2")
        dict_context["_read_fallback_paths"] = [str(shared)]
        loader = InputLoader(dict_context)

        with pytest.raises(ConfigurationError, match="does not exist"):
            loader._get_filepath({"filepath": str(external)}, "ds1")

    def test_still_raises_when_missing_from_both_own_and_fallback(self, dict_context, temp_dir):
        own = temp_dir / "trial_2"
        shared = temp_dir / "_shared"
        own.mkdir()
        shared.mkdir()

        dict_context["execution_mode"] = "local"
        dict_context["output_path"] = str(own)
        dict_context["_read_fallback_paths"] = [str(shared)]
        loader = InputLoader(dict_context)

        with pytest.raises(ConfigurationError, match="does not exist"):
            loader._get_filepath({"filepath": str(own / "nope.parquet")}, "ds1")

    def test_no_fallback_configured_behaves_exactly_as_before(self, dict_context, temp_dir):
        own = temp_dir / "trial_2"
        own.mkdir()

        dict_context["execution_mode"] = "local"
        dict_context["output_path"] = str(own)
        # No "_read_fallback_paths" key at all — any caller predating this
        # feature has this exact context shape.
        loader = InputLoader(dict_context)

        with pytest.raises(ConfigurationError, match="does not exist"):
            loader._get_filepath({"filepath": str(own / "nope.parquet")}, "ds1")

    def test_own_output_path_missing_disables_fallback_lookup(self, dict_context, temp_dir):
        shared = temp_dir / "_shared"
        (shared / "part.parquet").parent.mkdir(parents=True, exist_ok=True)
        (shared / "part.parquet").write_text("data")

        dict_context["execution_mode"] = "local"
        dict_context.pop("output_path", None)
        dict_context["_read_fallback_paths"] = [str(shared)]
        loader = InputLoader(dict_context)

        with pytest.raises(ConfigurationError, match="does not exist"):
            loader._get_filepath({"filepath": str(temp_dir / "trial_2" / "part.parquet")}, "ds1")
