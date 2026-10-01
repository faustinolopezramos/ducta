"""`show`, `explain`, `diff` and `convert`: what a project resolves to, and why."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from ducta.setting import project_inspect as inspect
from ducta.setting.project_loader import ProjectConfigError, compile_project, validate_project

PROJECT = """\
version: 2
project: demo
paths: {input: data, output: out}
settings: {max_parallel_nodes: 4, log_level: INFO}
defaults:
  node: {retry: 2}
  catalog: {"silver.*": {format: parquet}}
environments:
  dev:
    settings: {max_parallel_nodes: 1}
  prod:
    settings: {max_parallel_nodes: 8}
    pipelines.etl.nodes.b.retry: 5
"""

CATALOG = """\
raw: {format: csv, path: data/raw.csv}
silver.x.a: {description: first}
silver.x.b: {format: delta}
unrelated: {format: csv, path: data/other.csv}
"""

TEMPLATE = """\
params: {who: null}
description: "Pipeline for ${params.who}"
nodes:
  a: {run: m:f, inputs: [raw], outputs: [silver.x.a]}
"""

ETL = """\
extends: templates/base
params: {who: ana}
nodes:
  b: {run: m:g, inputs: [silver.x.a], outputs: [silver.x.b]}
"""


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / "pipelines").mkdir()
    (tmp_path / "templates").mkdir()
    (tmp_path / "ducta.yaml").write_text(PROJECT)
    (tmp_path / "catalog.yaml").write_text(CATALOG)
    (tmp_path / "templates" / "base.yaml").write_text(TEMPLATE)
    (tmp_path / "pipelines" / "etl.yaml").write_text(ETL)
    return tmp_path


class TestShow:
    def test_it_is_the_project_for_that_environment(self, root):
        tree = inspect.resolved_tree(root, "prod")
        assert tree["settings"]["max_parallel_nodes"] == 8
        assert tree["pipelines"]["etl"]["nodes"]["b"]["retry"] == 5

    def test_templates_and_defaults_are_already_applied(self, root):
        etl = inspect.resolved_tree(root, None)["pipelines"]["etl"]
        assert etl["description"] == "Pipeline for ana"
        assert etl["nodes"]["a"]["retry"] == 2
        assert inspect.resolved_tree(root, None)["catalog"]["silver.x.a"]["format"] == "parquet"

    def test_consumed_keys_are_not_shown(self, root):
        tree = inspect.resolved_tree(root, None)
        assert "defaults" not in tree and "environments" not in tree
        etl = tree["pipelines"]["etl"]
        assert not {"extends", "params", "defaults"} & set(etl)

    def test_one_pipeline_brings_only_its_datasets(self, root):
        tree = inspect.resolved_tree(root, None, "etl")
        assert set(tree["catalog"]) == {"raw", "silver.x.a", "silver.x.b"}

    def test_an_unknown_pipeline_lists_the_known_ones(self, root):
        with pytest.raises(ProjectConfigError, match="defined: etl"):
            inspect.resolved_tree(root, None, "nope")

    @pytest.mark.parametrize("fmt", ["yaml", "toml", "json"])
    def test_every_format_round_trips(self, root, fmt):
        import tomllib

        tree = inspect.resolved_tree(root, "prod")
        text = inspect.dump(tree, fmt)
        back = {"yaml": yaml.safe_load, "toml": tomllib.loads, "json": json.loads}[fmt](text)
        assert back["settings"] == tree["settings"]


class TestExplain:
    def test_a_value_set_in_the_file(self, root):
        ex = inspect.explain(root, "settings.log_level", None)
        assert ex.found and ex.value == "INFO"
        assert [(layer.name, layer.value) for layer in ex.layers] == [("file", "INFO")]
        assert ex.layers[0].at == "ducta.yaml:4"

    def test_an_environment_override_after_the_file_value(self, root):
        ex = inspect.explain(root, "settings.max_parallel_nodes", "prod")
        assert [(layer.name, layer.value) for layer in ex.layers] == [
            ("file", 4),
            ("environments.prod", 8),
        ]
        assert ex.layers[0].at == "ducta.yaml:4" and ex.layers[1].at == "ducta.yaml:12"

    def test_a_dotted_override_key_is_located_too(self, root):
        ex = inspect.explain(root, "pipelines.etl.nodes.b.retry", "prod")
        assert ex.layers[-1].name == "environments.prod" and ex.layers[-1].value == 5
        assert ex.layers[-1].at == "ducta.yaml:13"

    def test_an_inherited_default_names_defaults(self, root):
        ex = inspect.explain(root, "pipelines.etl.nodes.a.retry", None)
        assert [(layer.name, layer.value) for layer in ex.layers] == [("defaults", 2)]

    def test_a_catalog_default_names_defaults(self, root):
        ex = inspect.explain(root, "catalog.silver.x.a.format", None)
        assert ex.value == "parquet" and ex.layers[-1].name == "defaults"

    def test_a_dataset_that_sets_its_own_beats_the_default(self, root):
        ex = inspect.explain(root, "catalog.silver.x.b.format", None)
        assert ex.value == "delta"
        assert [layer.name for layer in ex.layers] == ["file"]
        assert ex.layers[0].at == "catalog.yaml:3"

    def test_a_value_from_a_template_names_the_template(self, root):
        ex = inspect.explain(root, "pipelines.etl.description", None)
        assert ex.layers[0].name == "template templates/base"
        assert ex.value == "Pipeline for ana"

    def test_a_key_that_is_not_set(self, root):
        ex = inspect.explain(root, "settings.nope", None)
        assert not ex.found and ex.layers == []

    def test_dotted_names_resolve_to_the_longest_key(self, root):
        ex = inspect.explain(root, "catalog.silver.x.b.format", None)
        assert ex.path == ["catalog", "silver.x.b", "format"]


class TestDiff:
    def test_it_lists_every_leaf_that_differs(self, root):
        changes = inspect.diff_trees(
            inspect.resolved_tree(root, "dev"), inspect.resolved_tree(root, "prod")
        )
        assert ("settings.max_parallel_nodes", 1, 8) in changes
        assert ("pipelines.etl.nodes.b.retry", 2, 5) in changes
        assert all(before != after for _, before, after in changes)

    def test_the_same_environment_differs_in_nothing(self, root):
        tree = inspect.resolved_tree(root, "dev")
        assert inspect.diff_trees(tree, tree) == []

    def test_a_key_in_only_one_side_is_missing_in_the_other(self):
        (change,) = inspect.diff_trees({"a": {"b": 1, "c": 2}}, {"a": {"c": 2}})
        assert change == ("a.b", 1, inspect.MISSING)


class TestConvert:
    @pytest.mark.parametrize("fmt", ["toml", "json", "yaml"])
    def test_the_converted_project_resolves_the_same(self, root, tmp_path, fmt):
        out = tmp_path / "out"
        written = inspect.convert_project(root, out, fmt)
        assert all(p.suffix == f".{fmt}" for p in written)
        for env in (None, "dev", "prod"):
            assert compile_project(validate_project(out, env)) == compile_project(
                validate_project(root, env)
            )

    def test_templates_come_along(self, root, tmp_path):
        inspect.convert_project(root, tmp_path / "out", "toml")
        assert (tmp_path / "out" / "templates" / "base.toml").is_file()

    def test_the_converted_files_name_their_schema(self, root, tmp_path):
        inspect.convert_project(root, tmp_path / "out", "toml")
        assert (
            (tmp_path / "out" / "pipelines" / "etl.toml")
            .read_text()
            .startswith("#:schema ../.ducta/schema/pipeline.json")
        )
        assert (tmp_path / "out" / ".ducta" / "schema" / "project.json").is_file()

    def test_it_refuses_a_directory_that_is_not_empty(self, root, tmp_path):
        out = tmp_path / "out"
        out.mkdir()
        (out / "keep.txt").write_text("x")
        with pytest.raises(ProjectConfigError, match="not empty"):
            inspect.convert_project(root, out, "json")
