"""`GET /api/executions/{id}/streaming/nodes/{node}/rows`: what a stream is landing, as rows."""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from ducta_server.dependencies import (
    get_current_user,
    get_execution_manager,
    get_optional_source_path,
)
from ducta_server.exceptions import ExecutionNotFoundError
from ducta_server.main import create_app
from ducta_server.models.auth import User
from ducta_server.models.execution import ExecutionResponse, ExecutionStatus


def _user(role: str) -> User:
    return User(id=role, username=role, email=f"{role}@example.com", roles=[role])


class _Engine:
    def __init__(self, nodes: dict[str, str]):
        self.nodes = nodes

    def streaming_snapshot(self):
        return [
            {
                "execution_id": "stream-1",
                "pipeline_name": "events_stream",
                "status": "running",
                "total_queries": len(self.nodes),
                "active_queries": len(self.nodes),
                "query_statuses": {n: {"isActive": True} for n in self.nodes},
                "node_summaries": {n: {"sink": sink} for n, sink in self.nodes.items()},
            }
        ]


class _Manager:
    def __init__(self, record, engine):
        self.record, self.engine = record, engine

    async def load_execution(self, execution_id, user_id=None):
        if execution_id != self.record.id:
            raise ExecutionNotFoundError(execution_id)
        return self.record

    def get_active_engine(self, execution_id):
        return self.engine


@pytest.fixture
def project(tmp_path, monkeypatch) -> Path:
    from ducta.console.templates import TemplateGenerator, TemplateType

    monkeypatch.chdir(tmp_path)  # the server's source confinement base
    root = tmp_path / "proj"
    TemplateGenerator(root).generate_project(TemplateType.STREAMING_BASIC, "proj")
    return root


def _land(path: Path, rows: list[dict], age: float = 0.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(path, index=False)
    when = time.time() - age
    os.utime(path, (when, when))


@pytest.fixture
def make_client(project):
    def build(role="developer", nodes=None, execution_id="run-1"):
        record = ExecutionResponse(
            id=execution_id,
            pipeline_name="events_stream",
            project_id="proj",
            env="dev",
            status=ExecutionStatus.RUNNING,
            started_at=datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc),
        )
        engine = _Engine(nodes or {"clean_events": "parquet data/dev/silver/events"})
        app = create_app()
        app.dependency_overrides[get_execution_manager] = lambda: _Manager(record, engine)
        app.dependency_overrides[get_optional_source_path] = lambda: Path(project)
        app.dependency_overrides[get_current_user] = lambda: _user(role)
        return TestClient(app)

    return build


URL = "/api/executions/run-1/streaming/nodes/clean_events/rows"


def test_returns_the_newest_rows_newest_first(project, make_client):
    silver = project / "data" / "dev" / "silver" / "events"
    _land(silver / "part-0.parquet", [{"event_id": "e1", "amount": 1.0}], age=30)
    _land(
        silver / "part-1.parquet",
        [{"event_id": "e2", "amount": 2.0}, {"event_id": "e3", "amount": 3.0}],
    )
    r = make_client().get(URL, params={"limit": 2})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["available"] is True, body
    assert [row["event_id"] for row in body["rows"]] == ["e3", "e2"]
    assert body["total_rows"] == 3
    assert [c["name"] for c in body["columns"]] == ["event_id", "amount"]
    assert body["sink"] == "parquet data/dev/silver/events"
    assert body["newest_at"]


def test_nothing_written_yet_says_so_instead_of_failing(make_client):
    body = make_client().get(URL).json()
    assert body["available"] is False
    assert "Nothing written yet" in body["reason"]


def test_a_kafka_sink_has_no_rows_to_show(make_client):
    body = make_client(nodes={"clean_events": "kafka topic events"}).get(URL).json()
    assert body["available"] is False
    assert "kafka" in body["reason"]


def test_a_sink_outside_the_project_is_not_read(tmp_path, make_client):
    outside = tmp_path.parent / "elsewhere"
    _land(outside / "part-0.parquet", [{"secret": 1}])
    body = make_client(nodes={"clean_events": f"parquet {outside}"}).get(URL).json()
    assert body["available"] is False
    assert "outside the project" in body["reason"]


def test_a_dotdot_path_cannot_leave_the_project(make_client):
    body = make_client(nodes={"clean_events": "parquet ../../etc"}).get(URL).json()
    assert body["available"] is False
    assert "outside the project" in body["reason"]


def test_an_unknown_node_is_404(make_client):
    assert make_client().get("/api/executions/run-1/streaming/nodes/ghost/rows").status_code == 404


def test_an_unknown_execution_is_404(make_client):
    assert (
        make_client().get("/api/executions/ghost/streaming/nodes/clean_events/rows").status_code
        == 404
    )


def test_the_limit_is_bounded(make_client):
    assert make_client().get(URL, params={"limit": 0}).status_code == 422
    assert make_client().get(URL, params={"limit": 201}).status_code == 422


def test_a_viewer_may_read_it_like_the_status(project, make_client):
    _land(project / "data" / "dev" / "silver" / "events" / "part-0.parquet", [{"event_id": "e1"}])
    assert make_client(role="viewer").get(URL).status_code == 200
