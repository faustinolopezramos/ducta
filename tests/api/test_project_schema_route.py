"""`GET /api/projects/{id}/schema`: the format-2 JSON Schema, for the editor."""

from __future__ import annotations

from fastapi.testclient import TestClient

from ducta.api.dependencies import get_current_user
from ducta.api.main import create_app
from ducta.api.models.auth import User


def _client() -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: User(
        id="viewer", username="viewer", email="viewer@example.com", roles=["viewer"]
    )
    return TestClient(app)


def test_it_serves_the_format_2_schema(tmp_path, monkeypatch):
    from ducta.console.template import TemplateGenerator, TemplateType

    monkeypatch.chdir(tmp_path)
    root = tmp_path / "proj"
    TemplateGenerator(root).generate_project(TemplateType.MEDALLION_BASIC, "proj")
    r = _client().get("/api/projects/proj/schema", params={"source": str(root)})
    assert r.status_code == 200, r.text
    body = r.json()
    assert {"project", "pipeline", "catalog"} <= set(body["$defs"])


def test_an_unknown_project_is_a_404(tmp_path, monkeypatch):
    from ducta.console.template import TemplateGenerator, TemplateType

    monkeypatch.chdir(tmp_path)
    root = tmp_path / "proj"
    TemplateGenerator(root).generate_project(TemplateType.MEDALLION_BASIC, "proj")
    r = _client().get("/api/projects/nope/schema", params={"source": str(root)})
    assert r.status_code == 404
