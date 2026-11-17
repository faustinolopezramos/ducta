"""Smoke tests for the FastAPI app factory and the security-posture warning."""

from __future__ import annotations

import importlib.util

import pytest

from ducta_server.config import Settings
from ducta_server.main import check_default_credentials, create_app, warn_if_insecure_exposure


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


class TestDefaultCredentials:
    """Accounts on with the published JWT key / admin password: refused where others connect."""

    @staticmethod
    def _auth(host, **kw):
        return Settings(environment="development", auth_enabled=True, host=host, **kw)

    def test_exposed_with_default_secret_refuses(self, monkeypatch):
        monkeypatch.setenv("DUCTA_ADMIN_PASSWORD", "a-real-password")
        with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
            check_default_credentials(self._auth("0.0.0.0"))

    def test_exposed_with_default_admin_password_refuses(self, monkeypatch):
        monkeypatch.delenv("DUCTA_ADMIN_PASSWORD", raising=False)
        with pytest.raises(RuntimeError, match="DUCTA_ADMIN_PASSWORD"):
            check_default_credentials(self._auth("0.0.0.0", jwt_secret_key="a-strong-secret"))

    def test_admin_password_admin_refuses(self, monkeypatch):
        monkeypatch.setenv("DUCTA_ADMIN_PASSWORD", "admin")
        with pytest.raises(RuntimeError, match="DUCTA_ADMIN_PASSWORD"):
            check_default_credentials(self._auth("0.0.0.0", jwt_secret_key="a-strong-secret"))

    def test_empty_host_counts_as_exposed(self, monkeypatch):
        monkeypatch.delenv("DUCTA_ADMIN_PASSWORD", raising=False)
        with pytest.raises(RuntimeError):
            check_default_credentials(self._auth("", jwt_secret_key="a-strong-secret"))

    def test_loopback_only_warns(self, monkeypatch):
        monkeypatch.delenv("DUCTA_ADMIN_PASSWORD", raising=False)
        assert check_default_credentials(self._auth("127.0.0.1")) is True

    def test_own_credentials_are_silent(self, monkeypatch):
        monkeypatch.setenv("DUCTA_ADMIN_PASSWORD", "a-real-password")
        settings = self._auth("0.0.0.0", jwt_secret_key="a-strong-secret")
        assert check_default_credentials(settings) is False

    def test_auth_off_has_nothing_to_check(self, monkeypatch):
        monkeypatch.delenv("DUCTA_ADMIN_PASSWORD", raising=False)
        settings = Settings(environment="development", auth_enabled=False, host="0.0.0.0")
        assert check_default_credentials(settings) is False

    def test_exposed_seed_rejects_admin_admin(self, monkeypatch):
        """The store itself refuses the default password where others connect (not only production)."""
        from ducta_server.auth.security import resolve_admin_password

        settings = self._auth("0.0.0.0", jwt_secret_key="a-strong-secret")
        assert settings.requires_strong_credentials() is True
        with pytest.raises(RuntimeError, match="DUCTA_ADMIN_PASSWORD"):
            resolve_admin_password(None, strict=settings.requires_strong_credentials())
        local = self._auth("127.0.0.1", jwt_secret_key="a-strong-secret")
        assert resolve_admin_password(None, strict=local.requires_strong_credentials()) == "admin"


class TestLauncherRefusesDefaultCredentials:
    def test_exposed_default_credentials_refused(self, monkeypatch):
        from ducta_server.config import get_settings
        from ducta_server.launcher import refuse_open_bind

        monkeypatch.setenv("AUTH_ENABLED", "true")
        monkeypatch.setenv("HOST", "0.0.0.0")
        monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
        monkeypatch.delenv("DUCTA_ADMIN_PASSWORD", raising=False)
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        get_settings.cache_clear()
        try:
            reason = refuse_open_bind("0.0.0.0", allow_unauthenticated=False)
            assert reason is not None and "default credentials" in reason
            assert refuse_open_bind("127.0.0.1", allow_unauthenticated=False) is None
            monkeypatch.setenv("JWT_SECRET_KEY", "a-strong-secret")
            monkeypatch.setenv("DUCTA_ADMIN_PASSWORD", "a-real-password")
            get_settings.cache_clear()
            assert refuse_open_bind("0.0.0.0", allow_unauthenticated=False) is None
        finally:
            get_settings.cache_clear()


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
            # The server's own version and the engine's: the same minor, maybe not patch.
            import ducta
            import ducta_server

            body = resp.json()
            assert body["version"] == ducta_server.__version__
            assert body["engine_version"] == ducta.__version__
