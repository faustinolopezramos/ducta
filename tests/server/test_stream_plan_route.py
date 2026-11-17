"""`POST .../stream-plan`: what a streaming pipeline would do, without starting it.

It imports the project's transform modules, so it runs in a subprocess (never the API
process, never with the server's secrets) and needs the permission to run pipelines.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ducta_server.dependencies import get_current_user
from ducta_server.main import create_app
from ducta_server.models.auth import User
from ducta_server.workspace import preflight


def _user(role: str) -> User:
    return User(id=role, username=role, email=f"{role}@example.com", roles=[role])


@pytest.fixture
def app():
    return create_app()


def _client(app, role: str) -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: _user(role)
    return TestClient(app)


@pytest.fixture
def project(tmp_path, monkeypatch) -> Path:
    from ducta.console.templates import TemplateGenerator, TemplateType

    monkeypatch.chdir(tmp_path)  # the server's source confinement base
    root = tmp_path / "proj"
    TemplateGenerator(root).generate_project(TemplateType.STREAMING_BASIC, "proj")
    return root


URL = "/api/projects/proj/pipelines/events_stream/stream-plan"


def test_a_viewer_cannot_ask_for_the_plan(app, project):
    r = _client(app, "viewer").post(URL, params={"source": str(project)})
    assert r.status_code == 403
    assert "pipeline.execute" in r.text


def test_a_developer_gets_each_nodes_source_sink_trigger_and_checkpoint(app, project):
    r = _client(app, "developer").post(URL, params={"source": str(project), "env": "dev"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["pipeline"] == "events_stream"
    names = [n["name"] for n in body["nodes"]]
    assert names == ["ingest_events", "clean_events"]
    clean = body["nodes"][1]
    assert clean["after"] == ["ingest_events"]
    assert clean["transform"] == "clean_events"
    assert clean["trigger"] == "every 5 seconds"
    assert clean["checkpoint"] and "clean_events" in clean["checkpoint"]


def test_an_unknown_environment_is_refused(app, project):
    r = _client(app, "developer").post(URL, params={"source": str(project), "env": "nope"})
    assert r.status_code == 400


def test_the_plan_subprocess_does_not_get_the_servers_secrets(monkeypatch, tmp_path):
    monkeypatch.setenv("JWT_SECRET_KEY", "probe-secret")
    seen = {}

    def fake_run(cmd, **kwargs):
        seen.update(kwargs)
        out = (
            preflight._STREAM_PLAN_MARKER
            + '{"pipeline": "p", "env": "dev", "ok": true, "nodes": [], "issues": []}\n'
        )
        return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = preflight.run_stream_plan(tmp_path, "p", "dev")
    assert result["ok"] is True
    assert "JWT_SECRET_KEY" not in seen["env"]


def test_a_failed_subprocess_becomes_an_error_issue_not_a_500(monkeypatch, tmp_path):
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="boom")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = preflight.run_stream_plan(tmp_path, "p", "dev")
    assert result["ok"] is False
    assert result["issues"][0]["level"] == "error" and "boom" in result["issues"][0]["text"]
