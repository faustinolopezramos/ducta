"""Token revocation sharing, refresh rotation, bounded file reads."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("fastapi", reason="requires the api extra")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from ducta.api.auth.service import AuthService, get_auth_service  # noqa: E402
from ducta.api.auth.users import get_user_store  # noqa: E402
from ducta.api.models.auth import User  # noqa: E402
from ducta.api.routes import auth as auth_routes  # noqa: E402


class _FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, int] = {}

    def setex(self, key: str, ttl: int, value: str) -> None:
        assert ttl >= 1
        self.data[key] = ttl

    def exists(self, key: str) -> int:
        return int(key in self.data)


class TestSharedRevocation:
    def test_revocation_is_visible_to_another_worker(self, monkeypatch):
        shared = _FakeRedis()
        monkeypatch.setattr(AuthService, "_connect_redis", staticmethod(lambda url: shared))
        worker_a = AuthService("k" * 32, redis_url="redis://x")
        worker_b = AuthService("k" * 32, redis_url="redis://x")

        token = worker_a.create_access_token("u1", "alice", ["admin"])
        payload = worker_a.decode_access_token(token)
        worker_a.revoke_token(payload["jti"], datetime.now(tz=timezone.utc) + timedelta(hours=1))

        assert worker_b.is_revoked(payload["jti"])

    def test_unreachable_redis_falls_back_to_local_list(self):
        svc = AuthService("k" * 32, redis_url="redis://127.0.0.1:1/0")
        svc.revoke_token("j", datetime.now(tz=timezone.utc) + timedelta(minutes=5))
        assert svc.is_revoked("j")


class _Store:
    async def get_by_id(self, user_id: str):
        return User(id=user_id, username="alice", email="a@x.io", roles=["admin"])


class TestRefreshRotation:
    def test_refresh_revokes_the_presented_token(self):
        svc = AuthService("k" * 32)
        app = FastAPI()
        app.include_router(auth_routes.router, prefix="/api")
        app.dependency_overrides[get_auth_service] = lambda: svc
        app.dependency_overrides[get_user_store] = lambda: _Store()
        client = TestClient(app)

        old = svc.create_access_token("u1", "alice", ["admin"])
        resp = client.post("/api/auth/refresh", json={}, headers={"Authorization": f"Bearer {old}"})
        assert resp.status_code == 200
        new = resp.json()["access_token"]
        assert new != old

        again = client.post(
            "/api/auth/refresh", json={}, headers={"Authorization": f"Bearer {old}"}
        )
        assert again.status_code == 401
        assert svc.decode_access_token(new)["sub"] == "u1"


class TestBoundedFileRead:
    def test_oversized_file_is_413(self, tmp_path, monkeypatch):
        from ducta.api.dependencies import get_current_user, get_source_path
        from ducta.api.routes import workspace_files
        from ducta.api.workspace.manager import WorkspaceManager

        (tmp_path / "big.txt").write_text("x" * 100)
        monkeypatch.setattr(WorkspaceManager, "MAX_READ_BYTES", 10)
        app = FastAPI()
        app.include_router(workspace_files.router, prefix="/api")
        app.dependency_overrides[get_source_path] = lambda: tmp_path
        app.dependency_overrides[get_current_user] = lambda: User(
            id="t", username="t", email="t@x.io", roles=["admin"]
        )
        client = TestClient(app)

        assert (
            client.get("/api/workspace/files/content", params={"path": "big.txt"}).status_code
            == 413
        )
        (tmp_path / "ok.txt").write_text("hi")
        assert (
            client.get("/api/workspace/files/content", params={"path": "ok.txt"}).status_code == 200
        )
