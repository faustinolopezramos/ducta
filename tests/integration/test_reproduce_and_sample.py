"""A reproduction and a sample run, end to end with the real CLI and Spark.

Each command runs in its own interpreter (as a user runs it), so no Spark
context is shared with the rest of the suite.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("pyspark")

SRC = str(Path(__file__).resolve().parents[2] / "src")


def _ducta(project: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([SRC, os.environ.get("PYTHONPATH", "")])}
    return subprocess.run(
        [sys.executable, "-c", "from ducta.console.wrapper import main; main()", *args],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )


def _files(root: Path) -> dict:
    """``{path: mtime}`` of every data file outside Ducta's own folders."""
    return {
        str(p): p.stat().st_mtime_ns
        for p in root.rglob("part-*")
        if ".ducta" not in p.relative_to(root).parts
    }


def _certificates(project: Path) -> list:
    runs = project / "data" / "base" / ".ducta" / "runs"
    return [json.loads(p.read_text()) for p in runs.glob("*/certificate.json")]


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    from ducta.console.templates import TemplateGenerator, TemplateType

    root = tmp_path_factory.mktemp("repro") / "p"
    TemplateGenerator(root).generate_project(TemplateType.MEDALLION_BASIC, "p")
    run = _ducta(root, "start", "--pipeline", "etl", "--start-date", "2026-01-01",
                 "--end-date", "2026-01-31")  # fmt: skip
    assert run.returncode == 0, run.stdout[-3000:] + run.stderr[-3000:]
    return root


def test_a_reproduction_never_touches_the_real_datasets(project):
    (original,) = _certificates(project)
    assert original["run_window"] == {"start_date": "2026-01-01", "end_date": "2026-01-31"}
    before = _files(project / "data")

    run = _ducta(project, "certify", "verify", "--run-id", original["run_id"], "--reproduce")

    out = run.stdout + run.stderr
    assert run.returncode == 0, out[-3000:]
    assert "Reproducible: all 3 output(s)" in out
    assert _files(project / "data") == before  # same files, not rewritten
    reproduced = project / "data" / "base" / ".ducta" / "reproduce" / original["run_id"]
    assert any(reproduced.rglob("part-*"))
    (copy,) = [c for c in _certificates(project) if c.get("reproduction_of")]
    assert copy["reproduction_of"] == original["run_id"]
    assert copy["run_window"] == original["run_window"]  # the run's dates, not none


def test_a_sample_run_reads_what_it_wrote_not_the_real_datasets(project, tmp_path):
    """Its downstream nodes read the real intermediate datasets before (or skipped)."""
    script = tmp_path / "sample.py"
    script.write_text(
        "import argparse\n"
        "from ducta.console import execution\n"
        "from ducta.console.commands.config_cmds import _init_config_manager\n"
        "from ducta.api.execution.runner import redirect_to_scratch\n"
        "from ducta.core import PipelineExecutor\n"
        "cm = _init_config_manager(argparse.Namespace(base_path='.', env='base'))\n"
        "ctx = execution.ContextInitializer(cm).initialize('base')\n"
        "redirect_to_scratch(ctx, 'base', 20)\n"
        "r = PipelineExecutor(ctx).run_pipeline(pipeline_name='etl', execution_mode='sync')\n"
        "print('STATUS', r.status.value, sorted(r.skipped))\n"
    )
    real = project / "data" / "base"
    hidden = project / "data" / "hidden-real"
    for layer in ("bronze", "silver"):  # the real intermediates are gone
        (hidden / layer).parent.mkdir(parents=True, exist_ok=True)
        (real / layer).rename(hidden / layer)
    try:
        env = {**os.environ, "PYTHONPATH": SRC}
        run = subprocess.run(
            [sys.executable, str(script)],
            cwd=project,
            env=env,
            capture_output=True,
            text=True,
            timeout=600,
        )
    finally:
        for layer in ("bronze", "silver"):
            (hidden / layer).rename(real / layer)
    assert "STATUS success []" in run.stdout, (run.stdout + run.stderr)[-3000:]
    scratch = real / ".ducta" / "scratch" / "base"
    assert any((scratch / "gold").rglob("part-*"))
