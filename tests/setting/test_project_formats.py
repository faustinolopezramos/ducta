"""A project is the same project in YAML, TOML or JSON, and errors say where."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import tomli_w
import yaml

from ducta.console.template import TemplateGenerator, TemplateType
from ducta.setting import project_files as pf
from ducta.setting.project_loader import (
    ProjectConfigError,
    compile_project,
    find_project_root,
    project_file,
    read_project,
    validate_project,
)

_KINDS = ["medallion_basic", "streaming_basic", "ml_basic", "hybrid_basic"]


def _convert(source: Path, target: Path, fmt: str) -> Path:
    """The same project with every YAML file rewritten as ``fmt`` (``toml`` or ``json``)."""
    for path in source.rglob("*.yaml"):
        if ".ducta" in path.parts:
            continue
        data = yaml.safe_load(path.read_text()) or {}
        out = target / path.relative_to(source).with_suffix(f".{fmt}")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(tomli_w.dumps(data) if fmt == "toml" else json.dumps(data, indent=2) + "\n")
    return target


@pytest.fixture(params=_KINDS)
def trio(request, tmp_path):
    yaml_root = tmp_path / "yaml"
    TemplateGenerator(yaml_root).generate_project(TemplateType(request.param), "p")
    return {
        "yaml": yaml_root,
        "toml": _convert(yaml_root, tmp_path / "toml", "toml"),
        "json": _convert(yaml_root, tmp_path / "json", "json"),
    }


class TestSameProject:
    @pytest.mark.parametrize("env", [None, "dev", "sandbox", "prod"])
    def test_every_format_compiles_to_the_same_engine_documents(self, trio, env):
        expected = compile_project(validate_project(trio["yaml"], env))
        for fmt in ("toml", "json"):
            assert compile_project(validate_project(trio[fmt], env)) == expected, fmt

    def test_each_is_discovered_as_a_project(self, trio):
        for root in trio.values():
            assert find_project_root(root) == root
        assert project_file(trio["toml"]).name == "ducta.toml"
        assert project_file(trio["json"]).name == "ducta.json"

    def test_the_pipelines_are_found_whatever_their_format(self, trio):
        names = {fmt: set(read_project(root).pipelines) for fmt, root in trio.items()}
        assert names["toml"] == names["json"] == names["yaml"]


class TestOneFilePerRole:
    def test_two_formats_of_the_same_file_are_an_error_not_a_choice(self, trio):
        root = trio["yaml"]
        (root / "ducta.toml").write_text(
            tomli_w.dumps(yaml.safe_load((root / "ducta.yaml").read_text()))
        )
        with pytest.raises(
            ProjectConfigError, match="ducta.yaml and ducta.toml: a project keeps one"
        ):
            validate_project(root)

    def test_two_pipelines_with_one_name_are_an_error_across_formats(self, trio):
        root = trio["yaml"]
        first = next((root / "pipelines").glob("*.yaml"))
        (root / "pipelines" / f"{first.stem}.json").write_text("{}")
        with pytest.raises(ProjectConfigError, match="already defined"):
            validate_project(root)


def _project(root: Path, fmt: str, project: dict, pipeline: dict, catalog: dict | None = None):
    def dump(data):
        return tomli_w.dumps(data) if fmt == "toml" else json.dumps(data, indent=2)

    (root / "pipelines").mkdir(parents=True)
    (root / f"ducta.{fmt}").write_text(dump(project))
    (root / f"catalog.{fmt}").write_text(
        dump(catalog or {"raw": {"format": "parquet", "path": "p"}})
    )
    (root / "pipelines" / f"p.{fmt}").write_text(dump(pipeline))
    return root


_PROJECT = {"version": 2, "project": "p", "paths": {"input": "d", "output": "o"}}
_NODES = {"nodes": {"a": {"run": "m:f", "inputs": ["raw"], "outputs": ["silver.x.a"]}}}
_CATALOG = {"raw": {"format": "parquet", "path": "p"}, "silver.x.a": {"format": "parquet"}}


@pytest.mark.parametrize("fmt", ["toml", "json"])
class TestErrorsAreLocated:
    def test_an_unknown_key_names_its_file_and_a_suggestion(self, tmp_path, fmt):
        pipeline = {"nodes": {"a": {**_NODES["nodes"]["a"], "retyr": 2}}}
        root = _project(tmp_path, fmt, _PROJECT, pipeline, _CATALOG)
        with pytest.raises(ProjectConfigError) as exc:
            validate_project(root)
        assert f"pipelines/p.{fmt}:" in str(exc.value)
        assert "did you mean 'retry'" in str(exc.value)

    def test_the_line_is_the_one_the_key_is_on(self, tmp_path, fmt):
        pipeline = {"nodes": {"a": {**_NODES["nodes"]["a"], "retyr": 2}}}
        root = _project(tmp_path, fmt, _PROJECT, pipeline, _CATALOG)
        lines = (root / "pipelines" / f"p.{fmt}").read_text().splitlines()
        on = next(i for i, line in enumerate(lines, 1) if "retyr" in line)
        with pytest.raises(ProjectConfigError, match=rf"p\.{fmt}:{on} "):
            validate_project(root)

    def test_a_syntax_error_names_the_format(self, tmp_path, fmt):
        root = _project(tmp_path, fmt, _PROJECT, _NODES, _CATALOG)
        (root / "pipelines" / f"p.{fmt}").write_text("{ broken" if fmt == "json" else "a = = 1\n")
        with pytest.raises(ProjectConfigError, match=f"not valid {fmt.upper()}"):
            validate_project(root)

    def test_a_reference_to_a_missing_dataset_is_located(self, tmp_path, fmt):
        pipeline = {"nodes": {"a": {**_NODES["nodes"]["a"], "inputs": ["nope"]}}}
        root = _project(tmp_path, fmt, _PROJECT, pipeline, _CATALOG)
        with pytest.raises(ProjectConfigError, match=rf"p\.{fmt}:\d+ .*nope"):
            validate_project(root)


class TestPositions:
    def test_toml_tables_arrays_and_quoted_names(self, tmp_path):
        text = (
            'version = 2\nproject = "p"\n\n[paths]\ninput = "d"\noutput = "o"\n\n'
            '["silver.x.a"]\nformat = "parquet"\n\n[environments.prod.settings]\nmax_parallel_nodes = 8\n'
        )
        path = tmp_path / "ducta.toml"
        path.write_text(text)
        where: dict = {}
        pf.index(path, text, ("project",), where, "ducta.toml")
        assert where[("project", "paths", "output")] == "ducta.toml:6"
        assert where[("project", "silver.x.a", "format")] == "ducta.toml:9"
        assert (
            where[("project", "environments", "prod", "settings", "max_parallel_nodes")]
            == "ducta.toml:12"
        )

    def test_toml_multiline_strings_do_not_confuse_the_scan(self, tmp_path):
        text = 'a = """\nfake = 1\n"""\nb = 2\n'
        path = tmp_path / "x.toml"
        path.write_text(text)
        where: dict = {}
        pf.index(path, text, (), where, "x.toml")
        assert where[("b",)] == "x.toml:4"
        assert ("fake",) not in where

    def test_json_objects_and_array_items(self, tmp_path):
        text = '{\n  "a": {\n    "b": [\n      1,\n      {"c": 2}\n    ]\n  }\n}\n'
        path = tmp_path / "x.json"
        path.write_text(text)
        where: dict = {}
        pf.index(path, text, ("p",), where, "x.json")
        assert where[("p", "a")] == "x.json:2"
        assert where[("p", "a", "b", "1")] == "x.json:5"
        assert where[("p", "a", "b", "1", "c")] == "x.json:5"

    def test_a_json_schema_key_is_ignored(self, tmp_path):
        path = tmp_path / "ducta.json"
        path.write_text('{"$schema": ".ducta/schema/project.json", "version": 2}')
        assert pf.load(path) == {"version": 2}


class TestTemplatesAndDefaultsInOtherFormats:
    def test_extends_finds_a_toml_template(self, tmp_path):
        (tmp_path / "pipelines").mkdir()
        (tmp_path / "templates").mkdir()
        (tmp_path / "ducta.toml").write_text(tomli_w.dumps(_PROJECT))
        (tmp_path / "catalog.toml").write_text(tomli_w.dumps(_CATALOG))
        (tmp_path / "templates" / "t.toml").write_text(
            tomli_w.dumps({"params": {"who": "x"}, **_NODES, "description": "for ${params.who}"})
        )
        (tmp_path / "pipelines" / "p.toml").write_text(
            tomli_w.dumps({"extends": "templates/t", "params": {"who": "ana"}})
        )
        docs = compile_project(validate_project(tmp_path))
        assert docs["pipelines_config"]["p"]["description"] == "for ana"
