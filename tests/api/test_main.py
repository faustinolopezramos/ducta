"""Smoke tests for the FastAPI app factory and the security-posture warning."""

from __future__ import annotations

import importlib.util

import pytest

from ducta.api.config import Settings
from ducta.api.main import create_app, warn_if_insecure_exposure


class TestInsecureExposureWarning:
    def test_warns_on_non_local_bind_without_auth(self):
        settings = Settings(environment="development", auth_enabled=False, host="0.0.0.0")
        assert warn_if_insecure_exposure(settings) is True

    def test_no_warning_on_localhost(self):
        settings = Settings(environment="development", auth_enabled=False, host="127.0.0.1")
        assert warn_if_insecure_exposure(settings) is False

    def test_no_warning_when_auth_enabled(self):
        settings = Settings(
            environment="development", auth_enabled=True, host="0.0.0.0", jwt_secret_key="x"
        )
        assert warn_if_insecure_exposure(settings) is False


class TestAppFactory:
    def test_create_app_returns_fastapi(self):
        app = create_app()
        assert app.title
        # Health route is registered. Assert against the OpenAPI schema rather
        # than app.routes: since FastAPI 0.140 include_router keeps a nested
        # router object instead of flattening sub-routes into app.routes, so
        # walking app.routes reports a false negative on any included router.
        assert "/health" in app.openapi()["paths"]


class TestHealthEndpoint:
    def test_health_returns_200(self):
        # starlette.testclient needs an HTTP client (httpx2 on newer Starlette,
        # httpx before that) and raises RuntimeError — not ImportError — when
        # neither is present, so importorskip on fastapi.testclient would
        # propagate instead of skipping. Check the client dependency first.
        if not any(importlib.util.find_spec(m) for m in ("httpx2", "httpx")):
            pytest.skip("neither httpx2 nor httpx installed (starlette TestClient dependency)")
        from fastapi.testclient import TestClient

        app = create_app()
        with TestClient(app) as client:
            resp = client.get("/health")
            assert resp.status_code == 200
