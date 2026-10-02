"""Configuration format 2: schema (phase 0) and loader/compiler (phase 2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ducta.setting.project_loader import (
    ProjectConfigError,
    compile_project,
    find_project_root,
    validate_project,
)
from ducta.setting.project_schema import PipelineFile, json_schema

PROJECT = """\
version: 2
project: demo
paths: {input: data, output: out}
settings:
  max_parallel_nodes: 4
environments:
  prod:
    settings: {max_parallel_nodes: 8}
    paths: {output: s3://lake/prod}
    catalog.silver.etl.orders.write.mode: append
    pipelines.etl.nodes.clean.quality.gate.max_errors: 1
"""

CATALOG = """\
raw_orders:
  format: csv
  path: ${paths.input}/orders.csv
  options: {header: true}
  quality: {not_empty: true}
silver.etl.orders:
  format: delta
  write: {mode: overwrite}
gold.sales.totals:
  format: delta
  path: ${paths.output}/${env}/gold/totals
  write:
    mode: merge
    merge: {keys: [order_date]}
"""

PIPELINE = """\
description: demo
requires_dates: false
nodes:
  clean:
    run: pipelines.etl:clean
    inputs: {raw: raw_orders}
    outputs: [silver.etl.orders]
    quality:
      checks: {row_count: {min: 1}}
      gate: {max_errors: 0, on_fail: skip_downstream}
  totals:
    run: pipelines.etl:totals
    inputs: [silver.etl.orders]
    outputs: [gold.sales.totals]
    timeout_seconds: 60
  pull:
    kind: ingest
    ingest: {source: crm, table: customers}
    outputs: [bronze.crm.customers]
    after: [clean]
"""


def _project(
    tmp_path: Path, project=PROJECT, catalog=CATALOG, pipeline=PIPELINE, extra_catalog=""
) -> Path:
    (tmp_path / "pipelines").mkdir()
    (tmp_path / "ducta.yaml").write_text(project)
    (tmp_path / "catalog.yaml").write_text(
        catalog + extra_catalog + "bronze.crm.customers:\n  format: parquet\n"
    )
    (tmp_path / "pipelines" / "etl.yaml").write_text(pipeline)
    return tmp_path


def _compile(root: Path, env=None):
    return compile_project(validate_project(root, env))


class TestCompile:
    def test_the_five_engine_documents(self, tmp_path):
        docs = _compile(_project(tmp_path), "dev")

        g = docs["global_config"]
        assert (g["input_path"], g["output_path"], g["project_name"]) == ("data", "out", "demo")
        assert docs["pipelines_config"]["etl"]["nodes"] == ["clean", "totals", "pull"]

        clean = docs["nodes_config"]["clean"]
        assert (clean["module"], clean["function"]) == ("pipelines.etl", "clean")
        assert clean["input"] == {"raw": "raw_orders"}
        assert clean["data_quality"]["quality_gate"] == {
            "max_errors": 0,
            "behavior": "skip_downstream",
        }
        # The catalog contract of what the node reads becomes its input check.
        assert clean["sanity_checks"]["inputs"]["raw_orders"]["checks"] == {"not_empty": {}}
        assert docs["nodes_config"]["totals"]["timeout"] == 60

    def test_placeholders_become_the_engine_names(self, tmp_path):
        docs = _compile(_project(tmp_path))
        assert docs["input_config"]["raw_orders"]["filepath"] == "${input_path}/orders.csv"
        assert (
            docs["output_config"]["gold.sales.totals"]["filepath"]
            == "${output_path}/${environment}/gold/totals"
        )

    def test_a_dataset_without_path_is_read_where_its_writer_puts_it(self, tmp_path):
        docs = _compile(_project(tmp_path))
        assert "filepath" not in docs["output_config"]["silver.etl.orders"]
        assert (
            docs["input_config"]["silver.etl.orders"]["filepath"]
            == "${output_path}/${environment}/silver/etl/orders"
        )

    def test_a_pathless_dataset_whose_name_gives_no_path_is_an_error(self, tmp_path):
        bad = CATALOG.replace("silver.etl.orders:", "silver_orders:")
        pipeline = PIPELINE.replace("silver.etl.orders", "silver_orders")
        with pytest.raises(ProjectConfigError, match="has no 'path'"):
            validate_project(_project(tmp_path, catalog=bad, pipeline=pipeline))

    def test_write_spec_compiles_to_writer_keys_on_the_output_side_only(self, tmp_path):
        docs = _compile(_project(tmp_path))
        out = docs["output_config"]["gold.sales.totals"]
        assert (out["write_mode"], out["merge"]["keys"]) == ("merge", ["order_date"])
        assert "write_mode" not in docs["input_config"].get("gold.sales.totals", {})

    def test_kinds(self, tmp_path):
        nodes = _compile(_project(tmp_path))["nodes_config"]
        assert nodes["pull"]["type"] == "ingestion"
        assert (nodes["pull"]["source"], nodes["pull"]["table"]) == ("crm", "customers")
        assert nodes["pull"]["dependencies"] == ["clean"]


class TestEnvironments:
    def test_overrides_reach_every_section(self, tmp_path):
        root = _project(tmp_path)
        base, prod = _compile(root, "dev"), _compile(root, "prod")

        assert base["global_config"]["max_parallel_nodes"] == 4
        assert prod["global_config"]["max_parallel_nodes"] == 8
        assert prod["global_config"]["output_path"] == "s3://lake/prod"
        # dotted keys resolve dataset names that contain dots
        assert prod["output_config"]["silver.etl.orders"]["write_mode"] == "append"
        assert base["output_config"]["silver.etl.orders"]["write_mode"] == "overwrite"
        assert prod["nodes_config"]["clean"]["data_quality"]["quality_gate"]["max_errors"] == 1

    def test_sandbox_falls_back_to_its_base_environment(self, tmp_path):
        root = _project(tmp_path, project=PROJECT.replace("  prod:", "  sandbox:"))
        assert _compile(root, "sandbox_ana")["global_config"]["max_parallel_nodes"] == 8

    def test_an_override_is_validated_like_the_base(self, tmp_path):
        root = _project(tmp_path, project=PROJECT + "    settings.max_paralel_nodes: 2\n")
        with pytest.raises(ProjectConfigError, match="did you mean 'max_parallel_nodes'"):
            validate_project(root, "prod")


class TestErrorsSayWhere:
    def test_unknown_node_key_names_file_and_line(self, tmp_path):
        bad = PIPELINE.replace("    timeout_seconds: 60\n", "    timeout: 60\n")
        with pytest.raises(ProjectConfigError) as exc:
            validate_project(_project(tmp_path, pipeline=bad))
        assert "pipelines/etl.yaml:" in str(exc.value)
        assert "unknown key 'timeout' — did you mean 'timeout_seconds'?" in str(exc.value)

    def test_a_catalog_typo_gets_a_suggestion_too(self, tmp_path):
        root = _project(tmp_path, extra_catalog="typo.set.data:\n  format: csv\n  pth: x.csv\n")
        with pytest.raises(
            ProjectConfigError, match="unknown dataset key 'pth' — did you mean 'path'"
        ):
            validate_project(root)

    def test_unknown_dataset_is_reported_with_a_suggestion(self, tmp_path):
        bad = PIPELINE.replace("inputs: [silver.etl.orders]", "inputs: [silver.order]")
        with pytest.raises(ProjectConfigError, match="did you mean 'silver.etl.orders'"):
            validate_project(_project(tmp_path, pipeline=bad))

    def test_every_problem_is_reported_not_just_the_first(self, tmp_path):
        bad = PIPELINE.replace("inputs: [silver.etl.orders]", "inputs: [nope]").replace(
            "after: [clean]", "after: [clen]"
        )
        with pytest.raises(ProjectConfigError) as exc:
            validate_project(_project(tmp_path, pipeline=bad))
        assert len(exc.value.problems) == 2

    def test_node_names_are_unique_across_pipelines(self, tmp_path):
        root = _project(tmp_path)
        (root / "pipelines" / "other.yaml").write_text(
            "nodes:\n  clean:\n    run: m:f\n    outputs: []\n"
        )
        with pytest.raises(ProjectConfigError, match="also defined in pipeline"):
            validate_project(root)

    def test_two_writers_of_one_dataset_are_rejected(self, tmp_path):
        bad = PIPELINE.replace("outputs: [gold.sales.totals]", "outputs: [silver.etl.orders]")
        with pytest.raises(ProjectConfigError, match="written by both"):
            validate_project(_project(tmp_path, pipeline=bad))


class TestDetection:
    def test_root_is_found_directly_or_under_config(self, tmp_path):
        root = _project(tmp_path)
        assert find_project_root(root) == root
        nested = tmp_path / "wrapper"
        (nested / "config").mkdir(parents=True)
        (nested / "config" / "ducta.yaml").write_text(PROJECT)
        assert find_project_root(nested) == nested / "config"

    def test_a_manifest_without_version_2_is_not_a_project(self, tmp_path):
        (tmp_path / "ducta.yaml").write_text("project: {type: layered}\nlayers: {}\n")
        assert find_project_root(tmp_path) is None


def test_kind_defaults_to_transform_and_other_kinds_forbid_transform_keys():
    ok = PipelineFile.model_validate({"nodes": {"a": {"run": "m:f"}}})
    assert ok.nodes["a"].kind == "transform"
    with pytest.raises(Exception):
        PipelineFile.model_validate(
            {"nodes": {"a": {"kind": "ingest", "run": "m:f", "ingest": {}}}}
        )


def test_json_schema_covers_every_file_kind():
    schema = json_schema()
    assert set(schema["$defs"]) == {"project", "catalog", "pipeline", "profiles"}


class TestLoadProject:
    """`ducta.load_project`: the public way to get a project's Context from Python."""

    def test_finds_the_project_from_a_directory_inside_it(self, tmp_path):
        import ducta

        root = _project(tmp_path)
        ctx = ducta.load_project(root / "pipelines", env="prod")
        assert ctx.global_config["output_path"] == "s3://lake/prod"
        assert "etl" in ctx.pipelines_config

    def test_no_project_names_the_directory_and_the_way_to_create_one(self, tmp_path):
        import ducta
        from ducta.setting.exceptions import ConfigurationError

        with pytest.raises(ConfigurationError, match="ducta template"):
            ducta.load_project(tmp_path)


class TestWriteModeDefault:
    """A dataset without `write:` is overwritten, not appended to.

    The Context validates the engine documents with `OutputSchema`, whose
    `write_mode` defaulted to APPEND and was written back into the document —
    so every format-2 output without an explicit mode appended on each run,
    and re-running a pipeline duplicated its data. The writer, the format-2
    schema and the docs all say the default is overwrite.
    """

    def test_an_unset_mode_reaches_the_writer_unset(self, tmp_path):
        import ducta
        from ducta.gate.writers import SparkWriterMixin

        ctx = ducta.load_project(_project(tmp_path), env="dev")
        unset = [n for n, cfg in ctx.output_config.items() if "write_mode" not in cfg]
        assert unset, "the fixture needs an output without write:"
        assert SparkWriterMixin()._determine_write_mode(ctx.output_config[unset[0]]) == "overwrite"

    def test_an_explicit_mode_is_kept(self, tmp_path):
        import ducta

        ctx = ducta.load_project(_project(tmp_path), env="prod")
        assert ctx.output_config["silver.etl.orders"]["write_mode"] == "append"


class TestStreamNodes:
    """`stream:` is closed: run settings live in `streaming:`, and typos are errors."""

    @staticmethod
    def _stream_project(tmp_path, stream_yaml: str):
        (tmp_path / "pipelines").mkdir(parents=True, exist_ok=True)
        (tmp_path / "ducta.yaml").write_text(PROJECT)
        (tmp_path / "catalog.yaml").write_text("{}\n")
        (tmp_path / "pipelines" / "s.yaml").write_text(
            "type: streaming\nrequires_dates: false\nnodes:\n  n:\n    kind: stream\n"
            "    stream:\n" + "".join(f"      {line}\n" for line in stream_yaml.splitlines())
        )
        return tmp_path

    def test_streaming_settings_reach_the_block_the_engine_reads(self, tmp_path):
        root = self._stream_project(
            tmp_path,
            "input: {format: kafka, options: {subscribe: t}}\n"
            "output: {format: delta, path: out}\n"
            "streaming: {checkpoint_location: ck, trigger: 10s, output_mode: append}\n",
        )
        node = compile_project(validate_project(root, None))["nodes_config"]["n"]
        assert node["streaming"] == {
            "checkpoint_location": "ck",
            "trigger": {"type": "processing_time", "interval": "10 seconds"},
            "output_mode": "append",
        }
        assert "trigger" not in node and "checkpoint_location" not in node

    @pytest.mark.parametrize(
        "text, interval",
        [("5 minutes", "5 minutes"), ("2h", "2 hours"), ("30sec", "30 seconds")],
    )
    def test_trigger_shorthand(self, tmp_path, text, interval):
        root = self._stream_project(tmp_path, f"streaming: {{trigger: '{text}'}}\n")
        node = compile_project(validate_project(root, None))["nodes_config"]["n"]
        assert node["streaming"]["trigger"] == {"type": "processing_time", "interval": interval}

    def test_terminating_triggers_need_no_interval(self, tmp_path):
        root = self._stream_project(tmp_path, "streaming: {trigger: available_now}\n")
        node = compile_project(validate_project(root, None))["nodes_config"]["n"]
        assert node["streaming"]["trigger"] == {"type": "available_now"}

    def test_a_flat_run_setting_points_at_the_streaming_block(self, tmp_path):
        root = self._stream_project(tmp_path, "checkpoint_location: ck\n")
        with pytest.raises(ProjectConfigError, match="belongs in the node's 'streaming:' block"):
            validate_project(root, None)

    def test_a_run_setting_under_output_points_at_the_streaming_block(self, tmp_path):
        root = self._stream_project(tmp_path, "output: {format: delta, trigger: 5s}\n")
        with pytest.raises(ProjectConfigError, match="'streaming:' block"):
            validate_project(root, None)

    def test_a_typo_in_the_streaming_block_is_an_error_with_a_suggestion(self, tmp_path):
        root = self._stream_project(tmp_path, "streaming: {checkpoint_locaton: ck}\n")
        with pytest.raises(ProjectConfigError, match="did you mean 'checkpoint_location'"):
            validate_project(root, None)

    def test_a_bad_trigger_says_what_is_accepted(self, tmp_path):
        root = self._stream_project(tmp_path, "streaming: {trigger: soon}\n")
        with pytest.raises(ProjectConfigError, match="not an interval"):
            validate_project(root, None)
        root2 = self._stream_project(tmp_path / "b", "streaming: {trigger: {type: continuous}}\n")
        with pytest.raises(ProjectConfigError, match="needs an 'interval'"):
            validate_project(root2, None)

    def test_the_file_stream_schema_keeps_its_name_in_the_engine_document(self, tmp_path):
        root = self._stream_project(
            tmp_path,
            "input: {format: file_stream, file_format: json, schema: 'a STRING', "
            "options: {path: p}}\n",
        )
        node = compile_project(validate_project(root, None))["nodes_config"]["n"]
        assert node["input"]["schema"] == "a STRING"
        assert "schema_def" not in node["input"]

    def test_the_transform_is_a_name_or_key_module_params(self, tmp_path):
        root = self._stream_project(
            tmp_path, "transform: {key: clean, module: m, params: {x: 1}}\n"
        )
        node = compile_project(validate_project(root, None))["nodes_config"]["n"]
        assert node["function"] == {"key": "clean", "module": "m", "params": {"x": 1}}
