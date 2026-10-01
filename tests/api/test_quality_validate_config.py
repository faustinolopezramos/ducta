"""POST /api/quality/validate-config checks a node of the workspace's project.

The request names the node and the environment; the server finds the project
that owns the node. See tests/check/test_validate_node_config.py for the rules.
"""

from __future__ import annotations

import pytest

from tests.check.test_validate_node_config import _project


class TestApi:
    @pytest.fixture
    def client(self, tmp_path, monkeypatch):
        from fastapi.testclient import TestClient

        from ducta.api.config import get_settings
        from ducta.api.main import create_app

        _project(tmp_path, profile="release")
        monkeypatch.setenv("DUCTA_WORKSPACE", str(tmp_path))
        monkeypatch.setenv("AUTH_ENABLED", "false")
        get_settings.cache_clear()
        with TestClient(create_app()) as c:
            yield c
        get_settings.cache_clear()

    def test_validates_the_node_in_the_requested_environment(self, client):
        prod = client.post(
            "/api/quality/validate-config", json={"node_name": "clean", "env": "prod"}
        )
        assert prod.status_code == 200, prod.text
        assert prod.json() == {"valid": True, "errors": [], "warnings": []}
        base = client.post("/api/quality/validate-config", json={"node_name": "clean"}).json()
        assert not base["valid"] and "Profile 'release'" in base["errors"][0]

    def test_an_unknown_node_is_404(self, client):
        resp = client.post("/api/quality/validate-config", json={"node_name": "ghost"})
        assert resp.status_code == 404
