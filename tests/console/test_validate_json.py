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
from ducta.console.templates import TemplateGenerator, TemplateType
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


def test_environment_problems_are_listed_and_do_not_fail(tmp_path, monkeypatch, capsys):
    import ducta.runtime_check as runtime_check

    monkeypatch.setattr(runtime_check, "stack_warnings", lambda: ("Java 11 is too old",))
    monkeypatch.setattr(runtime_check, "config_warnings", lambda spark_config: ())
    code, doc = _validate(monkeypatch, capsys, _project(tmp_path))
    assert code == ExitCode.SUCCESS.value, doc
    assert doc["ok"] is True and doc["environment"] == ["Java 11 is too old"]


def _set_spark_config(root: Path, entries: str) -> None:
    project = root / "ducta.yaml"
    text = project.read_text()
    assert text.count("\n  spark_config:\n") == 1, text
    project.write_text(text.replace("\n  spark_config:\n", f"\n  spark_config:\n{entries}"))


def test_spark_defaults_left_unset_are_listed(tmp_path, monkeypatch, capsys):
    import ducta.runtime_check as runtime_check

    monkeypatch.setattr(runtime_check, "stack_warnings", lambda: ())
    monkeypatch.setattr(runtime_check, "_version", lambda name: "4.2.0")
    code, doc = _validate(monkeypatch, capsys, _project(tmp_path))
    assert code == ExitCode.SUCCESS.value, doc
    assert [w for w in doc["environment"] if runtime_check.ANSI_KEY in w]
    assert [w for w in doc["environment"] if runtime_check.TIMEZONE_KEY in w]


def test_setting_the_spark_keys_silences_them(tmp_path, monkeypatch, capsys):
    import ducta.runtime_check as runtime_check

    monkeypatch.setattr(runtime_check, "stack_warnings", lambda: ())
    monkeypatch.setattr(runtime_check, "_version", lambda name: "4.2.0")
    root = _project(tmp_path)
    _set_spark_config(
        root, "    spark.sql.ansi.enabled: 'false'\n    spark.sql.session.timeZone: UTC\n"
    )
    code, doc = _validate(monkeypatch, capsys, root)
    assert code == ExitCode.SUCCESS.value, doc
    assert doc["environment"] == []
