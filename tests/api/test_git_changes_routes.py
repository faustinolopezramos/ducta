"""Explicit commits: list what changed, diff it, commit chosen files — and never
rewrite the repository's own git identity."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

git = pytest.importorskip("git")

from ducta.api.dependencies import get_current_user  # noqa: E402
from ducta.api.main import create_app  # noqa: E402
from ducta.api.models.auth import User  # noqa: E402


def _client() -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: User(
        id="admin", username="admin", email="admin@example.com", roles=["admin"]
    )
    return TestClient(app)


@pytest.fixture
def repo(tmp_path, monkeypatch) -> Path:
    from ducta.console.template import TemplateGenerator, TemplateType

    monkeypatch.chdir(tmp_path)
    root = tmp_path / "proj"
    TemplateGenerator(root).generate_project(TemplateType.MEDALLION_BASIC, "proj")
    r = git.Repo.init(root)
    with r.config_writer() as cw:
        cw.set_value("user", "name", "Owner")
        cw.set_value("user", "email", "owner@example.com")
    r.git.add(A=True)
    r.index.commit("initial")
    return root


def test_changes_lists_edited_and_new_files(repo):
    (repo / "pipelines" / "etl.yaml").write_text(
        (repo / "pipelines" / "etl.yaml").read_text() + "\n# x\n"
    )
    (repo / "src_new.py").write_text("x = 1\n")
    r = _client().get("/api/git/changes", params={"source": str(repo)})
    assert r.status_code == 200, r.text
    changes = {c["path"]: c for c in r.json()["changes"]}
    assert changes["pipelines/etl.yaml"]["status"] == "modified"
    assert changes["pipelines/etl.yaml"]["staged"] is False
    assert changes["src_new.py"]["status"] == "untracked"


def test_working_diff_returns_head_and_disk(repo):
    path = repo / "pipelines" / "etl.yaml"
    before = path.read_text()
    path.write_text(before + "\n# changed\n")
    r = _client().get(
        "/api/git/working-diff", params={"source": str(repo), "path": "pipelines/etl.yaml"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["original"] == before
    assert r.json()["modified"].endswith("# changed\n")


def test_commit_stages_exactly_the_chosen_paths(repo):
    (repo / "a.txt").write_text("a")
    (repo / "b.txt").write_text("b")
    r = _client().post(
        "/api/git/commit",
        params={"source": str(repo)},
        json={
            "paths": ["a.txt"],
            "message": "add a",
            "author_name": "Ana",
            "author_email": "ana@x.io",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["success"] is True
    head = git.Repo(repo).head.commit
    assert head.message == "add a"
    assert head.author.name == "Ana"
    assert list(head.stats.files) == ["a.txt"]
    assert "b.txt" in git.Repo(repo).untracked_files
    # The commit's author is the commit's; the repository keeps its own identity.
    assert git.Repo(repo).config_reader().get_value("user", "name") == "Owner"


def test_nothing_staged_is_not_committed(repo):
    (repo / "a.txt").write_text("a")
    head = git.Repo(repo).head.commit.hexsha
    r = _client().post("/api/git/commit", params={"source": str(repo)}, json={"message": "x"})
    assert r.json()["success"] is False
    assert git.Repo(repo).head.commit.hexsha == head


def test_a_file_at_a_commit(repo):
    head = git.Repo(repo).head.commit.hexsha
    path = repo / "pipelines" / "etl.yaml"
    original = path.read_text()
    path.write_text(original + "\n# later\n")
    r = _client().get(
        "/api/git/file-at", params={"source": str(repo), "path": "pipelines/etl.yaml", "rev": head}
    )
    assert r.status_code == 200, r.text
    assert r.json() == {
        "path": "pipelines/etl.yaml",
        "rev": head,
        "exists": True,
        "content": original,
    }
    r = _client().get(
        "/api/git/file-at", params={"source": str(repo), "path": "nope.txt", "rev": head}
    )
    assert r.json()["exists"] is False
