"""Comments: one file per thread, anchored to a node or a line of code."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from ducta.api.dependencies import get_current_user
from ducta.api.main import create_app
from ducta.api.models.auth import User
from ducta.api.services.comments import CommentNotFound, LocalCommentStore, clean_anchor


def test_threads_are_files_and_filter_by_anchor(tmp_path):
    store = LocalCommentStore(tmp_path)
    a = store.add(
        {"pipeline": "silver.clean", "node": "silver.clean_student"}, "ana", "Why drop nulls here?"
    )
    store.add({"file": "src/silver.py", "line": 97}, "luis", "This select looks wrong")
    assert (tmp_path / ".ducta" / "comments" / f"{a.id}.json").is_file()
    assert [t.body for t in store.list(node="silver.clean_student")] == ["Why drop nulls here?"]
    assert [t.anchor for t in store.list(file="src/silver.py")] == [
        {"file": "src/silver.py", "line": 97}
    ]

    store.reply(a.id, "luis", "Upstream sends empty ids")
    resolved = store.resolve(a.id, "ana")
    assert resolved.resolved and resolved.resolved_by == "ana"
    saved = json.loads((tmp_path / ".ducta" / "comments" / f"{a.id}.json").read_text())
    assert saved["replies"][0]["body"] == "Upstream sends empty ids"

    store.delete(a.id)
    with pytest.raises(CommentNotFound):
        store.get(a.id)


def test_anchors_and_ids_are_checked(tmp_path):
    with pytest.raises(ValueError):
        clean_anchor({"file": "../etc/passwd"})
    with pytest.raises(ValueError):
        clean_anchor({})
    with pytest.raises(CommentNotFound):
        LocalCommentStore(tmp_path).get("../../x")


@pytest.fixture
def root(tmp_path, monkeypatch):
    from ducta.console.template import TemplateGenerator, TemplateType

    monkeypatch.chdir(tmp_path)
    root = tmp_path / "proj"
    TemplateGenerator(root).generate_project(TemplateType.MEDALLION_BASIC, "proj")
    return root


def _client(username="ana", roles=("developer",)) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: User(
        id=username, username=username, email=f"{username}@example.com", roles=list(roles)
    )
    return TestClient(app)


def test_comment_routes(root):
    params = {"source": str(root)}
    c = _client(roles=["admin"])
    r = c.post(
        "/api/projects/proj/comments",
        params=params,
        json={"anchor": {"node": "n1", "pipeline": "etl"}, "body": "Check this"},
    )
    assert r.status_code == 200, r.text
    tid = r.json()["id"]
    assert (
        c.post(
            f"/api/projects/proj/comments/{tid}/replies", params=params, json={"body": "ok"}
        ).status_code
        == 200
    )
    assert c.patch(
        f"/api/projects/proj/comments/{tid}", params=params, json={"resolved": True}
    ).json()["resolved"]
    threads = c.get("/api/projects/proj/comments", params={**params, "node": "n1"}).json()[
        "threads"
    ]
    assert len(threads) == 1 and threads[0]["replies"][0]["body"] == "ok"
    open_only = c.get(
        "/api/projects/proj/comments", params={**params, "include_resolved": "false"}
    ).json()["threads"]
    assert open_only == []
    assert (
        c.post(
            "/api/projects/proj/comments",
            params=params,
            json={"anchor": {"file": "../x"}, "body": "x"},
        ).status_code
        == 400
    )
    assert c.delete(f"/api/projects/proj/comments/{tid}", params=params).status_code == 200
