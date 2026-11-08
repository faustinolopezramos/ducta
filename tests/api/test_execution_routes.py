"""The `/api/executions` routes: what each answers, and with which status.

A recording stand-in replaces the ExecutionManager, so each test states the
manager's answer and checks the route's translation of it (404, 409, 400, the
response shape) and the permission it demands.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from ducta.api.dependencies import (  # noqa: E402
    get_current_user,
    get_execution_manager,
    get_source_path,
)
from ducta.api.exceptions import ExecutionNotFoundError  # noqa: E402
from ducta.api.main import create_app  # noqa: E402
from ducta.api.models.auth import User  # noqa: E402
from ducta.api.models.execution import (  # noqa: E402
    ExecutionResponse,
    ExecutionStatus,
    LogEntry,
)

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)


def _record(execution_id: str = "run-1", **overrides) -> ExecutionResponse:
    payload = {
        "id": execution_id,
        "pipeline_name": "etl",
        "project_id": None,
        "env": "dev",
        "status": ExecutionStatus.FAILED,
        "started_at": NOW,
    }
    payload.update(overrides)
    return ExecutionResponse(**payload)


class _Manager:
    """Answers like an ExecutionManager holding the runs in ``records``."""

    def __init__(self, records=()):
        self.records = {r.id: r for r in records}
        self.calls: list = []
        self.cancellable: set = set(self.records)
        self.paused: set = set()
        self.errors: dict = {}
        self.logs: dict = {}
        self.engine = None
        self.retry_error: Exception | None = None

    def _get(self, execution_id):
        if execution_id not in self.records:
            raise ExecutionNotFoundError(f"Execution '{execution_id}' not found")
        return self.records[execution_id]

    # reads
    def queue_status(self):
        return {"active": 1, "queued": 2, "capacity": 4, "total_queued": 9, "total_completed": 7}

    def list_executions_paginated(self, **kwargs):
        self.calls.append(("list", kwargs))
        items = list(self.records.values())
        return items[kwargs["skip"] : kwargs["skip"] + kwargs["limit"]], len(items)

    async def load_execution(self, execution_id, user_id=None):
        return self._get(execution_id)

    def get_execution(self, execution_id, user_id=None):
        return self._get(execution_id)

    def get_active_engine(self, execution_id):
        return self.engine

    async def load_logs(self, execution_id, user_id=None):
        self._get(execution_id)
        return self.logs.get(execution_id, [])

    def get_execution_errors(self, execution_id, user_id=None):
        self._get(execution_id)
        return self.errors.get(execution_id)

    # writes
    def cancel_execution(self, execution_id, user_id=None):
        self._get(execution_id)
        self.calls.append(("cancel", execution_id))
        if execution_id not in self.cancellable:
            return False
        self.records[execution_id] = self.records[execution_id].model_copy(
            update={"status": ExecutionStatus.CANCELLED}
        )
        return True

    def resume(self, execution_id):
        self.calls.append(("resume", execution_id))
        return execution_id in self.paused

    def retry(self, execution_id, source_path=None, user_id=None):
        original = self._get(execution_id)
        self.calls.append(("retry", execution_id, source_path))
        if self.retry_error:
            raise self.retry_error
        clone = original.model_copy(update={"id": f"{execution_id}-retry", "status": "queued"})
        self.records[clone.id] = clone
        return clone


def _user(role: str) -> User:
    return User(id=role, username=role, email=f"{role}@example.com", roles=[role])


@pytest.fixture
def manager() -> _Manager:
    return _Manager([_record("run-1"), _record("run-2", status=ExecutionStatus.SUCCESS)])


@pytest.fixture
def app(manager, tmp_path):
    app = create_app()
    app.dependency_overrides[get_execution_manager] = lambda: manager
    app.dependency_overrides[get_source_path] = lambda: Path(tmp_path)
    app.dependency_overrides[get_current_user] = lambda: _user("admin")
    return app


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app)


def _as(app, role: str) -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: _user(role)
    return TestClient(app)


class TestReading:
    def test_queue_status_maps_the_managers_counts(self, client):
        body = client.get("/api/executions/queue").json()
        assert body == {
            "running": 1,
            "queued": 2,
            "max_concurrent": 4,
            "total_queued": 9,
            "total_completed": 7,
        }

    def test_list_passes_filters_and_pages(self, client, manager):
        body = client.get(
            "/api/executions", params={"skip": 1, "limit": 1, "status": "failed", "q": "etl"}
        ).json()
        assert (body["count"], body["total"], body["skip"], body["limit"]) == (1, 2, 1, 1)
        _, kwargs = manager.calls[-1]
        assert (kwargs["status"], kwargs["q"], kwargs["user_id"]) == ("failed", "etl", "admin")

    def test_get_one_and_unknown_is_404(self, client):
        assert client.get("/api/executions/run-1").json()["id"] == "run-1"
        assert client.get("/api/executions/nope").status_code == 404

    def test_logs_since_filters_and_a_bad_since_returns_all(self, client, manager):
        manager.logs["run-1"] = [
            LogEntry(timestamp=NOW - timedelta(minutes=5), level="INFO", message="old"),
            LogEntry(timestamp=NOW, level="INFO", message="new"),
        ]
        recent = client.get(
            "/api/executions/run-1/logs", params={"since": "2026-11-07T11:58:00Z"}
        ).json()
        assert [e["message"] for e in recent] == ["new"]

        naive = client.get(
            "/api/executions/run-1/logs", params={"since": "2026-11-07T11:58:00"}
        ).json()
        assert [e["message"] for e in naive] == ["new"]  # naive means UTC

        everything = client.get("/api/executions/run-1/logs", params={"since": "yesterday"})
        assert [e["message"] for e in everything.json()] == ["old", "new"]

    def test_logs_of_an_unknown_run_is_404(self, client):
        assert client.get("/api/executions/nope/logs").status_code == 404

    def test_errors_empty_when_nothing_recorded(self, client):
        body = client.get("/api/executions/run-1/errors").json()
        assert (body["error_count"], body["has_critical_errors"], body["errors"]) == (
            0,
            False,
            [],
        )

    def test_errors_are_detailed_and_old_logs_keep_their_hint(self, client, manager):
        manager.errors["run-1"] = {
            "error_count": 2,
            "has_critical_errors": True,
            "errors": [
                {
                    "timestamp": "t1",
                    "node_id": "load",
                    "error": {"type": "KeyError", "message": "id", "category": "data"},
                    "hint": "Check the column",
                },
                {
                    "node_id": "save",
                    "error": {},
                    "recovery_plan": {"notes": "Retry later"},
                },
            ],
        }
        body = client.get("/api/executions/run-1/errors").json()
        first, second = body["errors"]
        assert (first["error_type"], first["category"], first["hint"]) == (
            "KeyError",
            "data",
            "Check the column",
        )
        assert (second["error_type"], second["hint"]) == ("Exception", "Retry later")
        assert body["has_critical_errors"] is True

    def test_streaming_restart_without_a_stream_is_409(self, client):
        response = client.post("/api/executions/run-1/streaming/s-1/nodes/score/restart")
        assert response.status_code == 409

    def test_streaming_restart_reaches_the_engine(self, client, manager):
        class _Engine:
            def restart_streaming_node(self, stream_id, node):
                return (stream_id, node) == ("s-1", "score")

        manager.engine = _Engine()
        body = client.post("/api/executions/run-1/streaming/s-1/nodes/score/restart").json()
        assert body == {"restarted": True, "node": "score"}


class TestCancel:
    def test_cancel_returns_the_cancelled_run(self, client):
        body = client.post("/api/executions/run-1/cancel").json()
        assert body["status"] == "cancelled"

    def test_cancel_unknown_is_404(self, client):
        assert client.post("/api/executions/nope/cancel").status_code == 404

    def test_bulk_cancel_skips_unknown_and_finished(self, client, manager):
        manager.cancellable = {"run-1"}
        body = client.post(
            "/api/executions/bulk-cancel", json={"execution_ids": ["run-1", "run-2", "ghost"]}
        ).json()
        assert body == {"cancelled": ["run-1"], "skipped": ["run-2", "ghost"]}

    def test_a_viewer_cannot_cancel(self, app, manager):
        assert _as(app, "viewer").post("/api/executions/run-1/cancel").status_code == 403
        assert ("cancel", "run-1") not in manager.calls


class TestResume:
    def test_resume_a_paused_run(self, client, manager):
        manager.paused = {"run-1"}
        assert client.post("/api/executions/run-1/resume").json() == {"resumed": "run-1"}

    def test_resume_a_run_that_is_not_paused_is_409(self, client):
        assert client.post("/api/executions/run-1/resume").status_code == 409


class TestRetry:
    def test_retry_enqueues_a_clone_in_the_workspace(self, client, manager, tmp_path):
        response = client.post("/api/executions/run-1/retry")
        assert response.status_code == 202
        assert response.json()["id"] == "run-1-retry"
        assert manager.calls[-1] == ("retry", "run-1", Path(tmp_path))

    def test_retry_unknown_is_404(self, client):
        assert client.post("/api/executions/nope/retry").status_code == 404

    def test_retry_refused_by_the_manager_is_400(self, client, manager):
        manager.retry_error = ValueError("Only finished runs can be retried")
        response = client.post("/api/executions/run-1/retry")
        assert response.status_code == 400
        assert "finished runs" in response.json()["message"]

    def test_retry_in_a_protected_environment_needs_the_right(self, app, manager):
        manager.records["run-1"] = _record("run-1", env="prod")
        response = _as(app, "developer").post("/api/executions/run-1/retry")
        assert response.status_code == 403
        assert not any(c[0] == "retry" for c in manager.calls)

    def test_an_operator_may_retry_in_a_protected_environment(self, app, manager):
        manager.records["run-1"] = _record("run-1", env="prod")
        assert _as(app, "operator").post("/api/executions/run-1/retry").status_code == 202


class _Entry:
    def __init__(self, message):
        self.message = message

    def as_serialized_dict(self):
        return {"level": "INFO", "message": self.message}


class TestLogStream:
    """`/api/ws/logs/{id}`: batches as JSON (or msgpack), then a clean close."""

    @pytest.fixture
    def streaming_app(self, app, manager):
        async def stream_logs(execution_id, user_id=None):
            if execution_id not in manager.records:
                raise ExecutionNotFoundError(f"Execution '{execution_id}' not found")
            yield [_Entry("start"), _Entry("node load done")]
            yield [_Entry("finish")]

        manager.stream_logs = stream_logs
        app.state.execution_manager = manager
        return app

    def test_batches_then_stream_completed(self, streaming_app):
        from starlette.websockets import WebSocketDisconnect

        with TestClient(streaming_app).websocket_connect("/api/ws/logs/run-1") as ws:
            first = ws.receive_json()
            second = ws.receive_json()
            with pytest.raises(WebSocketDisconnect) as closed:
                ws.receive_json()
        assert [e["message"] for e in first] == ["start", "node load done"]
        assert [e["message"] for e in second] == ["finish"]
        assert (closed.value.code, closed.value.reason) == (1000, "Stream completed")

    def test_msgpack_on_request(self, streaming_app):
        import msgpack

        with TestClient(streaming_app).websocket_connect("/api/ws/logs/run-1?format=msgpack") as ws:
            batch = msgpack.unpackb(ws.receive_bytes(), raw=False)
        assert batch[0]["message"] == "start"

    def test_unknown_run_closes_with_policy_violation(self, streaming_app):
        from starlette.websockets import WebSocketDisconnect

        with TestClient(streaming_app).websocket_connect("/api/ws/logs/ghost") as ws:
            with pytest.raises(WebSocketDisconnect) as closed:
                ws.receive_json()
        assert closed.value.code == 1008
        assert "not found" in closed.value.reason


class TestDiagnosis:
    def test_a_failed_run_without_a_project_is_still_diagnosed(self, client, monkeypatch):
        import ducta.api.execution.error_recovery as recovery

        monkeypatch.setattr(
            recovery,
            "load_error_log_summary",
            lambda execution_id: {
                "errors": [
                    {
                        "node_id": "load",
                        "error": {"type": "KeyError", "message": "'amount'", "traceback": "tb"},
                        "hint": "A column is missing",
                    }
                ]
            },
        )
        response = client.get("/api/executions/run-1/diagnosis")
        assert response.status_code == 200
        assert "load" in response.text

    def test_run_errors_reads_the_error_log(self, monkeypatch):
        import ducta.api.execution.error_recovery as recovery
        from ducta.api.routes.execution import run_errors

        monkeypatch.setattr(
            recovery,
            "load_error_log_summary",
            lambda execution_id: {"errors": [{"node_id": "n", "error": {"type": "E"}}]},
        )
        assert run_errors("x") == [
            {"node_id": "n", "error_type": "E", "message": None, "traceback": None, "hint": None}
        ]
        monkeypatch.setattr(recovery, "load_error_log_summary", lambda execution_id: None)
        assert run_errors("x") == []

    def test_unknown_run_is_404(self, client):
        assert client.get("/api/executions/nope/diagnosis").status_code == 404
