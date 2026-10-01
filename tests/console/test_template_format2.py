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


@pytest.mark.parametrize("kind", ["medallion_basic", "streaming_basic"])
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


def test_only_yaml_is_generated(tmp_path):
    with pytest.raises(TemplateError):
        TemplateGenerator(tmp_path / "p", ConfigFormat.JSON)


def test_the_streaming_cli_loads_a_format_2_project(tmp_path, monkeypatch):
    from ducta.console.execution import _load_streaming_context

    root = _generate(tmp_path, "streaming_basic")
    assert _load_streaming_context(str(root / "ducta.yaml"), "dev").project_format == 2
    monkeypatch.chdir(root)
    assert "events_stream" in _load_streaming_context(None, "dev").pipelines
