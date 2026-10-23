"""`GET /api/executions/{id}/streaming`: the live state of an execution's streams."""

from __future__ import annotations

import json
import math

import pytest
from fastapi.testclient import TestClient

from ducta.api.dependencies import get_current_user, get_execution_manager
from ducta.api.exceptions import ExecutionNotFoundError
from ducta.api.main import create_app
from ducta.api.models.auth import User
from ducta.api.services.streaming_status import streaming_status

SNAPSHOT = {
    "execution_id": "stream-1",
    "pipeline_name": "live",
    "pipeline_config": {"huge": "never leaves the server"},
    "status": "running",
    "uptime_seconds": 12.5,
    "total_queries": 3,
    "active_queries": 1,
    "failed_queries": 1,
    "query_statuses": {
        "score": {"isActive": True, "lastProgress": object()},
        "enrich": {"isActive": False, "exception": "AnalysisException: no column x"},
    },
    "skipped_nodes": {"archive": "upstream 'enrich' failed"},
    "health_monitors": {"score": {"last_batch_id": 7}},
    "progress_metrics": {
        "score": {
            "batchId": 8,
            "numInputRows": 120,
            "inputRowsPerSecond": math.nan,  # Spark's rate before a full window
            "processedRowsPerSecond": 400.0,
            "triggerExecutionMs": 250,
        }
    },
    "served_models": {"score": {"name": "fraud", "version": 3, "source": "ducta"}},
}


class _Engine:
    def __init__(self, snapshot):
        self._snapshot = snapshot

    def streaming_snapshot(self):
        return self._snapshot


class TestTheStatus:
    def test_each_node_has_its_state_throughput_and_model(self):
        resp = streaming_status("exec-1", _Engine([SNAPSHOT]))
        assert resp.active
        (pipeline,) = resp.pipelines
        assert (pipeline.stream_execution_id, pipeline.pipeline_name) == ("stream-1", "live")
        nodes = {n.node: n for n in pipeline.nodes}
        assert sorted(nodes) == ["archive", "enrich", "score"]

        score = nodes["score"]
        assert (score.state, score.last_batch_id, score.num_input_rows) == ("active", 8, 120.0)
        assert score.input_rows_per_second is None  # NaN is not a number to show
        assert score.processed_rows_per_second == 400.0
        assert score.model == {"name": "fraud", "version": 3, "source": "ducta"}

        assert (nodes["enrich"].state, nodes["enrich"].error) == (
            "failed",
            "AnalysisException: no column x",
        )
        assert (nodes["archive"].state, nodes["archive"].error) == (
            "skipped",
            "upstream 'enrich' failed",
        )

    def test_it_is_plain_json(self):
        body = streaming_status("exec-1", _Engine([SNAPSHOT])).model_dump_json()
        assert "never leaves the server" not in body
        json.loads(body)  # no NaN, no Spark objects

    def test_without_an_engine_nothing_is_running(self):
        resp = streaming_status("exec-1", None)
        assert (resp.active, resp.pipelines) == (False, [])


class _Manager:
    def __init__(self, engines):
        self._engines = engines

    async def load_execution(self, execution_id, user_id=None):
        if execution_id not in self._engines:
            raise ExecutionNotFoundError(execution_id)
        return {"execution_id": execution_id}

    def get_active_engine(self, execution_id):
        return self._engines.get(execution_id)


@pytest.fixture
def client():
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: User(
        id="viewer", username="viewer", email="viewer@example.com", roles=["viewer"]
    )
    app.dependency_overrides[get_execution_manager] = lambda: _Manager(
        {"running": _Engine([SNAPSHOT]), "finished": None}
    )
    return TestClient(app)


class TestTheRoute:
    def test_a_running_execution(self, client):
        r = client.get("/api/executions/running/streaming")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["active"] is True
        assert body["pipelines"][0]["active_queries"] == 1

    def test_a_finished_execution_is_inactive(self, client):
        r = client.get("/api/executions/finished/streaming")
        assert r.status_code == 200, r.text
        assert r.json() == {"execution_id": "finished", "active": False, "pipelines": []}

    def test_an_unknown_execution_is_404(self, client):
        assert client.get("/api/executions/nope/streaming").status_code == 404


SUMMARIZED = {
    **SNAPSHOT,
    "node_summaries": {
        "score": {
            "source": "kafka topic events",
            "sink": "delta data/silver",
            "trigger": "every 5 seconds",
            "output_mode": "append",
            "checkpoint": "data/_ckpt/score/live/score",
        }
    },
}


class TestWhatTheNodeDoes:
    def test_the_node_says_what_it_reads_writes_and_checkpoints(self):
        resp = streaming_status("exec-1", _Engine([SUMMARIZED]))
        score = {n.node: n for n in resp.pipelines[0].nodes}["score"]
        assert (score.source, score.sink) == ("kafka topic events", "delta data/silver")
        assert (score.trigger, score.checkpoint) == (
            "every 5 seconds",
            "data/_ckpt/score/live/score",
        )

    def test_a_node_without_a_summary_has_none(self):
        enrich = {n.node: n for n in streaming_status("e", _Engine([SNAPSHOT])).pipelines[0].nodes}[
            "enrich"
        ]
        assert (enrich.source, enrich.checkpoint) == (None, None)

    def test_a_quiet_source_is_idle_not_failed(self):
        snap = {
            **SNAPSHOT,
            "progress_metrics": {"score": {"batchId": 8, "numInputRows": 0, "idleSeconds": 185.0}},
        }
        score = {n.node: n for n in streaming_status("e", _Engine([snap])).pipelines[0].nodes}[
            "score"
        ]
        assert (score.state, score.health, score.error, score.idle_seconds) == (
            "active",
            "idle",
            None,
            185.0,
        )

    def test_a_stall_is_a_warning_on_a_running_query(self):
        snap = {
            **SNAPSHOT,
            "health_monitors": {
                "score": {"error": "Query stalled: no progress for 400.0s (timeout: 300.0s)"}
            },
        }
        score = {n.node: n for n in streaming_status("e", _Engine([snap])).pipelines[0].nodes}[
            "score"
        ]
        assert (score.state, score.health, score.error) == ("active", "stalled", None)

    def test_recent_input_is_not_idle(self):
        snap = {**SNAPSHOT, "progress_metrics": {"score": {"numInputRows": 50, "idleSeconds": 0.0}}}
        score = {n.node: n for n in streaming_status("e", _Engine([snap])).pipelines[0].nodes}[
            "score"
        ]
        assert score.health is None


class _Restartable(_Engine):
    def __init__(self, snapshot, result=True):
        super().__init__(snapshot)
        self.calls = []
        self._result = result

    def restart_streaming_node(self, stream_execution_id, node):
        self.calls.append((stream_execution_id, node))
        return self._result


def _client_for(engines, roles):
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: User(
        id="u", username="u", email="u@example.com", roles=roles
    )
    app.dependency_overrides[get_execution_manager] = lambda: _Manager(engines)
    return TestClient(app)


class TestRestartingANode:
    URL = "/api/executions/running/streaming/stream-1/nodes/score/restart"

    def test_it_restarts_just_that_node(self):
        engine = _Restartable([SNAPSHOT])
        r = _client_for({"running": engine}, ["operator"]).post(self.URL)
        assert r.status_code == 200, r.text
        assert r.json() == {"restarted": True, "node": "score"}
        assert engine.calls == [("stream-1", "score")]

    def test_a_node_that_could_not_restart_says_so(self):
        engine = _Restartable([SNAPSHOT], result=False)
        r = _client_for({"running": engine}, ["operator"]).post(self.URL)
        assert r.json() == {"restarted": False, "node": "score"}

    def test_a_viewer_may_look_but_not_restart(self):
        engine = _Restartable([SNAPSHOT])
        r = _client_for({"running": engine}, ["viewer"]).post(self.URL)
        assert r.status_code == 403
        assert engine.calls == []

    def test_an_execution_holding_no_stream_is_a_conflict(self):
        r = _client_for({"running": None}, ["operator"]).post(self.URL)
        assert r.status_code == 409

    def test_an_unknown_execution_is_404(self):
        r = _client_for({}, ["operator"]).post(self.URL)
        assert r.status_code == 404
