from datetime import datetime

import pytest

from ducta.gate.exceptions import ConfigurationError, WriteOperationError
from ducta.gate.output import DataOutputManager, parse_iso_datetime, validate_date_range
from ducta.gate.output.paths import path_has_data


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
        assert path_has_data(str(p)) is True

    def test_path_has_data_empty_file(self, temp_dir):
        p = temp_dir / "empty.txt"
        p.touch()
        assert path_has_data(str(p)) is False

    def test_a_write_that_never_committed_is_not_data(self, temp_dir):
        # What a process killed mid-write leaves. It read as materialized.
        (temp_dir / "t" / "_temporary" / "0").mkdir(parents=True)
        assert path_has_data(str(temp_dir / "t")) is False

    def test_path_has_data_missing(self, temp_dir):
        assert path_has_data(str(temp_dir / "missing")) is False

    def test_path_has_data_dir_with_success(self, temp_dir):
        d = temp_dir / "out.parquet"
        d.mkdir()
        (d / "part-00000.parquet").write_text("data")
        (d / "_SUCCESS").write_text("")
        assert path_has_data(str(d)) is True

    def test_path_has_data_empty_dir(self, temp_dir):
        d = temp_dir / "empty"
        d.mkdir()
        assert path_has_data(str(d)) is False

    def test_path_has_data_dir_with_delta_log(self, temp_dir):
        d = temp_dir / "delta"
        d.mkdir()
        (d / "part-00000.parquet").write_text("data")
        dl = d / "_delta_log"
        dl.mkdir()
        (dl / "000000.json").write_text("{}")
        assert path_has_data(str(d)) is True

    def test_an_empty_result_is_written_where_there_is_nothing_to_lose(
        self, dict_context_with_spark, spark_dataframe_spec, tmp_path
    ):
        """0 rows into a dataset that holds nothing yet: written (an empty dataset)."""
        spark_dataframe_spec.isEmpty.return_value = True
        dict_context_with_spark["output_config"]["sch.sub.tbl"] = {
            "write_mode": "overwrite",
            "filepath": str(tmp_path / "tbl"),
        }
        dom = DataOutputManager(dict_context_with_spark)
        written = []
        dom._save_single_output = lambda key, *a, **k: written.append(key)

        dom.save_output("dev", {"output": ["sch.sub.tbl"], "name": "test"}, spark_dataframe_spec)

        assert written == ["sch.sub.tbl"]

    def test_empty_df_skips_an_append_target_and_records_an_evidence_gap(
        self, dict_context_with_spark, spark_dataframe_spec
    ):
        """Appending nothing is a real no-op — but the certificate must say so."""
        from ducta.core.ledger import ledger_for

        spark_dataframe_spec.isEmpty.return_value = True
        dict_context_with_spark["output_config"]["sch.sub.tbl"] = {"write_mode": "append"}
        dom = DataOutputManager(dict_context_with_spark)
        written = []
        dom._save_single_output = lambda key, *a, **k: written.append(key)

        dom.save_output("dev", {"output": ["sch.sub.tbl"], "name": "test"}, spark_dataframe_spec)

        assert written == []
        ledger = ledger_for(dict_context_with_spark)
        assert ledger.evidence_complete is False
        assert any("sch.sub.tbl" in gap for gap in ledger.record_failures)

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


class TestSaveModelArtifacts:
    """Regression: artifact["name"] and model_version became path
    components without going through the same VALID_NAME_PATTERN check
    validate_output_key already applies to output keys."""

    def test_rejects_path_traversal_in_artifact_name(self, dict_context, temp_dir):
        registry_dir = temp_dir / "registry"
        registry_dir.mkdir()
        dict_context["global_config"]["model_registry_path"] = str(registry_dir)
        dom = DataOutputManager(dict_context)

        node = {"name": "my_node", "model_artifacts": [{"name": "../../escaped"}]}
        with pytest.raises(WriteOperationError, match="escaped"):
            dom._save_model_artifacts(node, "v1")

        assert not (temp_dir / "escaped").exists()
        assert list(registry_dir.iterdir()) == []

    def test_rejects_path_traversal_in_model_version(self, dict_context, temp_dir):
        registry_dir = temp_dir / "registry"
        registry_dir.mkdir()
        dict_context["global_config"]["model_registry_path"] = str(registry_dir)
        dom = DataOutputManager(dict_context)

        node = {"name": "my_node", "model_artifacts": [{"name": "valid_name"}]}
        with pytest.raises(WriteOperationError, match="escaped"):
            dom._save_model_artifacts(node, "../../escaped")

        assert not (temp_dir / "escaped").exists()

    def test_accepts_valid_artifact_name_and_version(self, dict_context, temp_dir):
        registry_dir = temp_dir / "registry"
        registry_dir.mkdir()
        dict_context["global_config"]["model_registry_path"] = str(registry_dir)
        dom = DataOutputManager(dict_context)

        node = {"name": "my_node", "model_artifacts": [{"name": "my_model"}]}
        dom._save_model_artifacts(node, "v1")

        assert (registry_dir / "my_model" / "v1" / "metadata.json").exists()


class TestSkippedFailuresLeaveAGapInTheEvidence:
    def test_a_failed_output_with_fail_on_error_false_is_noted(self, dict_context, spark_dataframe):
        from unittest.mock import MagicMock

        dict_context["global_config"]["fail_on_error"] = False
        spark_dataframe.isEmpty.return_value = False
        dom = DataOutputManager(dict_context)
        dom.df_manager.is_spark_dataframe = MagicMock(return_value=True)
        dom._save_single_output = MagicMock(side_effect=RuntimeError("disk full"))
        dom._note_evidence_gap = MagicMock()

        dom.save_output("dev", {"output": ["a.b.c"]}, spark_dataframe)

        reason = dom._note_evidence_gap.call_args[0][0]
        assert "a.b.c" in reason and "disk full" in reason and "fail_on_error" in reason

    def test_with_fail_on_error_true_it_still_raises(self, dict_context, spark_dataframe):
        from unittest.mock import MagicMock

        spark_dataframe.isEmpty.return_value = False
        dom = DataOutputManager(dict_context)
        dom.df_manager.is_spark_dataframe = MagicMock(return_value=True)
        dom._save_single_output = MagicMock(side_effect=RuntimeError("disk full"))
        with pytest.raises(RuntimeError, match="disk full"):
            dom.save_output("dev", {"output": ["a.b.c"]}, spark_dataframe)


class TestRunWindowReachesTheWriter:
    """`replaceWhere` replaces the run's slice, so the writer has to be told the window."""

    CONFIG = {
        "format": "delta",
        "overwrite_strategy": "replaceWhere",
        "partition_col": "day",
    }

    def test_the_run_window_is_added_to_a_replacewhere_output(self):
        config = DataOutputManager._with_run_window(self.CONFIG, "2026-01-02", "2026-01-02")
        assert (config["start_date"], config["end_date"]) == ("2026-01-02", "2026-01-02")
        assert "start_date" not in self.CONFIG  # the dataset's own config is not mutated

    def test_a_window_written_in_the_dataset_wins(self):
        pinned = {**self.CONFIG, "start_date": "2025-12-01", "end_date": "2025-12-31"}
        config = DataOutputManager._with_run_window(pinned, "2026-01-02", "2026-01-02")
        assert (config["start_date"], config["end_date"]) == ("2025-12-01", "2025-12-31")

    def test_other_outputs_are_left_alone(self):
        plain = {"format": "parquet", "write_mode": "append"}
        assert DataOutputManager._with_run_window(plain, "2026-01-02", "2026-01-02") is plain

    def test_a_run_without_dates_changes_nothing(self):
        assert DataOutputManager._with_run_window(self.CONFIG, None, None) is self.CONFIG


def _holding_data(path):
    path.mkdir(parents=True)
    (path / "part-00000.parquet").write_text("rows")
    return str(path)


class TestAnEmptyResultDoesNotEmptyADataset:
    """0 rows + overwrite would delete what the dataset holds: refused unless allowed."""

    def _dom(self, context, **cfg):
        context["output_config"]["sch.sub.tbl"] = {"write_mode": "overwrite", **cfg}
        dom = DataOutputManager(context)
        written = []
        dom._save_single_output = lambda key, *a, **k: written.append(key)
        return dom, written

    def test_refused_and_nothing_written(
        self, dict_context_with_spark, spark_dataframe_spec, tmp_path
    ):
        spark_dataframe_spec.isEmpty.return_value = True
        dom, written = self._dom(dict_context_with_spark, filepath=_holding_data(tmp_path / "t"))
        with pytest.raises(WriteOperationError, match=r"produced 0 rows.*allow_empty: true"):
            dom.save_output(
                "dev", {"output": ["sch.sub.tbl"], "name": "load"}, spark_dataframe_spec
            )
        assert written == []

    def test_allow_empty_writes_it(self, dict_context_with_spark, spark_dataframe_spec, tmp_path):
        spark_dataframe_spec.isEmpty.return_value = True
        dom, written = self._dom(
            dict_context_with_spark, filepath=_holding_data(tmp_path / "t"), allow_empty=True
        )
        dom.save_output("dev", {"output": ["sch.sub.tbl"], "name": "load"}, spark_dataframe_spec)
        assert written == ["sch.sub.tbl"]

    def test_a_table_is_assumed_to_hold_data(self, dict_context_with_spark, spark_dataframe_spec):
        spark_dataframe_spec.isEmpty.return_value = True
        dom, written = self._dom(
            dict_context_with_spark, format="unity_catalog", catalog_name="main"
        )
        with pytest.raises(WriteOperationError, match="produced 0 rows"):
            dom.save_output(
                "dev", {"output": ["sch.sub.tbl"], "name": "load"}, spark_dataframe_spec
            )

    def test_with_fail_on_error_false_it_is_skipped_and_noted(
        self, dict_context_with_spark, spark_dataframe_spec, tmp_path
    ):
        from ducta.core.ledger import ledger_for

        spark_dataframe_spec.isEmpty.return_value = True
        dict_context_with_spark["global_config"]["fail_on_error"] = False
        dom, written = self._dom(dict_context_with_spark, filepath=_holding_data(tmp_path / "t"))
        dom.save_output("dev", {"output": ["sch.sub.tbl"], "name": "load"}, spark_dataframe_spec)
        assert written == []
        gaps = ledger_for(dict_context_with_spark).record_failures
        assert any("sch.sub.tbl" in gap and "0 rows" in gap for gap in gaps)


class TestSeveralOutputs:
    """A node's outputs are all writable before any is written; a failure halfway is recorded."""

    def _context(self, context, tmp_path, second):
        context["output_config"]["a.b.first"] = {
            "format": "parquet",
            "filepath": str(tmp_path / "first"),
        }
        context["output_config"]["a.b.second"] = {"format": "parquet", **second}
        return context

    def test_an_unwritable_one_stops_them_all_before_any_write(
        self, dict_context, spark_dataframe, tmp_path
    ):
        blocker = tmp_path / "a_file"
        blocker.write_text("not a directory")
        context = self._context(dict_context, tmp_path, {"filepath": str(blocker / "second")})
        dom = DataOutputManager(context)
        dom.df_manager.is_spark_dataframe = lambda df: True
        written = []
        dom._save_single_output = lambda key, *a, **k: written.append(key)
        with pytest.raises(ConfigurationError, match=r"none was written.*a\.b\.second"):
            dom.save_output("dev", {"output": ["a.b.first", "a.b.second"]}, spark_dataframe)
        assert written == []

    def test_an_unsupported_format_is_found_first(self, dict_context, spark_dataframe, tmp_path):
        context = self._context(
            dict_context, tmp_path, {"format": "unity_catalog", "catalog_name": "main"}
        )
        dom = DataOutputManager(context)
        dom.df_manager.is_spark_dataframe = lambda df: True
        dom._save_single_output = lambda *a, **k: pytest.fail("nothing may be written")
        with pytest.raises(ConfigurationError, match="needs a session with Unity Catalog"):
            dom.save_output("dev", {"output": ["a.b.first", "a.b.second"]}, spark_dataframe)

    def test_a_failure_halfway_is_recorded_as_a_partial_write(
        self, dict_context, spark_dataframe, tmp_path
    ):
        from ducta.core.ledger import ledger_for

        context = self._context(dict_context, tmp_path, {"filepath": str(tmp_path / "second")})
        dom = DataOutputManager(context)
        dom.df_manager.is_spark_dataframe = lambda df: True

        def save(key, *args, **kwargs):
            if key == "a.b.second":
                raise RuntimeError("disk full")

        dom._save_single_output = save
        with pytest.raises(RuntimeError, match="disk full"):
            dom.save_output("dev", {"output": ["a.b.first", "a.b.second"]}, spark_dataframe)
        gaps = ledger_for(context).record_failures
        assert any("partial write" in g and "a.b.first" in g and "a.b.second" in g for g in gaps)
