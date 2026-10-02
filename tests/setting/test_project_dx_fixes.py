"""Configuration mistakes are caught early, and reported where they were made.

Four things that used to slip through or point the wrong way: a dependency cycle only
the CLI noticed, an environment override whose error named the pipeline file, an
engine-schema failure shown as a raw pydantic dump, and template placeholders that
could not name a node.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ducta.setting.project_loader import (
    ProjectConfigError,
    _engine_problems,
    compile_project,
    validate_project,
)

PROJECT = "version: 2\nproject: p\npaths: {input: d, output: o}\n"
CATALOG = (
    "raw: {format: csv, path: x.csv}\nsilver.x.a: {format: delta}\nsilver.x.b: {format: delta}\n"
)
PIPELINE = """\
requires_dates: false
nodes:
  first:
    run: m:first
    inputs: {raw: raw}
    outputs: [silver.x.a]
  second:
    run: m:second
    inputs: {a: silver.x.a}
    outputs: [silver.x.b]
"""


def _project(root: Path, ducta: str = "", pipeline: str = PIPELINE, catalog: str = CATALOG) -> Path:
    (root / "pipelines").mkdir(parents=True)
    (root / "ducta.yaml").write_text(PROJECT + ducta)
    (root / "catalog.yaml").write_text(catalog)
    (root / "pipelines" / "p.yaml").write_text(pipeline)
    return root


def _problems(root: Path, env=None) -> str:
    with pytest.raises(ProjectConfigError) as exc:
        validate_project(root, env)
    return "\n".join(exc.value.problems)


class TestCycles:
    def test_a_cycle_through_after_is_an_error_when_the_project_loads(self, tmp_path):
        pipeline = PIPELINE.replace("  first:\n", "  first:\n    after: [second]\n")
        text = _problems(_project(tmp_path, pipeline=pipeline))
        assert "nodes wait for each other" in text
        assert "first" in text and "second" in text and "pipelines/p.yaml" in text

    def test_a_cycle_through_the_data_is_found_too(self, tmp_path):
        pipeline = """\
requires_dates: false
nodes:
  first:
    run: m:first
    inputs: {b: silver.x.b}
    outputs: [silver.x.a]
  second:
    run: m:second
    inputs: {a: silver.x.a}
    outputs: [silver.x.b]
"""
        assert "nodes wait for each other" in _problems(_project(tmp_path, pipeline=pipeline))

    def test_reading_what_you_write_is_not_a_cycle(self, tmp_path):
        pipeline = PIPELINE.replace(
            "inputs: {raw: raw}\n    outputs: [silver.x.a]",
            "inputs: {raw: raw, mine: silver.x.a}\n    outputs: [silver.x.a]",
        )
        validate_project(_project(tmp_path, pipeline=pipeline))

    def test_pipelines_that_depend_on_each_other(self, tmp_path):
        root = _project(tmp_path, pipeline="depends_on: [q]\n" + PIPELINE)
        other = PIPELINE.replace("first", "third").replace("second", "fourth")
        other = other.replace("silver.x.a", "silver.x.c").replace("silver.x.b", "silver.x.d")
        (root / "pipelines" / "q.yaml").write_text("depends_on: [p]\n" + other)
        (root / "catalog.yaml").write_text(
            CATALOG + "silver.x.c: {format: delta}\nsilver.x.d: {format: delta}\n"
        )
        assert "pipelines depend on each other" in _problems(root)


class TestOverridesAreLocatedAtTheOverride:
    ENV = "environments:\n  prod:\n    pipelines.p.nodes.first.{key}: 5\n"

    def test_a_typo_in_an_override_names_ducta_yaml(self, tmp_path):
        root = _project(tmp_path, self.ENV.format(key="retyr"))
        text = _problems(root, "prod")
        assert "did you mean 'retry'" in text
        assert text.startswith("ducta.yaml:"), text

    def test_an_override_of_a_node_that_does_not_exist(self, tmp_path):
        ducta = "environments:\n  prod:\n    pipelines.p.nodes.frist.retry: 5\n"
        text = _problems(_project(tmp_path, ducta), "prod")
        assert text.startswith("ducta.yaml:")
        assert "there is no node 'frist' in pipeline 'p' — did you mean 'first'" in text

    def test_an_override_of_a_pipeline_or_a_dataset_that_does_not_exist(self, tmp_path):
        ducta = "environments:\n  prod:\n    pipelines.zzz.retry: 1\n    catalog.nope.format: csv\n"
        text = _problems(_project(tmp_path, ducta), "prod")
        assert "there is no pipeline 'zzz'" in text and "there is no dataset 'nope'" in text

    def test_a_valid_override_still_applies(self, tmp_path):
        root = _project(tmp_path, self.ENV.format(key="retry"))
        project = validate_project(root, "prod")
        assert project.pipelines["p"].nodes["first"].retry == 5

    def test_an_error_in_an_untouched_key_still_names_its_own_file(self, tmp_path):
        pipeline = PIPELINE.replace("run: m:second", "runn: m:second")
        ducta = self.ENV.format(key="retry")
        text = _problems(_project(tmp_path, ducta, pipeline), "prod")
        assert "pipelines/p.yaml" in text and "ducta.yaml" not in text

    def test_a_settings_override_error_names_ducta_yaml(self, tmp_path):
        ducta = "environments:\n  prod:\n    settings: {max_paralell_nodes: 2}\n"
        assert _problems(_project(tmp_path, ducta), "prod").startswith("ducta.yaml:")


class TestTheEngineSchemaIsNotShownRaw:
    def test_a_pipeline_without_nodes_is_a_located_message_when_it_is_loaded_to_run(self, tmp_path):
        from ducta.setting.project_loader import load_project_v2

        root = _project(tmp_path, pipeline="requires_dates: false\n")
        validate_project(root)  # the API creates a pipeline before its first node
        with pytest.raises(ProjectConfigError) as exc:
            load_project_v2(root, None)
        text = "\n".join(exc.value.problems)
        assert "pipelines/p.yaml" in text and "pipeline 'p' has no nodes" in text
        assert "pydantic" not in text and "ConfigSchema" not in text

    def test_engine_errors_are_mapped_back_to_the_file(self, tmp_path):
        from pydantic import ValidationError

        from ducta.setting.schemas import ConfigSchema

        root = _project(tmp_path)
        project = validate_project(root)
        docs = compile_project(project)
        docs["nodes_config"]["second"]["retry"] = "often"
        with pytest.raises(ValidationError) as exc:
            ConfigSchema(**docs)
        problems = _engine_problems(root, project, exc.value)
        assert problems and "pipelines/p.yaml" in problems[0] and "node 'second'" in problems[0]
        assert "rejected by the engine's own schema" in problems[0]

    def test_something_that_is_not_a_schema_error_is_left_alone(self, tmp_path):
        root = _project(tmp_path)
        assert _engine_problems(root, validate_project(root), RuntimeError("boom")) is None


class TestTemplatesNameThings:
    TEMPLATE = """\
params: {layer: <required>, table: <required>}
requires_dates: false
nodes:
  ${params.layer}.clean_${params.table}:
    run: m:clean
    inputs:
      raw: ${params.table}_raw
    outputs:
      - ${params.layer}.x.${params.table}
"""

    def _root(self, tmp_path, params: str, catalog: str, template: str | None = None) -> Path:
        root = _project(
            tmp_path, pipeline="extends: templates/clean\nparams: " + params + "\n", catalog=catalog
        )
        (root / "templates").mkdir()
        (root / "templates" / "clean.yaml").write_text(template or self.TEMPLATE)
        return root

    def test_a_node_name_comes_from_the_parameters(self, tmp_path):
        catalog = "orders_raw: {format: csv, path: o.csv}\nsilver.x.orders: {format: delta}\n"
        root = self._root(tmp_path, "{layer: silver, table: orders}", catalog)
        project = validate_project(root)
        assert list(project.pipelines["p"].nodes) == ["silver.clean_orders"]

    def test_one_template_serves_several_copies_with_different_names(self, tmp_path):
        catalog = (
            "orders_raw: {format: csv, path: o.csv}\nsilver.x.orders: {format: delta}\n"
            "items_raw: {format: csv, path: i.csv}\nsilver.x.items: {format: delta}\n"
        )
        root = self._root(tmp_path, "{layer: silver, table: orders}", catalog)
        (root / "pipelines" / "q.yaml").write_text(
            "extends: templates/clean\nparams: {layer: silver, table: items}\n"
        )
        project = validate_project(root)
        assert list(project.pipelines["q"].nodes) == ["silver.clean_items"]
        assert list(project.pipelines["p"].nodes) == ["silver.clean_orders"]

    def test_a_list_cannot_be_part_of_a_name(self, tmp_path):
        text = _problems(
            self._root(
                tmp_path, "{layer: [a, b], table: orders}", "orders_raw: {format: csv, path: o}\n"
            )
        )
        assert "must be a plain value" in text

    def test_a_placeholder_in_a_key_must_be_declared(self, tmp_path):
        template = self.TEMPLATE.replace(
            "params: {layer: <required>, table: <required>}", "params: {table: <required>}"
        )
        text = _problems(
            self._root(
                tmp_path, "{table: orders}", "orders_raw: {format: csv, path: o}\n", template
            )
        )
        assert "uses ${params.layer}, which it does not declare" in text

    def test_two_keys_that_become_one_are_an_error(self, tmp_path):
        template = """\
params: {a: <required>}
requires_dates: false
nodes:
  ${params.a}:
    run: m:one
    inputs: {raw: raw}
    outputs: [silver.x.a]
  same:
    run: m:two
    inputs: {raw: raw}
    outputs: [silver.x.b]
"""
        text = _problems(self._root(tmp_path, "{a: same}", CATALOG, template))
        assert "both become 'same'" in text
