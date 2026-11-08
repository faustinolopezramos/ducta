"""The editor's WebSockets: who is refused, and the debugger's bridge to debugpy.

The LSP bridge itself is covered in ``test_language_server.py``; here are the
handshake refusals of both sockets, and a debug session relayed to a stand-in
debugpy that speaks the Debug Adapter Protocol's framing.
"""

from __future__ import annotations

import json
import socket
import threading

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402

from ducta.api.config import Settings, get_settings  # noqa: E402
from ducta.api.dependencies import get_current_user  # noqa: E402
from ducta.api.main import create_app  # noqa: E402
from ducta.api.models.auth import User  # noqa: E402
from ducta.api.services.language_server import frame  # noqa: E402


@pytest.fixture
def project(tmp_path, monkeypatch):
    from ducta.console.templates import TemplateGenerator, TemplateType

    monkeypatch.chdir(tmp_path)
    root = tmp_path / "proj"
    TemplateGenerator(root).generate_project(TemplateType.MEDALLION_BASIC, "proj")
    return root


class _Run:
    def __init__(self, port):
        self.debug_port = port


class _Manager:
    def __init__(self, port=None):
        self.port = port
        self.attached: list = []

    def get_execution(self, execution_id):
        if execution_id != "run-1":
            raise KeyError(execution_id)
        return _Run(self.port)

    def mark_debug_attached(self, execution_id):
        self.attached.append(execution_id)


def _client(manager=None, settings=None) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: User(
        id="admin", username="admin", email="admin@example.com", roles=["admin"]
    )
    if settings is not None:
        app.dependency_overrides[get_settings] = lambda: settings
    app.state.execution_manager = manager or _Manager()
    return TestClient(app)


def _refused(client, url):
    with pytest.raises(WebSocketDisconnect) as closed:
        with client.websocket_connect(url) as ws:
            ws.receive_text()
    return closed.value


class _FakeDebugpy:
    """Accepts one connection; answers each framed request with a framed response."""

    def __init__(self):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.received: list = []
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        conn, _ = self.sock.accept()
        with conn:
            buffer = b""
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    return
                buffer += chunk
                while b"\r\n\r\n" in buffer:
                    header, rest = buffer.split(b"\r\n\r\n", 1)
                    length = int(header.split(b":")[1])
                    if len(rest) < length:
                        break
                    body, buffer = rest[:length], rest[length:]
                    request = json.loads(body)
                    self.received.append(request)
                    reply = {"type": "response", "request_seq": request["seq"], "success": True}
                    conn.sendall(frame(json.dumps(reply).encode("utf-8")))

    def close(self):
        self.sock.close()


class TestDebugSocket:
    def test_relays_dap_messages_both_ways(self, project, monkeypatch):
        from ducta.api.services import debugger

        monkeypatch.setattr(debugger, "available", lambda: True)
        fake = _FakeDebugpy()
        manager = _Manager(port=fake.port)
        try:
            url = f"/api/ws/projects/proj/debug?source={project}&execution=run-1"
            with _client(manager).websocket_connect(url) as ws:
                ws.send_text(json.dumps({"seq": 1, "type": "request", "command": "initialize"}))
                reply = json.loads(ws.receive_text())
            assert reply == {"type": "response", "request_seq": 1, "success": True}
            assert fake.received[0]["command"] == "initialize"
            assert manager.attached == ["run-1"]
        finally:
            fake.close()

    def test_unknown_run_is_refused(self, project, monkeypatch):
        from ducta.api.services import debugger

        monkeypatch.setattr(debugger, "available", lambda: True)
        closed = _refused(_client(), f"/api/ws/projects/proj/debug?source={project}&execution=x")
        assert (closed.code, closed.reason) == (1008, "No such run")

    def test_a_source_that_does_not_resolve_is_refused(self, project, monkeypatch):
        from ducta.api.services import debugger

        monkeypatch.setattr(debugger, "available", lambda: True)
        closed = _refused(
            _client(), f"/api/ws/projects/proj/debug?source={project}/missing&execution=run-1"
        )
        assert (closed.code, closed.reason) == (1008, "Unknown project or non-local source")

    def test_without_debugpy_it_says_so(self, project, monkeypatch):
        from ducta.api.services import debugger

        monkeypatch.setattr(debugger, "available", lambda: False)
        closed = _refused(_client(), f"/api/ws/projects/proj/debug?source={project}")
        assert closed.code == 1011
        assert "debugpy" in closed.reason

    def test_a_server_with_accounts_refuses_debugging(self, project, monkeypatch):
        from ducta.api.services import debugger

        monkeypatch.setattr(debugger, "available", lambda: True)
        from ducta.api.routes import editor

        async def signed_in(websocket, settings, permission=None):
            return User(id="admin", username="admin", email="a@example.com", roles=["admin"])

        monkeypatch.setattr(editor, "authenticate_websocket", signed_in)
        settings = Settings(auth_enabled=False)
        monkeypatch.setattr(settings, "auth_enabled", True)
        monkeypatch.setattr(settings, "debug", False)
        closed = _refused(
            _client(settings=settings), f"/api/ws/projects/proj/debug?source={project}"
        )
        assert (closed.code, closed.reason) == (1008, "Debugging is for a local server")


class TestLspSocketRefusals:
    def test_a_source_that_does_not_resolve(self, project):
        closed = _refused(_client(), f"/api/ws/projects/proj/lsp?source={project}/missing")
        assert (closed.code, closed.reason) == (1008, "Unknown project or non-local source")

    def test_an_invalid_project_id(self, project):
        closed = _refused(_client(), f"/api/ws/projects/bad$id/lsp?source={project}")
        assert closed.code == 1008

    def test_a_git_source_is_never_analysed(self, project):
        url = "/api/ws/projects/proj/lsp?source=https://github.com/example/repo.git"
        closed = _refused(_client(), url)
        assert (closed.code, closed.reason) == (1008, "Unknown project or non-local source")

    def test_status_without_a_server_gives_the_hint(self, project, monkeypatch):
        from ducta.api.routes import editor

        monkeypatch.setenv("LSP_COMMAND", "off")
        get_settings.cache_clear()
        editor._pool = None
        try:
            body = _client().get("/api/projects/proj/lsp", params={"source": str(project)}).json()
        finally:
            get_settings.cache_clear()
            editor._pool = None
        assert body["available"] is False
        assert "basedpyright" in body["hint"]
