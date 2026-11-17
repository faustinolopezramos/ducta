"""Tests for the Automated Schedules feature: `AsyncCronScheduler` and its routes.

Covers three things that previously had zero test coverage:
  - workspace (`source_path`) scoping on list/delete/toggle/update, which
    used to be entirely global despite `create_schedule` already capturing
    `source_path` and the frontend already sending `?source=` on every call;
  - strict cron validation (`validate_cron`), which used to only check the
    field count, so an out-of-range field like `"99 * * * *"` was silently
    accepted and simply never fired;
  - `compute_next_run`, the replacement for the dead `next_run_hint` field.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi", reason="schedules tests require the api extra")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from ducta_server.dependencies import get_current_user, get_source_path  # noqa: E402
from ducta_server.execution.scheduler import (  # noqa: E402
    AsyncCronScheduler,
    PipelineSchedule,
    compute_next_run,
    validate_cron,
)
from ducta_server.models.auth import User  # noqa: E402
from ducta_server.routes import schedules as schedules_route  # noqa: E402


class TestValidateCron:
    def test_accepts_ordinary_expressions(self):
        validate_cron("0 0 * * *")
        validate_cron("*/15 * * * *")
        validate_cron("0 8 * * 1")
        validate_cron("1,15,30 0-6 1-15 1,6,12 *")

    def test_wrong_field_count_rejected(self):
        with pytest.raises(ValueError):
            validate_cron("* * *")

    def test_out_of_range_minute_rejected(self):
        with pytest.raises(ValueError, match="minute"):
            validate_cron("99 * * * *")

    def test_out_of_range_hour_rejected(self):
        with pytest.raises(ValueError, match="hour"):
            validate_cron("0 24 * * *")

    def test_invalid_step_rejected(self):
        with pytest.raises(ValueError):
            validate_cron("*/0 * * * *")

    def test_garbage_field_rejected(self):
        with pytest.raises(ValueError):
            validate_cron("abc * * * *")


class TestComputeNextRun:
    def test_daily_midnight(self):
        after = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        nxt = compute_next_run("0 0 * * *", after)
        assert nxt == datetime(2026, 1, 2, 0, 0, tzinfo=timezone.utc)

    def test_every_15_minutes(self):
        after = datetime(2026, 1, 1, 12, 1, tzinfo=timezone.utc)
        nxt = compute_next_run("*/15 * * * *", after)
        assert nxt == datetime(2026, 1, 1, 12, 15, tzinfo=timezone.utc)

    def test_specific_weekday(self):
        # 2026-01-01 is a Thursday; next Monday 8am should be 2026-01-05.
        after = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        nxt = compute_next_run("0 8 * * 1", after)
        assert nxt == datetime(2026, 1, 5, 8, 0, tzinfo=timezone.utc)

    def test_impossible_combination_returns_none(self):
        after = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        assert compute_next_run("0 0 31 2 *", after, horizon_days=30) is None


class TestAsyncCronSchedulerScoping:
    @pytest.fixture()
    def scheduler(self, tmp_path: Path) -> AsyncCronScheduler:
        return AsyncCronScheduler(storage_dir=tmp_path)

    @staticmethod
    def _make(scheduler: AsyncCronScheduler, source: str, **overrides) -> PipelineSchedule:
        sched = PipelineSchedule(
            pipeline_name=overrides.pop("pipeline_name", "daily_sales"),
            cron=overrides.pop("cron", "0 0 * * *"),
            source_path=source,
            **overrides,
        )
        return asyncio.run(scheduler.create_schedule(sched))

    def test_list_only_returns_matching_workspace(self, scheduler: AsyncCronScheduler):
        self._make(scheduler, "/workspace/a")
        self._make(scheduler, "/workspace/b")

        a_items = asyncio.run(scheduler.list_schedules("/workspace/a"))
        b_items = asyncio.run(scheduler.list_schedules("/workspace/b"))

        assert len(a_items) == 1
        assert len(b_items) == 1
        assert a_items[0].source_path == "/workspace/a"

    def test_delete_across_workspace_is_rejected(self, scheduler: AsyncCronScheduler):
        sched = self._make(scheduler, "/workspace/a")

        assert asyncio.run(scheduler.delete_schedule(sched.id, "/workspace/b")) is False
        assert asyncio.run(scheduler.delete_schedule(sched.id, "/workspace/a")) is True

    def test_toggle_across_workspace_is_rejected(self, scheduler: AsyncCronScheduler):
        sched = self._make(scheduler, "/workspace/a")

        assert asyncio.run(scheduler.toggle_schedule(sched.id, "/workspace/b")) is None
        updated = asyncio.run(scheduler.toggle_schedule(sched.id, "/workspace/a"))
        assert updated is not None
        assert updated.enabled is False

    def test_update_across_workspace_is_rejected(self, scheduler: AsyncCronScheduler):
        sched = self._make(scheduler, "/workspace/a")

        assert (
            asyncio.run(scheduler.update_schedule(sched.id, "/workspace/b", cron="0 1 * * *"))
            is None
        )
        updated = asyncio.run(scheduler.update_schedule(sched.id, "/workspace/a", cron="0 1 * * *"))
        assert updated is not None
        assert updated.cron == "0 1 * * *"


@pytest.fixture()
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    import ducta_server.execution.scheduler as scheduler_module

    # A fresh scheduler persisting under tmp_path: the default one reads and
    # writes ~/.ducta/schedules.json, so entries left by earlier runs (or by the
    # developer's real schedules) leaked into these assertions.
    monkeypatch.setattr(
        scheduler_module, "_scheduler", scheduler_module.AsyncCronScheduler(tmp_path / ".ducta")
    )

    fastapi_app = FastAPI()
    fastapi_app.include_router(schedules_route.router, prefix="/api")
    fastapi_app.dependency_overrides[get_source_path] = lambda: Path(tmp_path)
    fastapi_app.dependency_overrides[get_current_user] = lambda: User(
        id="test-user", username="test-user", email="test@ducta.local", roles=["admin"]
    )
    return fastapi_app


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


class TestScheduleRoutes:
    def test_create_rejects_invalid_cron(self, client: TestClient):
        resp = client.post(
            "/api/schedules", json={"pipeline_name": "daily_sales", "cron": "99 * * * *"}
        )
        assert resp.status_code == 422

    def test_create_then_list_includes_next_run_at(self, client: TestClient):
        create_resp = client.post(
            "/api/schedules", json={"pipeline_name": "daily_sales", "cron": "0 0 * * *"}
        )
        assert create_resp.status_code == 201
        body = create_resp.json()
        assert body["next_run_at"] is not None
        assert body["user_id"] == "test-user"

        list_resp = client.get("/api/schedules")
        assert list_resp.status_code == 200
        assert list_resp.json()["count"] == 1

    def test_patch_updates_cron(self, client: TestClient):
        created = client.post(
            "/api/schedules", json={"pipeline_name": "daily_sales", "cron": "0 0 * * *"}
        ).json()

        patch_resp = client.patch(f"/api/schedules/{created['id']}", json={"cron": "0 1 * * *"})
        assert patch_resp.status_code == 200
        assert patch_resp.json()["cron"] == "0 1 * * *"

    def test_patch_rejects_invalid_cron(self, client: TestClient):
        created = client.post(
            "/api/schedules", json={"pipeline_name": "daily_sales", "cron": "0 0 * * *"}
        ).json()

        patch_resp = client.patch(f"/api/schedules/{created['id']}", json={"cron": "abc"})
        assert patch_resp.status_code == 422

    def test_list_scopes_to_current_workspace(
        self, client: TestClient, app: FastAPI, tmp_path: Path
    ):
        client.post("/api/schedules", json={"pipeline_name": "daily_sales", "cron": "0 0 * * *"})

        other = tmp_path / "other-workspace"
        other.mkdir()
        app.dependency_overrides[get_source_path] = lambda: other
        other_client = TestClient(app)

        assert other_client.get("/api/schedules").json()["count"] == 0
        # Switching back to the original workspace still sees it.
        app.dependency_overrides[get_source_path] = lambda: Path(tmp_path)
        assert TestClient(app).get("/api/schedules").json()["count"] == 1


# ── a schedule is a run that happens later: same governance, and it has an owner ──


def _as(app: FastAPI, user_id: str, role: str) -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: User(
        id=user_id, username=user_id, email=f"{user_id}@ducta.local", roles=[role]
    )
    return TestClient(app)


class TestScheduleGovernance:
    BODY = {"pipeline_name": "daily_sales", "cron": "0 0 * * *"}

    def test_developer_cannot_schedule_in_a_protected_environment(self, app: FastAPI):
        dev = _as(app, "dev1", "developer")
        assert dev.post("/api/schedules", json={**self.BODY, "env": "prod"}).status_code == 403
        assert dev.post("/api/schedules", json={**self.BODY, "env": "dev"}).status_code == 201
        assert dev.get("/api/schedules").json()["count"] == 1  # nothing in prod was kept

    def test_operator_can_schedule_in_a_protected_environment(self, app: FastAPI):
        op = _as(app, "op1", "operator")
        assert op.post("/api/schedules", json={**self.BODY, "env": "prod"}).status_code == 201

    def test_developer_cannot_move_a_schedule_into_prod(self, app: FastAPI):
        dev = _as(app, "dev1", "developer")
        sid = dev.post("/api/schedules", json={**self.BODY, "env": "dev"}).json()["id"]
        assert dev.patch(f"/api/schedules/{sid}", json={"env": "prod"}).status_code == 403
        assert dev.patch(f"/api/schedules/{sid}", json={"cron": "0 2 * * *"}).status_code == 200

    def test_a_schedule_belongs_to_its_creator(self, app: FastAPI):
        sid = (
            _as(app, "op1", "operator")
            .post("/api/schedules", json={**self.BODY, "env": "dev"})
            .json()["id"]
        )
        dev = _as(app, "dev1", "developer")
        assert dev.patch(f"/api/schedules/{sid}", json={"cron": "0 5 * * *"}).status_code == 403
        assert dev.post(f"/api/schedules/{sid}/toggle").status_code == 403
        assert dev.delete(f"/api/schedules/{sid}").status_code == 403
        # The owner, and any operator/admin, can.
        assert _as(app, "op1", "operator").post(f"/api/schedules/{sid}/toggle").status_code == 200
        assert (
            _as(app, "adm", "admin")
            .patch(f"/api/schedules/{sid}", json={"cron": "0 6 * * *"})
            .status_code
            == 200
        )
        assert _as(app, "op1", "operator").delete(f"/api/schedules/{sid}").status_code == 204

    def test_unknown_schedule_is_404_not_403(self, app: FastAPI):
        assert _as(app, "dev1", "developer").delete("/api/schedules/nope").status_code == 404


class TestTriggerTimeGovernance:
    """A schedule saved before the routes checked, or by a role that lost the permission,
    must not keep running in a protected environment."""

    @staticmethod
    def _sched(**kw):
        return PipelineSchedule(
            pipeline_name="p", cron="* * * * *", source_path="/nowhere", user_id="dev1", **kw
        )

    @staticmethod
    def _auth(monkeypatch, roles):
        import ducta_server.auth.users as users_module
        import ducta_server.config as config_module

        class _Store:
            async def get_by_id(self, uid):
                return User(id=uid, username=uid, email="x@y.io", roles=roles) if roles else None

        monkeypatch.setattr(
            config_module, "get_settings", lambda: type("S", (), {"auth_enabled": True})()
        )
        monkeypatch.setattr(users_module, "get_user_store", lambda: _Store())

    def test_developers_schedule_in_prod_is_not_triggered(self, monkeypatch):
        from ducta_server.execution.scheduler import _may_run_in_env

        self._auth(monkeypatch, ["developer"])
        assert asyncio.run(_may_run_in_env(self._sched(env="prod"))) is False
        assert asyncio.run(_may_run_in_env(self._sched(env="dev"))) is True

    def test_operators_schedule_in_prod_is_triggered(self, monkeypatch):
        from ducta_server.execution.scheduler import _may_run_in_env

        self._auth(monkeypatch, ["operator"])
        assert asyncio.run(_may_run_in_env(self._sched(env="prod"))) is True

    def test_deleted_user_does_not_keep_running_in_prod(self, monkeypatch):
        from ducta_server.execution.scheduler import _may_run_in_env

        self._auth(monkeypatch, None)
        assert asyncio.run(_may_run_in_env(self._sched(env="prod"))) is False
