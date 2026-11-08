"""The `/api/ingestion/connections` routes on a real project.

Creating writes ``sources.yaml`` and the password to ``.env``; no read route
returns a credential. Connectivity is decided by ``JDBCConnector.test_connection``,
replaced here so no database (and no Spark) is needed.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

PASSWORD = "s3cret-Pa55"


def _conn(**overrides):
    body = {
        "name": "warehouse",
        "type": "postgresql",
        "host": "db.internal",
        "port": 5432,
        "database": "sales",
        "username": "reader",
        "password": PASSWORD,
    }
    body.update(overrides)
    return body


@pytest.fixture
def project(tmp_path, monkeypatch):
    from ducta.console.templates import TemplateGenerator, TemplateType

    monkeypatch.chdir(tmp_path)
    for var in ("WAREHOUSE_USER", "WAREHOUSE_PASSWORD"):
        monkeypatch.delenv(var, raising=False)
    root = tmp_path / "proj"
    TemplateGenerator(root).generate_project(TemplateType.MEDALLION_BASIC, "proj")
    return root


@pytest.fixture
def answers(monkeypatch):
    """What the database "answers" to a connection test: True, False or None."""
    from ducta.gate.gateway.connector import JDBCConnector

    state = {"result": True, "tested": []}

    def fake_test(self, timeout_seconds=10):
        state["tested"].append((self.host, self.port))
        return state["result"]

    monkeypatch.setattr(JDBCConnector, "test_connection", fake_test)
    return state


@pytest.fixture
def api(project) -> TestClient:
    from ducta.api.main import create_app

    class _NoRuns:
        def list_executions_paginated(self, **kwargs):
            return [], 0

    app = create_app()
    app.state.execution_manager = _NoRuns()  # the lifespan (which builds the real one) does not run
    client = TestClient(app)
    client.params = {"source": str(project)}  # type: ignore[assignment]
    return client


class TestCreateReadDelete:
    def test_create_list_get_and_no_credential_comes_back(self, api, project):
        created = api.post("/api/ingestion/connections", json=_conn())
        assert created.status_code == 201
        assert PASSWORD not in created.text

        listed = api.get("/api/ingestion/connections")
        assert [c["name"] for c in listed.json()["connections"]] == ["warehouse"]
        one = api.get("/api/ingestion/connections/warehouse")
        assert (one.json()["host"], one.json()["port"]) == ("db.internal", 5432)
        for response in (created, listed, one):
            assert PASSWORD not in response.text

        assert PASSWORD in (project / ".env").read_text(encoding="utf-8")

    def test_credentials_say_where_not_what(self, api):
        api.post("/api/ingestion/connections", json=_conn())
        body = api.get("/api/ingestion/connections/warehouse/credentials").json()
        assert {v["name"]: v["where"] for v in body["variables"]} == {
            "WAREHOUSE_USER": ".env",
            "WAREHOUSE_PASSWORD": ".env",
        }
        assert PASSWORD not in str(body)

    def test_a_duplicate_needs_overwrite(self, api):
        api.post("/api/ingestion/connections", json=_conn())
        assert api.post("/api/ingestion/connections", json=_conn()).status_code == 422
        replaced = api.post(
            "/api/ingestion/connections", json=_conn(host="db2.internal", overwrite=True)
        )
        assert (replaced.status_code, replaced.json()["host"]) == (201, "db2.internal")

    def test_an_invalid_spec_is_422(self, api):
        assert api.post("/api/ingestion/connections", json=_conn(type="nosql")).status_code == 422
        bad_name = api.post("/api/ingestion/connections", json=_conn(name="has space"))
        assert bad_name.status_code == 422

    def test_delete_then_everything_is_404(self, api):
        api.post("/api/ingestion/connections", json=_conn())
        assert api.delete("/api/ingestion/connections/warehouse").status_code == 204
        for path in ("", "/credentials", "/usage"):
            assert api.get(f"/api/ingestion/connections/warehouse{path}").status_code == 404
        assert api.delete("/api/ingestion/connections/warehouse").status_code == 404


class TestConnectivity:
    def test_a_saved_connection_is_tested_with_its_stored_settings(self, api, answers):
        api.post("/api/ingestion/connections", json=_conn())
        body = api.post("/api/ingestion/connections/warehouse/test").json()
        assert body == {"ok": True, "message": "Connection verified"}
        assert answers["tested"] == [("db.internal", 5432)]

    def test_a_refused_connection_says_failed(self, api, answers):
        answers["result"] = False
        api.post("/api/ingestion/connections", json=_conn())
        body = api.post("/api/ingestion/connections/warehouse/test").json()
        assert body["ok"] is False and body["message"].startswith("Connection failed")

    def test_an_unknown_saved_connection_is_404(self, api, answers):
        assert api.post("/api/ingestion/connections/ghost/test").status_code == 404

    def test_an_unsaved_spec(self, api, answers, project):
        answers["result"] = None
        spec = {k: v for k, v in _conn().items() if k != "name"}
        body = api.post("/api/ingestion/connections/test", json=spec).json()
        assert body["ok"] is False and body["message"].startswith("Not verified")
        assert not (project / ".env").exists() or PASSWORD not in (project / ".env").read_text()

    def test_an_unsaved_invalid_spec_is_422(self, api, answers):
        spec = {k: v for k, v in _conn(type="nosql").items() if k != "name"}
        assert api.post("/api/ingestion/connections/test", json=spec).status_code == 422
        assert answers["tested"] == []


class TestUsage:
    def test_pipelines_whose_code_names_the_connection(self, api, project):
        api.post("/api/ingestion/connections", json=_conn())
        etl = project / "pipelines" / "etl.py"
        etl.write_text(
            etl.read_text(encoding="utf-8") + '\n# reads ConnectionManager().get("warehouse")\n',
            encoding="utf-8",
        )

        body = api.get("/api/ingestion/connections/warehouse/usage").json()
        assert body == {"pipelines": ["etl"], "executions": []}


def test_a_viewer_reads_but_cannot_create_or_probe(api, answers):
    from ducta.api.dependencies import get_current_user
    from ducta.api.models.auth import User

    api.post("/api/ingestion/connections", json=_conn())
    api.app.dependency_overrides[get_current_user] = lambda: User(
        id="v", username="v", email="v@example.com", roles=["viewer"]
    )
    assert api.get("/api/ingestion/connections").status_code == 200
    assert api.post("/api/ingestion/connections", json=_conn(name="other")).status_code == 403
    spec = {k: v for k, v in _conn().items() if k != "name"}
    assert api.post("/api/ingestion/connections/test", json=spec).status_code == 403
    assert answers["tested"] == []
