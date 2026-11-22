"""Requests that named something that does not exist were accepted, then failed later.

A schedule for a missing pipeline was stored (201) and failed at every trigger; an execution
in an environment named ``../../x`` was accepted (202) and failed a moment after.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ducta.console.templates import TemplateGenerator, TemplateType
from ducta_server.dependencies import get_current_user
from ducta_server.main import create_app
from ducta_server.models.auth import User


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "proj"
    TemplateGenerator(root).generate_project(TemplateType.MEDALLION_BASIC, "proj")
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: User(
        id="admin", username="admin", email="admin@example.com", roles=["admin"]
    )
    with TestClient(app) as c:  # the lifespan creates the execution manager
        c.params = {"source": str(root)}  # type: ignore[assignment]
        project = c.get("/api/projects").json()["projects"][0]["id"]
        yield c, project


def test_a_schedule_for_a_missing_pipeline_is_refused(client):
    c, project = client
    r = c.post(
        "/api/schedules",
        json={"pipeline_name": "nope", "cron": "0 6 * * *", "env": "dev", "project_id": project},
    )
    assert r.status_code == 404
    assert c.get("/api/schedules").json()["count"] == 0


def test_a_schedule_for_an_existing_pipeline_is_created(client):
    c, project = client
    r = c.post(
        "/api/schedules",
        json={"pipeline_name": "etl", "cron": "0 6 * * *", "env": "dev", "project_id": project},
    )
    assert r.status_code == 201


@pytest.mark.parametrize("env", ["../../x", "a/b", "", "x" * 80, "a b"])
def test_an_invalid_environment_is_a_422_everywhere(client, env):
    c, project = client
    execute = c.post(f"/api/projects/{project}/pipelines/etl/execute", json={"env": env})
    assert execute.status_code == 422
    schedule = c.post(
        "/api/schedules",
        json={"pipeline_name": "etl", "cron": "0 6 * * *", "env": env, "project_id": project},
    )
    assert schedule.status_code == 422


def test_the_usual_environments_still_run(client):
    c, project = client
    for env in ("base", "dev", "prod", "sandbox_ana"):
        r = c.post(
            f"/api/projects/{project}/pipelines/etl/execute",
            json={"env": env, "validate_only": True},
        )
        assert r.status_code == 202, (env, r.text)


@pytest.mark.parametrize("bad", ["%00", "a" * 300, "%E2%82%AC", "x'%3B--"])
def test_junk_ids_are_client_errors_not_500s(client, bad):
    c, project = client
    paths = [
        f"/api/projects/{bad}/certificates/abc",
        f"/api/projects/{project}/certificates/{bad}",
        f"/api/quality/trend/{bad}",
        f"/api/quality/score/{bad}",
    ]
    for path in paths:
        status = c.get(path).status_code
        # a valid but unknown name may be a 200 "no history"; what must not happen is a 500
        assert status < 500, (path, status)


@pytest.mark.parametrize("web_app_built", [True, False], ids=["with-web-app", "api-only"])
def test_the_api_docs_are_not_served_to_anonymous_visitors_when_accounts_are_on(
    tmp_path, monkeypatch, web_app_built
):
    import ducta_server.main as server_main
    from ducta_server.config import get_settings

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("JWT_SECRET_KEY", "0123456789abcdef0123456789abcdef0123456789abcdef")
    monkeypatch.setenv("DUCTA_ADMIN_PASSWORD", "S3cure-pass-123!")
    if not web_app_built:
        # A source checkout (CI) has no ui_dist: switched off, the paths are a JSON 404.
        monkeypatch.setattr(server_main, "_UI_DIR", tmp_path / "no-ui-dist")

    def served(response) -> bool:
        """Swagger UI, ReDoc or the OpenAPI schema — not the web app's page nor a 404."""
        if response.status_code != 200:
            return False
        body = response.text.lower()
        if "swagger" in body or "redoc" in body:
            return True
        try:
            return "openapi" in response.json()
        except ValueError:
            return False

    def statuses(auth: str, debug: str) -> list:
        monkeypatch.setenv("AUTH_ENABLED", auth)
        monkeypatch.setenv("DEBUG", debug)
        get_settings.cache_clear()
        try:
            c = TestClient(create_app(), base_url="http://127.0.0.1:8000")
            return [served(c.get(p)) for p in ("/docs", "/redoc", "/openapi.json")]
        finally:
            get_settings.cache_clear()

    assert statuses("false", "false") == [True, True, True]
    assert statuses("true", "false") == [False, False, False]
    assert statuses("true", "true") == [True, True, True]
