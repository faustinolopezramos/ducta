"""The file API does not write into ``.git/`` or ``.ducta/``, nor read ``.git/``.

``PUT .git/config`` with ``core.fsmonitor = <command>`` ran the command inside the server on
the next ``GET /api/git/status``; ``.ducta/audit.log`` could be overwritten, erasing the trail.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ducta_server.dependencies import get_current_user
from ducta_server.main import create_app
from ducta_server.models.auth import User

FILES = "/api/workspace/files/content"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("[core]\n")
    (tmp_path / ".ducta" / "schema").mkdir(parents=True)
    (tmp_path / ".ducta" / "schema" / "project.json").write_text("{}")
    (tmp_path / ".ducta" / "audit.log").write_text("trail\n")
    (tmp_path / "pipelines").mkdir()
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: User(
        id="admin", username="admin", email="admin@example.com", roles=["admin"]
    )
    return TestClient(app), {"source": str(tmp_path)}, tmp_path


@pytest.mark.parametrize(
    "path",
    [
        ".git/config",
        ".git/hooks/pre-commit",
        ".GIT/config",
        "sub/.git/config",
        ".ducta/audit.log",
        ".ducta/x",
        ".DUCTA/x",
    ],
)
def test_writing_there_is_refused(client, path):
    c, params, root = client
    before = (root / ".git" / "config").read_text()
    r = c.put(FILES, params=params, json={"path": path, "content": "tampered\n"})
    assert r.status_code == 403
    assert (root / ".git" / "config").read_text() == before
    assert (root / ".ducta" / "audit.log").read_text() == "trail\n"
    assert not (root / ".git" / "hooks").exists()


@pytest.mark.parametrize("path", [".git/config", ".ducta/audit.log"])
def test_deleting_there_is_refused(client, path):
    c, params, root = client
    assert c.delete("/api/workspace/files", params={**params, "path": path}).status_code == 403
    assert (root / path).exists()


def test_reading_the_repository_files_is_refused(client):
    c, params, _ = client
    assert c.get(FILES, params={**params, "path": ".git/config"}).status_code == 403
    assert c.get("/api/workspace/files", params={**params, "path": ".git"}).status_code == 403


def test_the_editors_schema_is_still_readable(client):
    c, params, _ = client
    assert c.get(FILES, params={**params, "path": ".ducta/schema/project.json"}).status_code == 200


def test_the_projects_own_files_are_unaffected(client):
    c, params, root = client
    r = c.put(FILES, params=params, json={"path": "pipelines/new.py", "content": "x = 1\n"})
    assert r.status_code == 204 and (root / "pipelines" / "new.py").exists()
    assert (
        c.delete("/api/workspace/files", params={**params, "path": "pipelines/new.py"}).status_code
        == 204
    )


def test_a_symlink_into_git_does_not_open_it(client):
    c, params, root = client
    (root / "pipelines" / "cfg").symlink_to(root / ".git")
    r = c.put(FILES, params=params, json={"path": "pipelines/cfg/config", "content": "tampered\n"})
    assert r.status_code == 403
    assert (root / ".git" / "config").read_text() == "[core]\n"
