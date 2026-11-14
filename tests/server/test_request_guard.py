"""The Host + Origin guard: DNS rebinding and cross-site state changes are refused.

Both were proven against a live server before the guard existed: with
``Host: attacker.example`` (what a rebound DNS name sends) a page read catalog
files and wrote a pipeline module, and a form-encoded cross-site ``POST`` ran
``git pull``.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI, WebSocket  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from loguru import logger  # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402

from ducta_server.config import Settings  # noqa: E402
from ducta_server.middleware import register_middleware  # noqa: E402
from ducta_server.middleware.origin import (  # noqa: E402
    allowed_host_patterns,
    host_name,
    is_allowed_host,
)

EVIL_ORIGIN = "https://evil.example"


def _settings(monkeypatch, **overrides) -> Settings:
    overrides.setdefault("allowed_hosts", [])
    settings = Settings(**overrides)
    monkeypatch.setattr("ducta_server.config.get_settings", lambda: settings)
    monkeypatch.setattr("ducta_server.middleware.get_settings", lambda: settings)
    return settings


def _client(monkeypatch, **overrides) -> TestClient:
    _settings(monkeypatch, **overrides)
    app = FastAPI()

    @app.get("/api/read")
    async def read():  # pragma: no cover - exercised through the client
        return {"ok": True}

    @app.put("/api/write")
    async def write():  # pragma: no cover
        return {"ok": True}

    @app.post("/api/act")
    async def act():  # pragma: no cover
        return {"ok": True}

    @app.websocket("/ws/logs")
    async def logs(websocket: WebSocket):  # pragma: no cover
        await websocket.accept()
        await websocket.send_text("hello")
        await websocket.close()

    register_middleware(app)
    return TestClient(app)


class TestHostName:
    @pytest.mark.parametrize(
        "header, name",
        [
            ("localhost:8000", "localhost"),
            ("127.0.0.1", "127.0.0.1"),
            ("[::1]:8000", "::1"),
            ("[::1]", "::1"),
            ("Ducta.LAN:80", "ducta.lan"),
        ],
    )
    def test_parses(self, header, name):
        assert host_name(header) == name

    @pytest.mark.parametrize("header", [None, "", "[::1", "a b", "evil.example/x", "[::1]x"])
    def test_malformed(self, header):
        assert host_name(header) is None


class TestPatterns:
    def test_loopback_bind_checks_loopback_names(self):
        patterns = allowed_host_patterns(Settings(host="127.0.0.1", allowed_hosts=[]))
        assert patterns is not None
        assert {"localhost", "127.0.0.1", "::1"} <= set(patterns)

    def test_wildcard_bind_without_list_checks_nothing(self):
        assert allowed_host_patterns(Settings(host="0.0.0.0", allowed_hosts=[])) is None

    def test_wildcard_bind_with_list_checks_it(self):
        patterns = allowed_host_patterns(Settings(host="0.0.0.0", allowed_hosts=["ducta.lan"]))
        assert is_allowed_host("ducta.lan:8000", patterns)
        assert not is_allowed_host("attacker.example:8000", patterns)

    def test_star_disables_the_check(self):
        assert allowed_host_patterns(Settings(allowed_hosts=["*"])) is None

    def test_subdomain_pattern(self):
        patterns = allowed_host_patterns(Settings(allowed_hosts=["*.company.com"]))
        assert is_allowed_host("ducta.company.com", patterns)
        assert not is_allowed_host("company.com.evil.example", patterns)
        assert not is_allowed_host("evilcompany.com", patterns)


class TestRebinding:
    """``Host: attacker.example`` is what a page reaching 127.0.0.1 through its own name sends."""

    HEADERS = {"Host": "attacker.example:8000", "Origin": "http://attacker.example:8000"}

    def test_read_is_refused(self, monkeypatch):
        response = _client(monkeypatch).get("/api/read", headers=self.HEADERS)
        assert response.status_code == 400

    def test_write_is_refused(self, monkeypatch):
        response = _client(monkeypatch).put("/api/write", headers=self.HEADERS)
        assert response.status_code == 400

    def test_websocket_is_refused_before_accept(self, monkeypatch):
        client = _client(monkeypatch)
        with pytest.raises(WebSocketDisconnect) as closed:
            with client.websocket_connect("/ws/logs", headers=self.HEADERS) as ws:
                ws.receive_text()
        assert closed.value.code == 1008

    @pytest.mark.parametrize("host", ["localhost:8000", "127.0.0.1:8000", "[::1]:8000"])
    def test_loopback_names_pass(self, monkeypatch, host):
        response = _client(monkeypatch).get("/api/read", headers={"Host": host})
        assert response.status_code == 200

    def test_websocket_on_loopback_passes(self, monkeypatch):
        client = _client(monkeypatch)
        with client.websocket_connect(
            "/ws/logs", headers={"Host": "127.0.0.1:8000", "Origin": "http://127.0.0.1:8000"}
        ) as ws:
            assert ws.receive_text() == "hello"

    def test_a_declared_name_passes(self, monkeypatch):
        client = _client(monkeypatch, allowed_hosts=["ducta.lan"])
        assert client.get("/api/read", headers={"Host": "ducta.lan"}).status_code == 200

    def test_the_bind_host_passes(self, monkeypatch):
        client = _client(monkeypatch, host="192.168.1.20")
        assert client.get("/api/read", headers={"Host": "192.168.1.20:8000"}).status_code == 200

    def test_wildcard_bind_without_list_answers_any_host(self, monkeypatch):
        client = _client(monkeypatch, host="0.0.0.0")
        assert client.get("/api/read", headers=self.HEADERS).status_code == 200


class TestCrossSiteStateChange:
    def test_foreign_origin_post_is_refused(self, monkeypatch):
        response = _client(monkeypatch).post(
            "/api/act",
            headers={
                "Host": "127.0.0.1:8000",
                "Origin": EVIL_ORIGIN,
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        assert response.status_code == 403

    @pytest.mark.parametrize("origin", ["http://127.0.0.1:8000", "http://localhost:5173", None])
    def test_own_listed_or_missing_origin_passes(self, monkeypatch, origin):
        headers = {"Host": "127.0.0.1:8000"}
        if origin:
            headers["Origin"] = origin
        response = _client(monkeypatch).post("/api/act", headers=headers)
        assert response.status_code == 200

    def test_foreign_origin_get_is_not_refused(self, monkeypatch):
        """Reading is CORS's job: the response is not shared with the page."""
        response = _client(monkeypatch).get(
            "/api/read", headers={"Host": "127.0.0.1:8000", "Origin": EVIL_ORIGIN}
        )
        assert response.status_code == 200
        assert response.headers.get("access-control-allow-origin") != EVIL_ORIGIN

    def test_preflight_is_not_refused(self, monkeypatch):
        response = _client(monkeypatch).options(
            "/api/act",
            headers={
                "Host": "127.0.0.1:8000",
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert response.status_code == 200

    def test_the_real_git_pull_route_is_guarded(self, monkeypatch):
        """The route proven exploitable in the review: refused before it runs."""
        _settings(monkeypatch)
        from ducta_server.main import app

        response = TestClient(app).post(
            "/api/git/pull",
            headers={
                "Host": "127.0.0.1:8000",
                "Origin": EVIL_ORIGIN,
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        assert response.status_code == 403


class TestStartupWarnings:
    @pytest.fixture
    def messages(self):
        captured: list = []
        logger.enable("ducta")
        sink = logger.add(lambda m: captured.append(str(m)), level="INFO")
        yield captured
        logger.remove(sink)
        logger.disable("ducta")

    def test_hosts_unchecked_warns_on_wildcard_bind(self, messages):
        from ducta_server.main import warn_if_hosts_unchecked

        assert warn_if_hosts_unchecked(Settings(host="0.0.0.0", allowed_hosts=[]))
        assert any("ALLOWED_HOSTS" in m for m in messages)

    def test_hosts_checked_does_not_warn(self, messages):
        from ducta_server.main import warn_if_hosts_unchecked

        assert not warn_if_hosts_unchecked(Settings(host="127.0.0.1", allowed_hosts=[]))
        assert not warn_if_hosts_unchecked(Settings(host="0.0.0.0", allowed_hosts=["ducta.lan"]))
        assert messages == []

    def test_in_process_runs_note_only_with_accounts(self, messages, monkeypatch):
        from ducta_server.main import warn_about_in_process_runs

        assert not warn_about_in_process_runs(Settings(auth_enabled=False))
        assert messages == []
        settings = Settings(auth_enabled=False, run_isolation="thread")
        monkeypatch.setattr(settings, "auth_enabled", True)
        assert warn_about_in_process_runs(settings)
        assert any("JWT_SECRET_KEY" in m and "developer" in m for m in messages)

    def test_runs_in_their_own_process_get_a_different_note(self, messages, monkeypatch):
        from ducta_server.execution import child_runner
        from ducta_server.main import warn_about_in_process_runs

        monkeypatch.setattr(child_runner, "protect_server_process", lambda: False)
        settings = Settings(auth_enabled=False)  # auto: process once accounts are on
        monkeypatch.setattr(settings, "auth_enabled", True)
        assert warn_about_in_process_runs(settings)
        assert not any("developer" in m for m in messages)
        assert any("own process" in m and "same OS user" in m for m in messages)


class TestContentSecurityPolicy:
    """One strict policy everywhere: the packaged UI served by `ducta ui` got `default-src *`."""

    @pytest.mark.parametrize("production", [False, True])
    def test_no_wildcard_and_no_eval(self, production):
        from ducta_server.middleware import content_security_policy

        csp = content_security_policy(production)
        assert "default-src 'self'" in csp
        assert "*" not in csp
        assert "'unsafe-eval'" not in csp
        assert "script-src 'self' 'wasm-unsafe-eval';" in csp
        assert "'unsafe-inline'" not in csp.split("script-src", 1)[1].split(";", 1)[0]

    def test_only_framing_differs(self):
        from ducta_server.middleware import content_security_policy

        assert content_security_policy(True).endswith("frame-ancestors 'none'")
        assert content_security_policy(False).endswith("frame-ancestors 'self'")

    def test_local_server_sends_it(self, monkeypatch):
        response = _client(monkeypatch).get("/api/read", headers={"Host": "127.0.0.1:8000"})
        csp = response.headers["content-security-policy"]
        assert "default-src 'self'" in csp
        assert "'unsafe-eval'" not in csp
