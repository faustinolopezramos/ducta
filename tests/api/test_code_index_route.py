"""`GET /api/projects/{id}/code-index`: node ↔ function, read from the syntax tree."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from ducta.api.dependencies import get_current_user
from ducta.api.main import create_app
from ducta.api.models.auth import User
from ducta.api.services.code_index import top_level_functions


def _client() -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: User(
        id="viewer", username="viewer", email="viewer@example.com", roles=["viewer"]
    )
    return TestClient(app)


def _project(tmp_path: Path, monkeypatch) -> Path:
    from ducta.console.template import TemplateGenerator, TemplateType

    monkeypatch.chdir(tmp_path)
    root = tmp_path / "proj"
    TemplateGenerator(root).generate_project(TemplateType.MEDALLION_BASIC, "proj")
    return root


def test_each_node_points_at_its_function(tmp_path, monkeypatch):
    root = _project(tmp_path, monkeypatch)
    r = _client().get("/api/projects/proj/code-index", params={"source": str(root)})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["nodes"], body
    for entry in body["nodes"]:
        source = (root / entry["file"]).read_text()
        assert entry["exists"] is True
        assert entry["pipeline"]
        # The line really is the function's `def`.
        assert (
            source.splitlines()[entry["line"] - 1]
            .lstrip()
            .startswith(("def " + entry["function"], "async def " + entry["function"]))
        )
        assert entry["file"] in body["files"]


def test_it_does_not_import_the_project(tmp_path, monkeypatch):
    root = _project(tmp_path, monkeypatch)
    first = _client().get("/api/projects/proj/code-index", params={"source": str(root)}).json()
    target = root / first["nodes"][0]["file"]
    target.write_text("raise SystemExit('imported!')\n" + target.read_text())
    r = _client().get("/api/projects/proj/code-index", params={"source": str(root)})
    assert r.status_code == 200
    assert r.json()["nodes"][0]["line"] == first["nodes"][0]["line"] + 1


def test_unparseable_source_has_no_functions():
    assert top_level_functions("def broken(:\n") == []
    [fn] = top_level_functions("def f(a, b, *, c):\n    'doc'\n")
    assert (fn.name, fn.line, fn.params, fn.docstring) == ("f", 1, ["a", "b", "c"], "doc")
