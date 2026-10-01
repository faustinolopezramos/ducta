"""`ducta config show | explain | diff | convert` through the command handlers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest
import yaml

from ducta.console.commands.config_cmds import handle_config
from ducta.console.core import ExitCode
from ducta.console.template import TemplateGenerator, TemplateType


@pytest.fixture
def project(tmp_path, monkeypatch) -> Path:
    root = tmp_path / "proj"
    TemplateGenerator(root).generate_project(TemplateType.MEDALLION_BASIC, "proj")
    monkeypatch.chdir(root)
    return root


def _run(capsys, command: str, **options) -> tuple[int, str]:
    args = argparse.Namespace(
        **{"config_command": command, "base_path": None, "env": None, **options}
    )
    code = handle_config(args)
    return code, capsys.readouterr().out


def test_show_prints_the_resolved_project(project, capsys):
    code, out = _run(capsys, "show", env="prod", pipeline="etl", output_format="yaml", engine=False)
    assert code == ExitCode.SUCCESS.value
    tree = yaml.safe_load(out)
    assert tree["settings"]["max_parallel_nodes"] == 8
    assert set(tree["pipelines"]) == {"etl"}


def test_show_as_json_and_as_toml(project, capsys):
    _, out = _run(capsys, "show", output_format="json", pipeline=None, engine=False)
    assert json.loads(out)["project"] == "proj"
    _, out = _run(capsys, "show", output_format="toml", pipeline=None, engine=False)
    assert 'project = "proj"' in out


def test_show_engine_prints_the_five_documents(project, capsys):
    _, out = _run(capsys, "show", output_format="json", pipeline=None, engine=True)
    assert set(json.loads(out)) == {
        "global_config",
        "pipelines_config",
        "nodes_config",
        "input_config",
        "output_config",
    }


def test_explain_follows_a_value_through_the_environment(project, capsys):
    code, out = _run(capsys, "explain", path="settings.max_parallel_nodes", env="prod")
    assert code == ExitCode.SUCCESS.value
    lines = out.splitlines()
    assert lines[0] == "settings.max_parallel_nodes = 8"
    assert "file" in lines[1] and "ducta.yaml:" in lines[1]
    assert "environments.prod" in lines[2]


def test_explain_names_defaults(project, capsys):
    _, out = _run(capsys, "explain", path="catalog.silver.etl.clean_data.format")
    assert "defaults" in out and '"parquet"' in out


def test_explain_a_typo_is_an_error_with_a_suggestion(project, capsys, caplog):
    code, _ = _run(capsys, "explain", path="settings.max_paralel_nodes")
    assert code == ExitCode.VALIDATION_ERROR.value


def test_diff_lists_what_differs(project, capsys):
    _, out = _run(capsys, "diff", env_a="dev", env_b="prod")
    assert "settings.max_parallel_nodes: 1 -> 8" in out


def test_diff_of_an_environment_with_itself(project, capsys):
    _, out = _run(capsys, "diff", env_a="dev", env_b="dev")
    assert "resolve to the same project" in out


def test_convert_writes_a_project_in_the_new_format(project, tmp_path, capsys):
    code, _ = _run(capsys, "convert", to_format="toml", out=str(tmp_path / "toml"))
    assert code == ExitCode.SUCCESS.value
    assert (tmp_path / "toml" / "ducta.toml").is_file()
    assert (tmp_path / "toml" / "pipelines" / "etl.toml").is_file()


def test_convert_refuses_a_directory_in_use(project, tmp_path, capsys):
    code, _ = _run(capsys, "convert", to_format="json", out=str(project))
    assert code == ExitCode.VALIDATION_ERROR.value
