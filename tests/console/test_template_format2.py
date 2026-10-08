"""Templates generate configuration format 2 by default (phase 6)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ducta.console.template import ConfigFormat, TemplateError, TemplateGenerator, TemplateType
from ducta.setting.project_loader import compile_project, find_project_root, validate_project


def _generate(tmp_path: Path, kind: str, fmt=ConfigFormat.YAML, **kw) -> Path:
    root = tmp_path / "p"
    TemplateGenerator(root, fmt).generate_project(TemplateType(kind), "p", **kw)
    return root


_KINDS = ["medallion_basic", "streaming_basic", "ml_basic", "ml_scoring", "hybrid_basic"]


@pytest.mark.parametrize("kind", _KINDS)
def test_default_is_format_2_and_compiles_in_every_environment(tmp_path, kind):
    root = _generate(tmp_path, kind)
    assert find_project_root(root) == root
    assert not (root / "environment.yaml").exists()
    assert not (root / "config").exists()
    for env in ("dev", "prod", "sandbox"):
        compile_project(validate_project(root, env))
    assert (root / ".ducta" / "schema" / "project.json").is_file()


def test_generated_text_points_at_the_format_2_files(tmp_path):
    root = _generate(tmp_path, "medallion_basic")
    readme = (root / "README.md").read_text()
    assert "catalog.yaml" in readme and "pipelines/etl.yaml" in readme
    assert "config/nodes" not in readme
    for code in (root / "pipelines").rglob("*.py"):
        assert "config/nodes.yaml" not in code.read_text(), code


def test_streaming_readme_describes_the_project_as_generated(tmp_path):
    readme = (_generate(tmp_path, "streaming_basic") / "README.md").read_text()
    assert "ducta stream run --pipeline events_stream" in readme
    for stale in ("environment.yaml", "global_config", "function: {", "dependencies:"):
        assert stale not in readme, stale


def test_an_unknown_format_is_refused(tmp_path):
    with pytest.raises(TemplateError):
        TemplateGenerator(tmp_path / "p", ConfigFormat.DSL)


@pytest.mark.parametrize("fmt", [ConfigFormat.TOML, ConfigFormat.JSON])
@pytest.mark.parametrize("kind", _KINDS)
def test_toml_and_json_are_the_same_project(tmp_path, kind, fmt):
    yaml_root = _generate(tmp_path / "y", kind)
    root = tmp_path / "other"
    TemplateGenerator(root, fmt).generate_project(TemplateType(kind), "p")
    ext = fmt.value
    assert (root / f"ducta.{ext}").is_file() and not (root / "ducta.yaml").exists()
    assert not list((root / "pipelines").glob("*.yaml"))
    assert find_project_root(root) == root
    for env in (None, "dev", "prod"):
        assert compile_project(validate_project(root, env)) == compile_project(
            validate_project(yaml_root, env)
        )


@pytest.mark.parametrize("fmt", [ConfigFormat.TOML, ConfigFormat.JSON])
def test_text_points_at_the_files_that_exist(tmp_path, fmt):
    root = tmp_path / "p"
    TemplateGenerator(root, fmt).generate_project(TemplateType.MEDALLION_BASIC, "p")
    ext = fmt.value
    readme = (root / "README.md").read_text()
    assert f"catalog.{ext}" in readme and f"pipelines/etl.{ext}" in readme
    assert "ducta.yaml" not in readme and "catalog.yaml" not in readme
    assert "pipelines/etl.yaml" not in (root / "pipelines" / "etl.py").read_text()


def test_toml_and_json_name_their_schema(tmp_path):
    toml_root = tmp_path / "t"
    TemplateGenerator(toml_root, ConfigFormat.TOML).generate_project(
        TemplateType.MEDALLION_BASIC, "p"
    )
    assert (toml_root / "ducta.toml").read_text().startswith("#:schema .ducta/schema/project.json")
    json_root = tmp_path / "j"
    TemplateGenerator(json_root, ConfigFormat.JSON).generate_project(
        TemplateType.MEDALLION_BASIC, "p"
    )
    first = (json_root / "ducta.json").read_text().splitlines()[1]
    assert '"$schema": ".ducta/schema/project.json"' in first


def test_the_streaming_cli_loads_a_format_2_project(tmp_path, monkeypatch):
    from ducta.console.execution import _load_streaming_context

    root = _generate(tmp_path, "streaming_basic")
    assert _load_streaming_context(str(root / "ducta.yaml"), "dev").project_format == 2
    monkeypatch.chdir(root)
    assert "events_stream" in _load_streaming_context(None, "dev").pipelines


_KINDS = ["medallion_basic", "streaming_basic", "ml_basic", "ml_scoring", "hybrid_basic"]


@pytest.mark.parametrize("kind", _KINDS)
def test_generated_files_are_commented_and_carry_their_schema(tmp_path, kind):
    root = _generate(tmp_path, kind)
    schema_headers = {
        "ducta.yaml": "$schema=.ducta/schema/project.json",
        "catalog.yaml": "$schema=.ducta/schema/catalog.json",
    }
    for name, header in schema_headers.items():
        text = (root / name).read_text()
        assert header in text.splitlines()[0], name
        assert text.count("\n#") > 2, f"{name} should explain itself"
    for pipeline in (root / "pipelines").glob("*.yaml"):
        assert "$schema=../.ducta/schema/pipeline.json" in pipeline.read_text().splitlines()[0]


def test_environments_state_only_what_differs(tmp_path):
    root = _generate(tmp_path, "medallion_basic")
    base = compile_project(validate_project(root, None))["global_config"]
    dev = compile_project(validate_project(root, "dev"))["global_config"]
    prod = compile_project(validate_project(root, "prod"))["global_config"]
    assert (base["max_parallel_nodes"], dev["max_parallel_nodes"]) == (4, 1)
    assert prod["max_parallel_nodes"] == 8
    assert dev["log_level"] == "DEBUG"


def test_developer_sandboxes_inherit_sandbox_and_are_named_in_the_project(tmp_path):
    root = _generate(tmp_path, "medallion_basic", developer_sandboxes=["alice", "bob"])
    assert "sandbox_alice, sandbox_bob" in (root / "ducta.yaml").read_text()
    # No file or entry is needed: sandbox_<dev> resolves to the `sandbox` overrides.
    compile_project(validate_project(root, "sandbox_alice"))


def test_evidence_level_is_written_into_the_settings(tmp_path):
    root = _generate(tmp_path, "streaming_basic", evidence_level="signed")
    docs = compile_project(validate_project(root, "dev"))
    assert docs["global_config"]["evidence_level"] == "signed"


def test_run_output_is_not_committed(tmp_path):
    ignored = (_generate(tmp_path, "medallion_basic") / ".gitignore").read_text()
    for env in ("dev/", "sandbox/", "prod/"):
        assert f"data/{env}" in ignored
    assert "!data/input.csv" in ignored


@pytest.mark.parametrize("kind", _KINDS)
def test_no_marker_is_left_and_arrow_is_off_for_jdk_21(tmp_path, kind):
    root = _generate(tmp_path, kind)
    for path in list(root.glob("*.yaml")) + list((root / "pipelines").glob("*.yaml")):
        assert "@@" not in path.read_text(), path.name
    spark = compile_project(validate_project(root, "dev"))["global_config"]["spark_config"]
    assert spark["spark.sql.execution.arrow.pyspark.enabled"] == "false"
