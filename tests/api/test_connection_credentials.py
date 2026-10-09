"""Connections of a format-2 project, and whether their credentials are set (never their values)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ducta.api.dependencies import get_current_user
from ducta.api.main import create_app
from ducta.api.models.auth import User
from ducta.gate.gateway.service import IngestionService


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "ducta.yaml").write_text(
        "version: 2\nproject: p\npaths: {input: d, output: d}\n"
        "settings:\n  ingestion: {sources_path: sources.yaml}\n"
    )
    (tmp_path / "sources.yaml").write_text(
        "sources:\n  crm:\n    type: postgresql\n    host: db\n    port: 5432\n    database: crm\n"
    )
    (tmp_path / ".env").write_text("CRM_USER=alice\nCRM_PASSWORD=\n")
    monkeypatch.delenv("CRM_USER", raising=False)
    monkeypatch.setenv("CRM_PASSWORD", "s3cret")
    return tmp_path


def test_the_sources_file_is_the_one_the_engine_reads(project):
    assert [c["name"] for c in IngestionService(project).list_connections()] == ["crm"]


def test_credentials_say_where_they_are_set_and_never_what(project):
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: User(
        id="a", username="a", email="a@example.com", roles=["admin"]
    )
    r = TestClient(app).get(
        "/api/ingestion/connections/crm/credentials", params={"source": str(project)}
    )
    assert r.status_code == 200, r.text
    assert r.json()["variables"] == [
        {"name": "CRM_USER", "set": True, "where": ".env"},
        {"name": "CRM_PASSWORD", "set": True, "where": "environment"},
    ]
    assert "alice" not in r.text and "s3cret" not in r.text
