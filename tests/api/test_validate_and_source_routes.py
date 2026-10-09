"""Editing a pipeline as text, and validating drafts without writing them."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ducta.api.dependencies import get_current_user
from ducta.api.main import create_app
from ducta.api.models.auth import User


def _client() -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: User(
        id="admin", username="admin", email="admin@example.com", roles=["admin"]
    )
    return TestClient(app)


@pytest.fixture
def root(tmp_path, monkeypatch) -> Path:
    from ducta.console.template import TemplateGenerator, TemplateType

    monkeypatch.chdir(tmp_path)
    root = tmp_path / "proj"
    TemplateGenerator(root).generate_project(TemplateType.MEDALLION_BASIC, "proj")
    return root


def _get(root: Path, url: str):
    return _client().get(url, params={"source": str(root)})


def test_source_is_the_file_with_its_comments(root):
    etl = root / "pipelines" / "etl.yaml"
    etl.write_text("# keep me\n" + etl.read_text())
    r = _get(root, "/api/projects/proj/pipelines/etl/source")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["file"] == "pipelines/etl.yaml"
    assert body["content"].startswith("# keep me\n")
    assert body["version"]


def test_saving_text_keeps_it_verbatim_and_rejects_an_invalid_project(root):
    src = _get(root, "/api/projects/proj/pipelines/etl/source").json()
    edited = src["content"] + "\n# a note\n"
    r = _client().put(
        "/api/projects/proj/pipelines/etl/source",
        params={"source": str(root)},
        json={"content": edited, "expected_version": src["version"]},
    )
    assert r.status_code == 200, r.text
    assert (root / "pipelines" / "etl.yaml").read_text() == edited

    bad = edited.replace("nodes:", "nodez:", 1)
    r = _client().put(
        "/api/projects/proj/pipelines/etl/source",
        params={"source": str(root)},
        json={"content": bad, "expected_version": r.json()["version"]},
    )
    assert r.status_code == 400
    assert (root / "pipelines" / "etl.yaml").read_text() == edited  # restored


def test_a_stale_version_is_a_conflict(root):
    src = _get(root, "/api/projects/proj/pipelines/etl/source").json()
    (root / "pipelines" / "etl.yaml").write_text(src["content"] + "\n# by hand\n")
    r = _client().put(
        "/api/projects/proj/pipelines/etl/source",
        params={"source": str(root)},
        json={"content": src["content"], "expected_version": src["version"]},
    )
    assert r.status_code == 409


def test_validate_reports_draft_problems_without_writing(root):
    before = (root / "pipelines" / "etl.yaml").read_text()
    draft = before.replace(
        "nodes:", "nodes:\n  extra:\n    run: nowhere:fn\n    descripton: x\n", 1
    )
    r = _client().post(
        "/api/projects/proj/validate",
        params={"source": str(root)},
        json={"files": {"pipelines/etl.yaml": draft}},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is False
    p = next(p for p in body["problems"] if p["code"] == "unknown_key")
    assert p["file"] == "pipelines/etl.yaml" and p["line"] and p["fix"]
    assert (root / "pipelines" / "etl.yaml").read_text() == before


def test_validate_checks_run_against_the_function(root):
    from ducta.api.repositories.v2_store import V2ProjectStore

    store = V2ProjectStore.detect(root)
    node, spec = next((n, s) for n, s in store.nodes().items() if s.get("module"))
    module_file = root / Path(*spec["module"].split(".")).with_suffix(".py")
    source = module_file.read_text()
    # Rename the function the node runs: the node now points at nothing.
    module_file.write_text(source.replace(f"def {spec['function']}(", "def renamed_away(", 1))
    r = _client().post("/api/projects/proj/validate", params={"source": str(root)}, json={})
    body = r.json()
    assert any(
        p["code"] == "function_not_found" and p["node"] == node and p["source"] == "code"
        for p in body["problems"]
    ), body


def test_validate_works_on_a_project_that_does_not_load(root):
    etl = root / "pipelines" / "etl.yaml"
    etl.write_text(etl.read_text().replace("nodes:", "nodez:", 1))
    r = _client().post("/api/projects/proj/validate", params={"source": str(root)}, json={})
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is False
    assert any(p["file"] == "pipelines/etl.yaml" for p in r.json()["problems"])


def test_a_broken_project_can_be_fixed_one_file_at_a_time(root):
    etl = root / "pipelines" / "etl.yaml"
    good = etl.read_text()
    etl.write_text(good.replace("nodes:", "nodez:", 1))
    # The file opens although the project does not load …
    src = _get(root, "/api/projects/proj/pipelines/etl/source")
    assert src.status_code == 200, src.text
    # … a write that adds a problem is still refused …
    worse = src.json()["content"] + "\nanother_bad_key: 1\n"
    r = _client().put(
        "/api/projects/proj/pipelines/etl/source",
        params={"source": str(root)},
        json={"content": worse, "expected_version": src.json()["version"]},
    )
    assert r.status_code == 400
    # … and the fix is accepted.
    r = _client().put(
        "/api/projects/proj/pipelines/etl/source",
        params={"source": str(root)},
        json={"content": good, "expected_version": src.json()["version"]},
    )
    assert r.status_code == 200, r.text
    assert etl.read_text() == good


def test_a_project_that_does_not_load_is_listed_as_invalid(root):
    etl = root / "pipelines" / "etl.yaml"
    etl.write_text(etl.read_text().replace("nodes:", "nodez:", 1))
    r = _get(root, "/api/projects")
    assert r.status_code == 200
    [project] = r.json()["projects"]
    assert project["id"] == "proj"
    assert project["config_status"] == "invalid"
    assert "nodez" in project["config_error"]
