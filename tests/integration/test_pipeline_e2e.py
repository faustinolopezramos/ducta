"""Scaffold a project and run a pipeline through the real CLI, on real Spark.

This is the walkthrough from the README, asserted end to end: template → list
pipelines → start → run certificate. Every other test in the suite stops at a
module boundary, so this is the only thing that would catch a break in the wiring
*between* config loading, the executor, the gate and the certificate writer.

Runs the CLI in a subprocess rather than calling ``main()`` in-process, because
the CLI reconfigures global logging and changes the working directory — and
because a subprocess is what actually proves the console entry point works.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.spark


def _run_cli(ducta_cli, *args, cwd, timeout=600):
    """Invoke the Ducta CLI, returning the completed process."""
    return subprocess.run(
        [*ducta_cli, *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


@pytest.fixture(scope="module")
def scaffolded(tmp_path_factory, ducta_cli):
    """A `medallion_basic` project created by `ducta template`, built once."""
    root = tmp_path_factory.mktemp("e2e")
    result = _run_cli(
        ducta_cli,
        "template",
        "--template",
        "medallion_basic",
        "--project-name",
        "demo",
        "--format",
        "yaml",
        cwd=root,
    )
    assert result.returncode == 0, f"template failed:\n{result.stdout}\n{result.stderr}"
    project = root / "demo"
    assert project.is_dir()
    return project


class TestScaffold:
    def test_template_creates_a_runnable_project(self, scaffolded):
        for relative in (
            "config/pipelines.yaml",
            "config/nodes.yaml",
            "config/input.yaml",
            "config/output.yaml",
            "pipelines/etl.py",
            "data/input.csv",
        ):
            assert (scaffolded / relative).is_file(), f"missing {relative}"

    def test_list_pipelines_reports_the_etl_pipeline(self, scaffolded, ducta_cli):
        result = _run_cli(ducta_cli, "config", "list-pipelines", cwd=scaffolded)

        assert result.returncode == 0, result.stderr
        assert "etl" in result.stdout + result.stderr


class TestPipelineRun:
    @pytest.fixture(scope="class")
    def executed(self, scaffolded, ducta_cli):
        result = _run_cli(
            ducta_cli,
            "start",
            "--env",
            "dev",
            "--pipeline",
            "etl",
            "--start-date",
            "2026-01-01",
            "--end-date",
            "2026-01-31",
            cwd=scaffolded,
        )
        assert result.returncode == 0, (
            f"pipeline run failed:\n--- stdout ---\n{result.stdout[-4000:]}\n"
            f"--- stderr ---\n{result.stderr[-4000:]}"
        )
        return result

    def test_run_writes_output_data(self, executed, scaffolded):
        written = [
            p
            for p in (scaffolded / "data" / "dev").rglob("*")
            if p.is_file() and not p.name.startswith((".", "_"))
        ]
        assert written, "pipeline produced no output files under data/dev"

    def test_run_emits_a_verifiable_certificate(self, executed, scaffolded, ducta_cli):
        runs = sorted((scaffolded / ".ducta" / "runs").iterdir())
        assert runs, "no run certificate directory was created"

        certificate = json.loads((runs[-1] / "certificate.json").read_text())
        assert certificate["status"] == "success"
        assert certificate["certificate_hash"]

        verified = _run_cli(
            ducta_cli, "certify", "verify", "--run-id", runs[-1].name, cwd=scaffolded
        )
        assert verified.returncode == 0, verified.stderr
        assert "verified" in (verified.stdout + verified.stderr).lower()

    def test_stdout_is_not_polluted_with_serialized_logs(self, executed):
        """Regression guard: importing ducta.api used to hijack the CLI's logging.

        `ducta.api.main` built its FastAPI app at import time, and `create_app`
        calls `configure_logging`, which does `logger.remove()` and installs a
        JSON sink on stdout. Because the executor imported an API helper on the
        node path, every pipeline run dumped serialized loguru records over its
        own Rich output.
        """
        json_lines = [
            line
            for line in executed.stdout.splitlines()
            if line.startswith('{"text"') and '"record"' in line
        ]
        assert not json_lines, (
            f"{len(json_lines)} serialized loguru records leaked onto stdout; "
            f"first: {json_lines[0][:200]}"
        )
