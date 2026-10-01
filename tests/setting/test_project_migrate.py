"""`ducta config migrate`: format 1 → format 2, verified equivalent per environment."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ducta.setting import project_migrate as pm
from ducta.setting.project_loader import compile_project, find_project_root, validate_project
from tests.format1 import format1_project


def _template(tmp_path: Path, kind: str = "medallion_basic") -> Path:
    return format1_project(tmp_path / "proj", kind)


def _yaml(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False))


def _read(path: Path):
    return yaml.safe_load(path.read_text())


@pytest.mark.parametrize("kind", ["medallion_basic", "streaming_basic"])
def test_both_templates_migrate_and_verify(tmp_path, kind):
    result = pm.migrate(_template(tmp_path, kind))
    assert result.environments  # dev, prod, sandbox were all verified
    assert "environments" not in result.project  # the scaffold's envs differ in nothing


def test_inferable_dependencies_disappear_and_contracts_move_to_the_catalog(tmp_path):
    result = pm.migrate(_template(tmp_path))
    nodes = result.pipelines["etl"]["nodes"]
    assert all("after" not in n for n in nodes.values())
    assert "checks" in result.catalog["source_data"]
    assert "input_checks" not in nodes["extract"]


def test_a_real_environment_difference_becomes_a_minimal_override(tmp_path):
    root = _template(tmp_path)
    env = _read(root / "environment.yaml")
    env["env_config"]["prod"]["input_config_path"] = "config/prod/input.yaml"
    _yaml(root / "environment.yaml", env)
    prod_input = _read(root / "config" / "input.yaml")
    prod_input["source_data"]["filepath"] = "s3://lake/prod/input.csv"
    _yaml(root / "config" / "prod" / "input.yaml", prod_input)
    _yaml(root / "config" / "prod" / "global_config.yaml", {"max_parallel_nodes": 16})

    result = pm.migrate(root)

    prod = result.project["environments"]["prod"]
    assert prod == {
        "settings": {"max_parallel_nodes": 16},
        "catalog": {"source_data": {"path": "s3://lake/prod/input.csv"}},
    }
    assert "dev" not in result.project.get("environments", {})


def test_inline_global_environments_become_overrides(tmp_path):
    root = _template(tmp_path)
    g = _read(root / "config" / "global_config.yaml")
    g["environments"] = {"prod": {"max_parallel_nodes": 32}}
    _yaml(root / "config" / "global_config.yaml", g)

    result = pm.migrate(root)
    assert result.project["environments"]["prod"]["settings"] == {"max_parallel_nodes": 32}


def test_written_project_loads_and_compiles_for_every_environment(tmp_path):
    root = _template(tmp_path)
    result = pm.migrate(root)
    out = tmp_path / "v2"
    pm.write_files(result, out)

    assert find_project_root(out) == out
    for env in ("dev", "prod", "sandbox"):
        docs = compile_project(validate_project(out, env))
        assert set(docs["nodes_config"]) == {"extract", "transform", "load"}
    header = (out / "ducta.yaml").read_text().splitlines()[0]
    assert header.startswith("# yaml-language-server: $schema=")
    assert (out / ".ducta" / "schema" / "pipeline.json").is_file()


def test_write_in_place_backs_up_format_1(tmp_path):
    root = _template(tmp_path)
    written, backup = pm.replace_in_place(pm.migrate(root), root)

    assert (root / "ducta.yaml").is_file()
    assert not (root / "environment.yaml").exists()
    assert (backup / "environment.yaml").is_file()
    assert (backup / "config" / "nodes.yaml").is_file()
    # the project's code is untouched
    assert (root / "pipelines" / "etl.py").is_file()
    assert find_project_root(root) == root


class TestRefusals:
    def test_a_node_shared_by_two_pipelines(self, tmp_path):
        root = _template(tmp_path)
        p = _read(root / "config" / "pipelines.yaml")
        p["again"] = {"nodes": ["extract"], "requires_dates": False}
        _yaml(root / "config" / "pipelines.yaml", p)
        with pytest.raises(pm.MigrationError, match="used by pipelines"):
            pm.migrate(root)

    def test_a_dataset_read_and_written_at_different_places(self, tmp_path):
        root = _template(tmp_path)
        i = _read(root / "config" / "input.yaml")
        i["bronze.etl.raw_data"]["filepath"] = "/somewhere/else"
        _yaml(root / "config" / "input.yaml", i)
        with pytest.raises(pm.MigrationError, match="one location per dataset"):
            pm.migrate(root)

    def test_an_unknown_node_key(self, tmp_path):
        root = _template(tmp_path)
        n = _read(root / "config" / "nodes.yaml")
        n["load"]["dependencie"] = ["transform"]
        _yaml(root / "config" / "nodes.yaml", n)
        with pytest.raises(pm.MigrationError, match="dependencie"):
            pm.migrate(root)

    def test_an_already_migrated_project(self, tmp_path):
        root = _template(tmp_path)
        pm.replace_in_place(pm.migrate(root), root)
        with pytest.raises(pm.MigrationError, match="already format 2"):
            pm.migrate(root)

    def test_any_behavioural_difference_aborts_before_writing(self, tmp_path, monkeypatch):
        """The safety net itself: if compiling the result diverges, nothing is written."""
        root = _template(tmp_path)
        real = pm.compile_project

        def lossy(project):
            docs = real(project)
            docs["nodes_config"]["transform"]["retry"] = 3
            return docs

        monkeypatch.setattr(pm, "compile_project", lossy)
        with pytest.raises(pm.MigrationError, match="would not behave the same"):
            pm.migrate(root)
        assert not (root / "ducta.yaml").exists()


def test_the_directory_convention_form_migrates(tmp_path):
    root = _template(tmp_path)
    (root / "environment.yaml").unlink()
    result = pm.migrate(root)
    assert set(result.pipelines) == {"etl"} and result.environments == []


def test_the_bundle_form_migrates(tmp_path):
    root = _template(tmp_path)
    bundle = {
        doc: _read(root / "config" / f"{name}.yaml")
        for doc, name in [
            ("global_config", "global_config"),
            ("pipelines_config", "pipelines"),
            ("nodes_config", "nodes"),
            ("input_config", "input"),
            ("output_config", "output"),
        ]
    }
    b = tmp_path / "bundle"
    _yaml(b / "config.yaml", bundle)
    assert set(pm.migrate(b).catalog) >= {"source_data", "gold.etl.final_output"}


def test_layered_projects_are_refused_with_guidance(tmp_path):
    (tmp_path / "ducta.yaml").write_text(
        "project: {type: layered}\nlayers:\n  bronze: {path: bronze}\n"
    )
    (tmp_path / "bronze" / "config").mkdir(parents=True)
    with pytest.raises(pm.MigrationError, match="layered"):
        pm.migrate(tmp_path)


def test_an_output_without_write_mode_keeps_appending(tmp_path):
    """Format 1 appended when write_mode was unset; format 2 overwrites.
    migrate writes the old behaviour out explicitly instead of changing it."""
    root = _template(tmp_path)
    output = root / "config" / "output.yaml"
    docs = _read(output)
    name = next(iter(docs))
    docs[name].pop("write_mode", None)
    _yaml(output, docs)

    result = pm.migrate(root)  # still verified equivalent

    assert result.catalog[name]["write"]["mode"] == "append"
