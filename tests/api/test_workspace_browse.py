"""The directory listing behind the connect screen's local-folder picker.

Scoped to the same base `SourceResolver.resolve_local` enforces, on purpose: a
native OS dialog would let someone pick any folder on the machine and then have
it rejected on submit. Offering only reachable directories makes the constraint
visible instead of surprising.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

_PROJECT = "version: 2\nproject: demo\npaths: {input: data, output: data}\n"


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    (tmp_path / "projects" / "alpha" / "pipelines").mkdir(parents=True)
    (tmp_path / "projects" / "alpha" / "ducta.yaml").write_text(_PROJECT)
    (tmp_path / "projects" / "beta").mkdir()
    (tmp_path / "node_modules").mkdir()
    (tmp_path / ".hidden").mkdir()
    (tmp_path / "ducta.yaml").write_text(_PROJECT)
    monkeypatch.setenv("DUCTA_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("AUTH_ENABLED", "false")
    return tmp_path


@pytest.fixture
def client(workspace):
    from ducta.api.config import get_settings
    from ducta.api.main import create_app

    get_settings.cache_clear()
    with TestClient(create_app()) as c:
        yield c


def test_defaults_to_the_reachable_root(client, workspace):
    body = client.get("/api/workspace/browse").json()
    assert body["path"] == str(workspace.resolve())
    assert body["root"] == str(workspace.resolve())
    # No parent at the root: there is nowhere further up the server would accept.
    assert body["parent"] is None


def test_lists_directories_and_hides_the_noise(client, workspace):
    names = {e["name"] for e in client.get("/api/workspace/browse").json()["entries"]}
    assert "projects" in names
    # Build/tooling directories are never a workspace and only add scrolling.
    assert "node_modules" not in names
    assert ".hidden" not in names


def test_flags_a_directory_ducta_already_recognises(client, workspace):
    body = client.get("/api/workspace/browse", params={"path": str(workspace / "projects")}).json()
    by_name = {e["name"]: e for e in body["entries"]}
    assert by_name["alpha"]["is_workspace"] is True, "has ducta.yaml"
    assert by_name["beta"]["is_workspace"] is False


def test_descending_reports_a_parent_to_climb_back(client, workspace):
    body = client.get("/api/workspace/browse", params={"path": str(workspace / "projects")}).json()
    assert body["parent"] == str(workspace.resolve())


@pytest.mark.parametrize("escape", ["/etc", "/", "{ws}/../.."])
def test_refuses_to_list_outside_the_reachable_base(client, workspace, escape):
    target = escape.format(ws=str(workspace))
    r = client.get("/api/workspace/browse", params={"path": target})
    assert r.status_code == 400
    # The app's exception handler reshapes HTTPException.detail into `message`.
    assert "outside" in r.json()["message"].lower()


def test_a_file_is_not_a_directory(client, workspace):
    r = client.get("/api/workspace/browse", params={"path": str(workspace / "ducta.yaml")})
    assert r.status_code == 400
