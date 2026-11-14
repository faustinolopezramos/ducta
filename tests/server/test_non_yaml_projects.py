"""Projects written in TOML or JSON: what reads ``ducta.*`` finds the real file, and the
web app, which edits YAML only, refuses instead of writing a second ``ducta.yaml``."""

from __future__ import annotations

import contextlib
import io
from pathlib import Path

import pytest

from ducta.ai.config import AIConfig
from ducta.ai.errors import AIPolicyError

REMOTE = AIConfig(provider="openai", model="gpt", base_url="https://api.openai.com/v1")
LOCAL = AIConfig(provider="ollama", model="m", base_url="http://localhost:11434/v1")


def _project(tmp_path: Path, fmt: str) -> Path:
    from ducta.console.template import TemplateCommand

    root = tmp_path / "projects" / "shop"
    with contextlib.redirect_stdout(io.StringIO()):
        code = TemplateCommand().handle_template_command(
            template_type="medallion_basic",
            project_name="shop",
            output_path=str(root),
            config_format=fmt,
        )
    assert code == 0 and (root / f"ducta.{fmt}").is_file()
    return root


def _set_ai(root: Path, fmt: str, **values: bool) -> None:
    path = root / f"ducta.{fmt}"
    if fmt == "toml":
        lines = "".join(f"{k} = {str(v).lower()}\n" for k, v in values.items())
        path.write_text(path.read_text() + f"\n[ai]\n{lines}")
    else:
        import json

        data = json.loads(path.read_text())
        data["ai"] = values
        path.write_text(json.dumps(data, indent=2))


@pytest.mark.parametrize("fmt", ["toml", "json"])
def test_the_ai_policy_is_read_from_a_toml_or_json_project(tmp_path, fmt):
    from ducta.ai.policy import project_policy, require_allowed
    from ducta.setting.project.loader import load_project_v2

    root = _project(tmp_path, fmt)
    _set_ai(root, fmt, enabled=False)
    load_project_v2(root, "dev")  # the block is valid project configuration
    assert project_policy(root).enabled is False
    with pytest.raises(AIPolicyError, match=f"ai.enabled: false in ducta.{fmt}"):
        require_allowed(root, LOCAL)


@pytest.mark.parametrize("fmt", ["toml", "json"])
def test_remote_false_keeps_a_toml_or_json_project_from_a_remote_model(tmp_path, fmt):
    from ducta.ai.policy import require_allowed

    root = _project(tmp_path, fmt)
    _set_ai(root, fmt, remote=False)
    require_allowed(root, LOCAL)
    with pytest.raises(AIPolicyError, match="only a local model"):
        require_allowed(root, REMOTE)


@pytest.mark.parametrize("fmt", ["toml", "json"])
def test_environments_are_read_from_a_toml_or_json_project(tmp_path, fmt):
    from ducta_server.workspace.manager import WorkspaceManager

    root = _project(tmp_path, fmt)
    manager = WorkspaceManager(root)
    declared = manager.declared_environments()
    assert declared[0] == "base" and len(declared) > 1
    assert set(declared[1:]) <= set(manager.list_environments())


@pytest.mark.parametrize("fmt", ["toml", "json"])
def test_source_info_lists_a_toml_or_json_projects_files(tmp_path, fmt, monkeypatch):
    from ducta_server.source.resolver import SourceResolver

    root = _project(tmp_path, fmt)
    monkeypatch.chdir(tmp_path)
    info = SourceResolver.get_info(str(root))
    assert info.environments[0] == "base" and len(info.environments) > 1
    assert f"ducta.{fmt}" in info.config_files
    assert f"pipelines/etl.{fmt}" in info.config_files


@pytest.mark.parametrize("fmt", ["toml", "json"])
def test_the_web_app_refuses_to_edit_a_toml_or_json_project(tmp_path, fmt):
    from ducta.project_store.errors import ValidationError
    from ducta.project_store.store import V2ProjectStore
    from ducta_server.repositories.project_repository import ProjectRepository

    root = _project(tmp_path, fmt)
    before = sorted(p.name for p in root.iterdir())
    with pytest.raises(ValidationError, match="edits YAML projects only"):
        ProjectRepository(tmp_path).update_settings("shop", {"description": "x"})
    store = V2ProjectStore.detect(root)
    with pytest.raises(ValidationError, match=f"etl.{fmt} is {fmt.upper()}"):
        store.apply_pipeline_ops("etl", [{"op": "set", "node": "load", "key": "retry", "value": 3}])
    assert sorted(p.name for p in root.iterdir()) == before  # no ducta.yaml beside it


def test_a_yaml_project_is_still_edited(tmp_path):
    from ducta_server.repositories.project_repository import ProjectRepository

    _project(tmp_path, "yaml")
    path = ProjectRepository(tmp_path).update_settings("shop", {"description": "edited"})
    assert "edited" in path.read_text()
