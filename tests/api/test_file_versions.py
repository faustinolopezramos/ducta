"""A file edited elsewhere since it was opened is not overwritten unseen."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ducta.api.dependencies import get_current_user
from ducta.api.main import create_app
from ducta.api.models.auth import User


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.py").write_text("x = 1\n")
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: User(
        id="admin", username="admin", email="admin@example.com", roles=["admin"]
    )
    return TestClient(app), {"source": str(tmp_path)}, tmp_path


def test_write_with_the_version_read(client):
    c, params, root = client
    v = c.get("/api/workspace/files/content", params={**params, "path": "a.py"}).json()["version"]
    r = c.put(
        "/api/workspace/files/content",
        params=params,
        json={"path": "a.py", "content": "x = 2\n", "expected_version": v},
    )
    assert r.status_code == 204
    assert (root / "a.py").read_text() == "x = 2\n"


def test_a_stale_write_is_refused_with_the_current_content(client):
    c, params, root = client
    v = c.get("/api/workspace/files/content", params={**params, "path": "a.py"}).json()["version"]
    (root / "a.py").write_text("x = 99  # edited in another editor\n")
    r = c.put(
        "/api/workspace/files/content",
        params=params,
        json={"path": "a.py", "content": "x = 2\n", "expected_version": v},
    )
    assert r.status_code == 409
    body = r.json()
    assert body["error"] == "CONCURRENCY_ERROR"
    assert "edited in another editor" in body["detail"]["content"]
    assert (root / "a.py").read_text().startswith("x = 99")


def test_without_a_version_it_writes_as_before(client):
    c, params, root = client
    r = c.put(
        "/api/workspace/files/content", params=params, json={"path": "a.py", "content": "y\n"}
    )
    assert r.status_code == 204
