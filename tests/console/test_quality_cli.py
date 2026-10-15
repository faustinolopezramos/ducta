"""`ducta quality list | run | report | trend | validate-config`, end to end.

Driven through the real argument parser and ``main()``: a standalone run on a
CSV stores its report under the workspace, and ``report``/``trend`` read back
what it stored — the loop a user follows before adopting a project.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from ducta.console.core import ExitCode
from ducta.console.wrapper import main

CHECKS = "checks:\n  row_count: {min: 2}\n  null_rate: {columns: [id], threshold: 0}\n"


def _ducta(monkeypatch, capsys, *args: str) -> tuple:
    capsys.readouterr()
    monkeypatch.setattr(sys, "argv", ["ducta", *args])
    code = main()
    return code, capsys.readouterr().out


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "people.csv").write_text("id,name\n1,a\n2,b\n3,c\n")
    (tmp_path / "checks.yaml").write_text(CHECKS)
    return tmp_path


def _run(monkeypatch, capsys, data: str = "people.csv", checks: str = "checks.yaml"):
    return _ducta(
        monkeypatch,
        capsys,
        "quality",
        "run",
        "--input",
        data,
        "--format",
        "csv",
        "--config",
        checks,
        "--output-format",
        "json",
    )


def test_list_names_the_built_in_checks(workspace, monkeypatch, capsys):
    code, _ = _ducta(monkeypatch, capsys, "quality", "list")
    assert code == ExitCode.SUCCESS.value


def test_run_passes_and_prints_a_json_report(workspace, monkeypatch, capsys):
    code, out = _run(monkeypatch, capsys)

    assert code == ExitCode.SUCCESS.value
    report = json.loads(out)
    assert report["passed"] is True
    assert {"row_count", "null_rate"} <= {r["check_name"] for r in report["results"]}


def test_a_failing_check_fails_the_command(workspace, monkeypatch, capsys):
    (workspace / "checks.yaml").write_text("checks:\n  row_count: {min: 10}\n")
    code, out = _run(monkeypatch, capsys)

    assert code == ExitCode.GENERAL_ERROR.value
    assert json.loads(out)["passed"] is False


def test_a_missing_input_is_a_validation_error(workspace, monkeypatch, capsys):
    code, _ = _run(monkeypatch, capsys, data="missing.csv")
    assert code == ExitCode.VALIDATION_ERROR.value


def test_rich_output_keeps_the_exit_code(workspace, monkeypatch, capsys):
    code, _ = _ducta(
        monkeypatch,
        capsys,
        *["quality", "run", "--input", "people.csv", "--format", "csv", "--config", "checks.yaml"],
    )
    assert code == ExitCode.SUCCESS.value


def test_report_reads_back_what_run_stored(workspace, monkeypatch, capsys):
    _run(monkeypatch, capsys)

    code, out = _ducta(
        monkeypatch, capsys, "quality", "report", "--dataset", "people", "--output-format", "json"
    )
    assert code == ExitCode.SUCCESS.value
    assert json.loads(out)["passed"] is True

    code, out = _ducta(monkeypatch, capsys, "quality", "report", "--dataset", "people", "--all")
    assert code == ExitCode.SUCCESS.value
    assert "Reports for 'people'" in out


def test_report_for_an_unknown_dataset_is_not_an_error(workspace, monkeypatch, capsys):
    code, _ = _ducta(monkeypatch, capsys, "quality", "report", "--dataset", "nobody")
    assert code == ExitCode.SUCCESS.value


def test_trend_lists_one_score_per_run(workspace, monkeypatch, capsys):
    _run(monkeypatch, capsys)
    _run(monkeypatch, capsys)

    code, out = _ducta(
        monkeypatch, capsys, "quality", "trend", "--dataset", "people", "--output-format", "json"
    )
    assert code == ExitCode.SUCCESS.value
    scores = json.loads(out)["scores"]
    assert len(scores) == 2 and all(0.0 <= s <= 1.0 for s in scores)

    code, _ = _ducta(monkeypatch, capsys, "quality", "trend", "--dataset", "people")
    assert code == ExitCode.SUCCESS.value


def test_validate_config_outside_a_project_fails_cleanly(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    code, _ = _ducta(monkeypatch, capsys, "quality", "validate-config", "--node", "x")
    assert code == ExitCode.GENERAL_ERROR.value


def _template(tmp_path, monkeypatch) -> Path:
    from ducta.console.template import TemplateGenerator, TemplateType

    root: Path = tmp_path / "proj"
    TemplateGenerator(root).generate_project(TemplateType.MEDALLION_BASIC, "proj")
    monkeypatch.chdir(root)
    return root


def test_validate_config_accepts_the_template_quality_block(tmp_path, monkeypatch, capsys):
    _template(tmp_path, monkeypatch)
    code, _ = _ducta(monkeypatch, capsys, "quality", "validate-config", "--node", "transform")
    assert code == ExitCode.SUCCESS.value


def test_validate_config_rejects_an_unknown_check(tmp_path, monkeypatch, capsys):
    root = _template(tmp_path, monkeypatch)
    etl = root / "pipelines" / "etl.yaml"
    etl.write_text(
        etl.read_text().replace("      row_count: {min: 400}", "      no_such_check: {}")
    )

    code, _ = _ducta(monkeypatch, capsys, "quality", "validate-config", "--node", "transform")
    assert code == ExitCode.VALIDATION_ERROR.value
