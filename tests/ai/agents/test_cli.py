"""``ducta ai architect`` and ``ducta ai sentinel`` from the terminal: the
commands that need no model answer in JSON, for scripts and assistants."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

from ducta.console.commands.ai_cmds import AICommands
from ducta.console.parser import UnifiedArgumentParser

sys.path.insert(0, str(Path(__file__).parent))
from test_architect import BLUEPRINT, SALES  # noqa: E402

POLICY = "\nsentinel: {enabled: true, environments: [dev], retry_infra: {backoff_seconds: [0]}}\n"


@pytest.fixture
def sales(tmp_path, monkeypatch):
    root = tmp_path / "sales"
    shutil.copytree(SALES, root)
    (root / "ducta.yaml").write_text((root / "ducta.yaml").read_text() + POLICY)
    monkeypatch.chdir(root)
    return root


def _run(*argv: str) -> int:
    return AICommands.handle(UnifiedArgumentParser.create().parse_args(["ai", *argv]))


def _out(capsys) -> dict:
    return json.loads(capsys.readouterr().out)


def test_check_needs_no_model(sales, capsys):
    (sales / "bp.yaml").write_text(BLUEPRINT)
    assert _run("architect", "check", "bp.yaml", "--output-format", "json") == 0
    assert _out(capsys)["ok"] is True
    (sales / "bad.yaml").write_text(BLUEPRINT.replace("write: merge", "write: upsert"))
    assert _run("architect", "check", "bad.yaml", "--output-format", "json") == 3


def test_scaffold_writes_stubs_without_a_model(sales):
    (sales / "bp.yaml").write_text(BLUEPRINT)
    assert _run("architect", "scaffold", "bp.yaml", "--write", "--yes") == 0
    source = (sales / "pipelines" / "silver_stores.py").read_text()
    assert "def orders_with_store(orders, **kwargs):" in source and "NotImplementedError" in source


def test_sentinel_status_and_incidents(sales, capsys):
    assert _run("sentinel", "status", "--output-format", "json") == 0
    status = _out(capsys)
    assert status["enabled"] and status["environments"] == ["dev"] and status["active"] == 0
    assert _run("sentinel", "incidents", "--output-format", "json") == 0
    assert _out(capsys) == []


def test_sentinel_watch_once_runs_due_reruns(sales, capsys, monkeypatch):
    from ducta.ai.agents.sentinel.engine import Sentinel
    from ducta.ai.agents.sentinel.incidents import Incidents
    from ducta.ai.agents.sentinel.triage import RunEvent

    class Recorder:
        calls: list = []

        def rerun(self, root, env, pipeline, nodes, reuse):
            Recorder.calls.append(pipeline)
            return RunEvent(
                env=env, pipeline=pipeline, status="success", run_id="x", actor="sentinel"
            )

    Sentinel(sales, Recorder(), notify=False).handle(
        RunEvent(
            env="dev",
            pipeline="bronze.sales",
            status="failed",
            run_id="r",
            error="Connection refused",
        )
    )
    monkeypatch.setattr("ducta.ai.agents.sentinel.actions.CliExecutor", lambda *a, **k: Recorder())
    monkeypatch.setattr(
        "ducta.api.services.run_certificates.certificates", lambda root, env: iter([])
    )
    assert _run("sentinel", "watch", "--once", "--env", "dev", "--output-format", "json") == 0
    assert Recorder.calls == ["bronze.sales"]
    assert [i.status for i in Incidents(sales).list()] == ["resolved"]


def test_sentinel_pause_resume_and_close(sales):
    from ducta.ai.agents.sentinel import policy as gate
    from ducta.ai.agents.sentinel.engine import Sentinel
    from ducta.ai.agents.sentinel.incidents import Incidents
    from ducta.ai.agents.sentinel.triage import RunEvent

    assert _run("sentinel", "pause", "--reason", "upgrade") == 0 and gate.is_paused(sales)
    assert _run("sentinel", "resume") == 0 and not gate.is_paused(sales)

    class Nothing:
        def rerun(self, *a, **k):
            return None

    incident = Sentinel(sales, Nothing(), notify=False).handle(
        RunEvent(
            env="dev",
            pipeline="bronze.sales",
            status="failed",
            run_id="r",
            error="Traceback\nValueError: x",
        )
    )
    assert _run("sentinel", "ignore", incident.id, "--note", "known") == 0
    assert Incidents(sales).get(incident.id).status == "ignored"
    assert _run("sentinel", "resolve", incident.id) == 2  # already closed
