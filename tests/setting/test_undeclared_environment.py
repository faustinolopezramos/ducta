"""``--env`` naming no declared environment runs the base project, and says so as a warning.

``-e prodx`` (a typo of ``prod``) ran the base configuration and wrote under ``prodx/`` with
only an INFO line; ``config validate -e prodx`` passed.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from loguru import logger

from ducta.setting.project import overlay
from ducta.setting.project.loader import validate_project

PROJECT = """\
version: 2
project: demo
paths: {input: data, output: out}
environments:
  prod:
    settings: {max_parallel_nodes: 8}
  sandbox:
    settings: {max_parallel_nodes: 1}
"""

PIPELINE = """\
nodes:
  keep:
    run: pipelines.daily:keep
    inputs: [raw.app.events]
    outputs: [silver.app.events]
"""

CATALOG = """\
raw.app.events: {format: csv, path: data/events.csv}
silver.app.events: {format: parquet}
"""


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "pipelines").mkdir()
    (tmp_path / "ducta.yaml").write_text(PROJECT)
    (tmp_path / "catalog.yaml").write_text(CATALOG)
    (tmp_path / "pipelines" / "daily.yaml").write_text(PIPELINE)
    return tmp_path


@pytest.fixture
def warnings(monkeypatch):
    monkeypatch.setattr(overlay, "_WARNED_UNDECLARED", set())
    seen = []
    logger.enable("ducta")  # Ducta as a library logs nothing until enabled, as the CLI does
    sink = logger.add(lambda m: seen.append(m.record["message"]), level="WARNING")
    yield seen
    logger.remove(sink)
    logger.disable("ducta")


def _undeclared(seen):
    return [m for m in seen if "is not declared in ducta.yaml" in m]


def test_a_typo_warns_and_suggests_the_close_name(project, warnings):
    validate_project(project, "prodx")
    found = _undeclared(warnings)
    assert len(found) == 1
    assert "'prodx'" in found[0] and "prod, sandbox" in found[0]
    assert "Did you mean 'prod'?" in found[0]


def test_an_environment_without_a_block_warns_without_a_guess(project, warnings):
    validate_project(project, "qa")
    found = _undeclared(warnings)
    assert len(found) == 1 and "Did you mean" not in found[0]


def test_the_warning_is_said_once_per_project_and_environment(project, warnings):
    validate_project(project, "prodx")
    validate_project(project, "prodx")
    assert len(_undeclared(warnings)) == 1


@pytest.mark.parametrize("env", ["prod", "production", "sandbox_ana", "base", None])
def test_declared_or_base_environments_are_quiet(project, warnings, env):
    validate_project(project, env)
    assert _undeclared(warnings) == []


def test_the_base_project_still_runs(project, warnings):
    """Behaviour unchanged: the warning is the only difference."""
    assert validate_project(project, "prodx") is not None
