"""CORS policy regression tests.

The API binds to loopback and runs unauthenticated by default, which is a fine
local-first posture *only* while a web page cannot drive it. Wildcard origin plus
credentials breaks exactly that: Starlette then reflects any Origin back with
`Access-Control-Allow-Credentials: true`, so any site the developer visits can
read responses from 127.0.0.1 — enumerate the workspace, write files into it via
`PUT /api/workspace/files/content`, and launch a pipeline that executes them.

Development used to be exempt from the downgrade, and development is the default.
"""

from __future__ import annotations

import pytest

from ducta.api.config import Settings

fastapi = pytest.importorskip("fastapi", reason="CORS tests require the api extra")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from ducta.api.middleware import register_middleware  # noqa: E402

EVIL = "https://evil.example.com"


def _client(monkeypatch, **overrides):
    """Build a minimal app whose middleware is configured from `overrides`."""
    settings = Settings(**overrides)
    monkeypatch.setattr("ducta.api.middleware.get_settings", lambda: settings)

    app = FastAPI()

    @app.get("/probe")
    async def probe():  # pragma: no cover - exercised through the client
        return {"ok": True}

    register_middleware(app)
    return TestClient(app)


class TestDefaults:
    def test_default_origins_are_an_explicit_allow_list(self):
        assert "*" not in Settings().cors_origins

    def test_default_origins_are_loopback_only(self):
        for origin in Settings().cors_origins:
            assert origin.startswith(("http://localhost:", "http://127.0.0.1:")), origin

    def test_unlisted_origin_is_not_reflected_by_default(self, monkeypatch):
        response = _client(monkeypatch).get("/probe", headers={"Origin": EVIL})

        assert response.headers.get("access-control-allow-origin") != EVIL

    def test_listed_origin_is_allowed_with_credentials(self, monkeypatch):
        allowed = Settings().cors_origins[0]
        response = _client(monkeypatch).get("/probe", headers={"Origin": allowed})

        assert response.headers.get("access-control-allow-origin") == allowed
        assert response.headers.get("access-control-allow-credentials") == "true"


class TestWildcardDowngrade:
    @pytest.mark.parametrize("environment", ["development", "staging", "production"])
    def test_wildcard_never_reflects_credentials(self, monkeypatch, environment):
        """Development is not an exemption — that is where the risk actually lives."""
        overrides = {
            "environment": environment,
            "cors_origins": ["*"],
            "cors_allow_credentials": True,
        }
        if environment == "production":
            overrides |= {"jwt_secret_key": "a-strong-secret", "auth_enabled": True}

        response = _client(monkeypatch, **overrides).get("/probe", headers={"Origin": EVIL})

        assert response.headers.get("access-control-allow-credentials") != "true"
        assert response.headers.get("access-control-allow-origin") != EVIL

    def test_wildcard_preflight_does_not_authorize_credentialed_writes(self, monkeypatch):
        client = _client(
            monkeypatch,
            environment="development",
            cors_origins=["*"],
            cors_allow_credentials=True,
        )
        response = client.options(
            "/probe",
            headers={
                "Origin": EVIL,
                "Access-Control-Request-Method": "PUT",
                "Access-Control-Request-Headers": "content-type",
            },
        )

        assert response.headers.get("access-control-allow-credentials") != "true"
