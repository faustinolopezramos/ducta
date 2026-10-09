"""The editor's language-server bridge: JSON-RPC in, LSP framing out, and back."""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ducta.api.config import get_settings
from ducta.api.dependencies import get_current_user
from ducta.api.main import create_app
from ducta.api.models.auth import User
from ducta.api.routes import editor
from ducta.api.services.language_server import server_command

FAKE_SERVER = textwrap.dedent(
    """
    import json, sys
    def read():
        length = None
        while True:
            line = sys.stdin.buffer.readline()
            if not line:
                return None
            line = line.strip()
            if not line:
                break
            k, _, v = line.decode().partition(":")
            if k.lower() == "content-length":
                length = int(v)
        return json.loads(sys.stdin.buffer.read(length))
    def write(msg):
        body = json.dumps(msg).encode()
        sys.stdout.buffer.write(b"Content-Length: %d\\r\\n\\r\\n" % len(body) + body)
        sys.stdout.buffer.flush()
    import os
    while True:
        msg = read()
        if msg is None:
            break
        if msg.get("method") == "initialize":
            write({"jsonrpc": "2.0", "id": msg["id"], "result": {"capabilities": {"hoverProvider": True}, "cwd": os.getcwd()}})
        elif msg.get("method") == "textDocument/hover":
            write({"jsonrpc": "2.0", "id": msg["id"], "result": {"contents": "def clean(df) -> DataFrame"}})
            write({"jsonrpc": "2.0", "method": "textDocument/publishDiagnostics", "params": {"uri": "x", "diagnostics": []}})
    """
)


@pytest.fixture
def project(tmp_path, monkeypatch):
    from ducta.console.template import TemplateGenerator, TemplateType

    monkeypatch.chdir(tmp_path)
    root = tmp_path / "proj"
    TemplateGenerator(root).generate_project(TemplateType.MEDALLION_BASIC, "proj")
    server = tmp_path / "fake_lsp.py"
    server.write_text(FAKE_SERVER)
    monkeypatch.setenv("LSP_COMMAND", f"{sys.executable} {server}")
    get_settings.cache_clear()
    editor._pool = None
    yield root
    get_settings.cache_clear()
    editor._pool = None


def _client() -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: User(
        id="admin", username="admin", email="admin@example.com", roles=["admin"]
    )
    return TestClient(app)


def test_status_names_the_server(project):
    r = _client().get("/api/projects/proj/lsp", params={"source": str(project)})
    assert r.status_code == 200
    assert r.json()["available"] is True


def test_bridge_round_trip(project):
    with _client().websocket_connect(f"/api/ws/projects/proj/lsp?source={project}") as ws:
        ws.send_text(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}))
        init = json.loads(ws.receive_text())
        assert init["id"] == 1 and init["result"]["capabilities"]["hoverProvider"] is True
        assert Path(init["result"]["cwd"]).resolve() == project.resolve()
        ws.send_text(
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "textDocument/hover", "params": {}})
        )
        assert json.loads(ws.receive_text())["result"]["contents"].startswith("def clean")
        assert json.loads(ws.receive_text())["method"] == "textDocument/publishDiagnostics"


def test_off_and_missing_commands():
    assert server_command("off") is None
    assert server_command("no-such-language-server --stdio") is None
