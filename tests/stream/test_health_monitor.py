"""Unit tests for ducta.stream.pipeline_manager.QueryHealthMonitor."""

from __future__ import annotations

from ducta.stream.pipeline_manager import QueryHealthMonitor, StreamingPipelineManager


class FakeQuery:
    def __init__(self, active=True, progress=None, exc=None):
        self._active = active
        self.lastProgress = progress
        self._exc = exc

    def isActive(self):  # noqa: N802 - mirrors Spark API
        return self._active

    def exception(self):
        return self._exc


class TestQueryHealthMonitor:
    def test_active_query_is_healthy(self):
        mon = QueryHealthMonitor(FakeQuery(active=True, progress=None), "q1")
        healthy, error = mon.check_health()
        assert healthy is True
        assert error is None

    def test_failed_query_reports_exception(self):
        q = FakeQuery(active=False, exc=RuntimeError("boom"))
        mon = QueryHealthMonitor(q, "q1")
        healthy, error = mon.check_health()
        assert healthy is False
        assert "boom" in error

    def test_inactive_clean_query(self):
        mon = QueryHealthMonitor(FakeQuery(active=False, exc=None), "q1")
        healthy, error = mon.check_health()
        assert healthy is False
        assert error is None

    def test_status_dict_shape(self):
        mon = QueryHealthMonitor(FakeQuery(active=True), "node_x")
        status = mon.get_status_dict()
        assert status["query_name"] == "node_x"
        assert status["is_active"] is True


class TestCollectQueryExceptions:
    def test_collects_only_failed(self):
        queries = [
            FakeQuery(exc=RuntimeError("err1")),
            FakeQuery(exc=None),
        ]
        errors = StreamingPipelineManager._collect_query_exceptions(queries)
        assert len(errors) == 1
        assert "err1" in errors[0]
