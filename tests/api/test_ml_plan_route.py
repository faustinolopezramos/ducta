"""`GET /api/projects/{id}/pipelines/{name}/ml-plan`: `ducta config show --ml` for the UI."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ducta.api.dependencies import get_current_user
from ducta.api.main import create_app
from ducta.api.models.auth import User


def _client(role: str) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: User(
        id=role, username=role, email=f"{role}@example.com", roles=[role]
    )
    return TestClient(app)


def _project(tmp_path: Path, monkeypatch, kind) -> Path:
    from ducta.console.template import TemplateGenerator

    monkeypatch.chdir(tmp_path)  # the server's source confinement base
    root = tmp_path / "proj"
    TemplateGenerator(root).generate_project(kind, "proj")
    return root


@pytest.fixture
def ml_project(tmp_path, monkeypatch) -> Path:
    from ducta.console.template import TemplateType

    return _project(tmp_path, monkeypatch, TemplateType.ML_BASIC)


def _url(name: str) -> str:
    return f"/api/projects/proj/pipelines/{name}/ml-plan"


def test_it_says_what_each_ml_node_is_given(ml_project):
    r = _client("viewer").get(_url("churn_model"), params={"source": str(ml_project)})
    assert r.status_code == 200, r.text  # reads configuration only: a viewer may look
    body = r.json()
    assert body["pipeline"] == "churn_model"
    assert body["type"] == "ml"
    assert body["split_enforcement"] == "error"
    train = body["nodes"]["train"]
    assert train["ml_stage"] == "training"
    assert train["split"]["method"] == "stratified"
    assert train["split_from"] == "pipeline"
    assert train["must_apply_split"] is True
    # a feature node receives the split but is not bound to it
    assert body["nodes"]["prepare_features"]["must_apply_split"] is False


def test_a_pipeline_without_ml_has_no_nodes(tmp_path, monkeypatch):
    from ducta.console.template import TemplateType

    root = _project(tmp_path, monkeypatch, TemplateType.MEDALLION_BASIC)
    r = _client("viewer").get(_url("etl"), params={"source": str(root)})
    assert r.status_code == 200, r.text
    assert r.json()["nodes"] == {}


def test_an_unknown_pipeline_is_a_404(ml_project):
    r = _client("viewer").get(_url("nope"), params={"source": str(ml_project)})
    assert r.status_code == 404


def test_a_bad_environment_name_is_a_400(ml_project):
    r = _client("viewer").get(
        _url("churn_model"), params={"source": str(ml_project), "env": "../etc"}
    )
    assert r.status_code == 400
