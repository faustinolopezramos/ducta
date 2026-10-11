"""``ducta config validate --output-format json``: one JSON document on stdout.

CI jobs and AI assistants read it instead of parsing log lines, so stdout must
hold the document and nothing else, in every outcome — valid, invalid, or a
project that does not load — and the exit code must stay what it was.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from ducta.console.core import ExitCode
from ducta.console.template import TemplateGenerator, TemplateType
from ducta.console.wrapper import main


def _project(root: Path, run: str = "pipelines.etl:extract") -> Path:
    TemplateGenerator(root).generate_project(TemplateType.MEDALLION_BASIC, "proj")
    etl = root / "pipelines" / "etl.yaml"
    etl.write_text(etl.read_text().replace("run: pipelines.etl:extract", f"run: {run}"))
    return root


def _validate(monkeypatch, capsys, root: Path) -> tuple:
    capsys.readouterr()  # what generating the project printed
    monkeypatch.chdir(root)
    monkeypatch.syspath_prepend(str(root))
    for name in [m for m in sys.modules if m == "pipelines" or m.startswith("pipelines.")]:
        monkeypatch.delitem(sys.modules, name)
    monkeypatch.setattr(
        sys, "argv", ["ducta", "config", "validate", "--env", "dev", "--output-format", "json"]
    )
    code = main()
    out = capsys.readouterr().out
    return code, json.loads(out)


def test_a_valid_project_is_ok(tmp_path, monkeypatch, capsys):
    code, doc = _validate(monkeypatch, capsys, _project(tmp_path))
    assert code == ExitCode.SUCCESS.value, doc
    assert doc["ok"] is True and doc["env"] == "dev" and doc["config_error"] == []
    assert doc["pipelines"]["etl"]["ok"] is True


def test_a_preflight_error_is_located(tmp_path, monkeypatch, capsys):
    code, doc = _validate(monkeypatch, capsys, _project(tmp_path, run="src.m:missing"))
    assert code == ExitCode.VALIDATION_ERROR.value
    assert doc["ok"] is False
    problems = doc["pipelines"]["etl"]["problems"]
    assert problems and problems[0]["severity"] == "error"
    assert {"message", "severity", "source"} <= set(problems[0])


def test_a_project_that_does_not_load_is_still_json(tmp_path, monkeypatch, capsys):
    root = _project(tmp_path)
    (root / "ducta.yaml").write_text("version: 2\nproject: [not, a, name]\n")
    code, doc = _validate(monkeypatch, capsys, root)
    assert code == ExitCode.CONFIGURATION_ERROR.value
    assert doc["ok"] is False and doc["config_error"]
    assert doc["config_error"][0]["severity"] == "error"


def test_a_load_error_keeps_its_location_and_fix(tmp_path, monkeypatch, capsys):
    # The loader's located problem arrives wrapped in a ConfigurationError.
    root = _project(tmp_path)
    etl = root / "pipelines" / "etl.yaml"
    etl.write_text(etl.read_text().replace("    outputs: [silver", "    outptus: [silver"))
    code, doc = _validate(monkeypatch, capsys, root)
    assert code == ExitCode.CONFIGURATION_ERROR.value
    [problem] = doc["config_error"]
    assert problem["code"] == "unknown_key"
    assert problem["file"] == "pipelines/etl.yaml" and problem["line"]
    assert problem["fix"]["replace"] == ["outptus", "outputs"]


def test_no_project_at_all_is_still_json(tmp_path, monkeypatch, capsys):
    code, doc = _validate(monkeypatch, capsys, tmp_path)
    assert code != ExitCode.SUCCESS.value
    assert doc["ok"] is False and doc["config_error"]


@pytest.mark.parametrize("flag", [[], ["--output-format", "rich"]])
def test_the_default_output_is_unchanged(tmp_path, monkeypatch, capsys, flag):
    monkeypatch.chdir(_project(tmp_path))
    monkeypatch.syspath_prepend(str(tmp_path))
    capsys.readouterr()
    monkeypatch.setattr(sys, "argv", ["ducta", "config", "validate", "--env", "dev", *flag])
    assert main() == ExitCode.SUCCESS.value
    assert not capsys.readouterr().out.lstrip().startswith("{")
