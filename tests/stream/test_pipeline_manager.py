"""Unit tests for StreamingPipelineManager orchestration: waves/dependencies,
stop/restart, status, and metrics. QueryHealthMonitor's own logic is already
covered by test_health_monitor.py — only its integration is touched here.

create_and_start_query is always patched on the manager's query_manager so
these tests exercise orchestration, not query_manager internals (covered in
test_query_manager_lifecycle.py).
"""

from __future__ import annotations

import time
from threading import Event, Thread
from unittest.mock import MagicMock, patch

import pytest

from ducta.stream.exceptions import StreamingPipelineError
from ducta.stream.pipeline_manager import StreamingPipelineManager


@pytest.fixture
def manager(obj_context):
    with patch("ducta.stream.pipeline_manager.listener_available", return_value=False):
        mgr = StreamingPipelineManager(obj_context, max_concurrent_pipelines=5)
    mgr.validator.validate_streaming_pipeline_config = MagicMock()
    return mgr


def _node(name, depends_on=None):
    node = {
        "name": name,
        "input": {"format": "file_stream", "path": f"/tmp/{name}"},
        "output": {"format": "console"},
    }
    if depends_on:
        node["depends_on"] = depends_on
    return node


class TestExecutePipelineOrchestration:
    def test_independent_nodes_all_started(self, manager, mock_streaming_query):
        queries = {}

        def fake_create(node_config, execution_id, pipeline_name):
            name = node_config["name"]
            q = mock_streaming_query(name=name, query_id=name)
            queries[name] = q
            return q

        manager.query_manager.create_and_start_query = MagicMock(side_effect=fake_create)
        pipeline_config = {"nodes": [_node("a"), _node("b")]}
        execution_id = "exec1"
        manager._running_pipelines[execution_id] = {
            "pipeline_name": "p1",
            "pipeline_config": pipeline_config,
            "status": "starting",
            "start_time": 0,
            "queries": {},
            "completed_nodes": 0,
            "failed_nodes": {},
            "skipped_nodes": {},
            "error": None,
        }
        manager._pipeline_events[execution_id] = MagicMock()

        manager._execute_pipeline(execution_id, "p1", pipeline_config)

        info = manager._running_pipelines[execution_id]
        assert set(info["queries"].keys()) == {"a", "b"}
        assert info["status"] == "running"

    @pytest.mark.parametrize("key", ["depends_on", "dependencies"])
    def test_dependent_node_starts_after_dependency(self, manager, mock_streaming_query, key):
        """Both spellings order streaming nodes. `dependencies` — the key batch
        nodes use — used to be ignored here, so `b` could start before `a`."""
        start_order = []

        def fake_create(node_config, execution_id, pipeline_name):
            name = node_config["name"]
            start_order.append(name)
            return mock_streaming_query(name=name, query_id=name)

        manager.query_manager.create_and_start_query = MagicMock(side_effect=fake_create)
        b = _node("b")
        b[key] = ["a"]
        pipeline_config = {"nodes": [b, _node("a")]}
        execution_id = "exec2"
        manager._running_pipelines[execution_id] = {
            "pipeline_name": "p1",
            "pipeline_config": pipeline_config,
            "status": "starting",
            "start_time": 0,
            "queries": {},
            "completed_nodes": 0,
            "failed_nodes": {},
            "skipped_nodes": {},
            "error": None,
        }
        manager._pipeline_events[execution_id] = MagicMock()

        manager._execute_pipeline(execution_id, "p1", pipeline_config)

        assert start_order.index("a") < start_order.index("b")

    def test_node_with_failed_dependency_is_skipped(self, manager, mock_streaming_query):
        def fake_create(node_config, execution_id, pipeline_name):
            if node_config["name"] == "a":
                raise RuntimeError("boom")
            return mock_streaming_query(name=node_config["name"])

        manager.query_manager.create_and_start_query = MagicMock(side_effect=fake_create)
        manager._is_transient_start_error = MagicMock(return_value=False)
        pipeline_config = {"nodes": [_node("a"), _node("b", depends_on=["a"])]}
        execution_id = "exec3"
        manager._running_pipelines[execution_id] = {
            "pipeline_name": "p1",
            "pipeline_config": pipeline_config,
            "status": "starting",
            "start_time": 0,
            "queries": {},
            "completed_nodes": 0,
            "failed_nodes": {},
            "skipped_nodes": {},
            "error": None,
        }
        manager._pipeline_events[execution_id] = MagicMock()

        manager._execute_pipeline(execution_id, "p1", pipeline_config)

        info = manager._running_pipelines[execution_id]
        assert "b" in info["skipped_nodes"]
        assert "a" not in info["queries"]


class TestOrderNodesByDependencies:
    def test_orders_linear_chain(self, manager):
        nodes = [_node("c", depends_on=["b"]), _node("a"), _node("b", depends_on=["a"])]
        ordered = manager._order_nodes_by_dependencies(nodes)
        names = [n["name"] for n in ordered]
        assert names.index("a") < names.index("b") < names.index("c")

    def test_cycle_raises_pipeline_error(self, manager):
        nodes = [_node("a", depends_on=["b"]), _node("b", depends_on=["a"])]
        with pytest.raises(StreamingPipelineError):
            manager._order_nodes_by_dependencies(nodes)


class TestStopPipeline:
    def test_stop_unknown_execution_returns_false(self, manager):
        assert manager.stop_pipeline("does-not-exist") is False

    def test_stop_active_pipeline_stops_all_queries(self, manager, mock_streaming_query):
        q1 = mock_streaming_query(name="a", query_id="a")
        q2 = mock_streaming_query(name="b", query_id="b")
        execution_id = "exec1"
        manager._running_pipelines[execution_id] = {
            "pipeline_name": "p1",
            "pipeline_config": {},
            "status": "running",
            "start_time": 0,
            "queries": {"a": q1, "b": q2},
            "completed_nodes": 2,
            "failed_nodes": {},
            "skipped_nodes": {},
            "error": None,
        }
        manager._pipeline_events[execution_id] = MagicMock()

        result = manager.stop_pipeline(execution_id)

        assert result is True
        assert q1.isActive() is False
        assert q2.isActive() is False
        assert manager._running_pipelines[execution_id]["status"] == "stopped"

    def test_stop_already_inactive_query_counted_as_stopped(self, manager, mock_streaming_query):
        q1 = mock_streaming_query(name="a", query_id="a", active=False)
        execution_id = "exec1"
        manager._running_pipelines[execution_id] = {
            "pipeline_name": "p1",
            "pipeline_config": {},
            "status": "running",
            "start_time": 0,
            "queries": {"a": q1},
            "completed_nodes": 1,
            "failed_nodes": {},
            "skipped_nodes": {},
            "error": None,
        }
        manager._pipeline_events[execution_id] = MagicMock()

        assert manager.stop_pipeline(execution_id) is True

    def test_stop_pipeline_survives_concurrent_queries_dict_mutation(
        self, manager, mock_streaming_query
    ):
        """Regression: _stop_pipeline_queries must iterate a snapshot, not the
        live pipeline_info["queries"] dict, otherwise a concurrent node-start
        wave inserting into it mid-iteration raises
        "RuntimeError: dictionary changed size during iteration"."""
        q1 = mock_streaming_query(name="a", query_id="a")
        execution_id = "exec1"
        manager._running_pipelines[execution_id] = {
            "pipeline_name": "p1",
            "pipeline_config": {},
            "status": "running",
            "start_time": 0,
            "queries": {"a": q1},
            "completed_nodes": 1,
            "failed_nodes": {},
            "skipped_nodes": {},
            "error": None,
        }
        manager._pipeline_events[execution_id] = MagicMock()

        original_stop_query = manager.query_manager.stop_query
        inserted = False

        def stop_query_side_effect(query, *args, **kwargs):
            # Simulate a concurrent node-start wave inserting into the *live*
            # queries dict while stop_pipeline is (conceptually) iterating it
            # — once, like a real node-start wave finishing a single node,
            # not on every stop_query call (which would also fire for the
            # re-check pass's own call to stop "b").
            nonlocal inserted
            if not inserted:
                inserted = True
                manager._running_pipelines[execution_id]["queries"]["b"] = mock_streaming_query(
                    name="b", query_id="b"
                )
            return original_stop_query(query, *args, **kwargs)

        manager.query_manager.stop_query = MagicMock(side_effect=stop_query_side_effect)

        result = manager.stop_pipeline(execution_id)  # must not raise RuntimeError

        assert result is True
        # Regression: a query added to the live dict after the initial
        # snapshot (simulating a concurrent node-start wave finishing just
        # after stop_pipeline() took its snapshot) used to be left running —
        # stop_pipeline() re-checks and stops it too now.
        assert manager._running_pipelines[execution_id]["queries"]["b"].isActive() is False

    def test_stop_sets_the_per_execution_stop_event(self, manager, mock_streaming_query):
        """Regression: stop_pipeline() must signal cancellation to any
        in-flight node-start wave/retry for *this* execution_id — the global
        _shutdown_event alone would also stop every other pipeline the
        manager is running."""
        execution_id = "exec1"
        manager._running_pipelines[execution_id] = {
            "pipeline_name": "p1",
            "pipeline_config": {},
            "status": "running",
            "start_time": 0,
            "queries": {},
            "completed_nodes": 0,
            "failed_nodes": {},
            "skipped_nodes": {},
            "error": None,
        }
        manager._pipeline_events[execution_id] = MagicMock()
        manager._pipeline_stop_events[execution_id] = Event()

        manager.stop_pipeline(execution_id)

        assert manager._pipeline_stop_events[execution_id].is_set() is True
        assert manager._shutdown_event.is_set() is False  # other pipelines unaffected


class TestRestartNode:
    def test_restart_unknown_execution_returns_false(self, manager):
        assert manager.restart_node("missing", "n1") is False

    def test_restart_unknown_node_returns_false(self, manager):
        execution_id = "exec1"
        manager._running_pipelines[execution_id] = {
            "pipeline_name": "p1",
            "pipeline_config": {"nodes": [_node("a")]},
            "status": "running",
            "queries": {},
        }
        assert manager.restart_node(execution_id, "ghost") is False

    def test_restart_success_replaces_query(self, manager, mock_streaming_query):
        old_query = mock_streaming_query(name="a", query_id="old")
        new_query = mock_streaming_query(name="a", query_id="new")
        manager.query_manager.create_and_start_query = MagicMock(return_value=new_query)

        execution_id = "exec1"
        manager._running_pipelines[execution_id] = {
            "pipeline_name": "p1",
            "pipeline_config": {"nodes": [_node("a")]},
            "status": "running",
            "queries": {"a": old_query},
            "failed_nodes": {"a": "previous error"},
        }

        result = manager.restart_node(execution_id, "a")

        assert result is True
        assert manager._running_pipelines[execution_id]["queries"]["a"] is new_query
        assert "a" not in manager._running_pipelines[execution_id]["failed_nodes"]
        assert old_query.isActive() is False


class TestPipelineStatusAndMetrics:
    def test_get_pipeline_status_unknown_returns_none(self, manager):
        assert manager.get_pipeline_status("missing", force_refresh=True) is None

    def test_get_pipeline_status_includes_query_counts(self, manager, mock_streaming_query):
        q1 = mock_streaming_query(name="a", query_id="a", active=True)
        execution_id = "exec1"
        manager._running_pipelines[execution_id] = {
            "pipeline_name": "p1",
            "pipeline_config": {},
            "status": "running",
            "start_time": 0,
            "queries": {"a": q1},
            "completed_nodes": 1,
            "failed_nodes": {},
            "skipped_nodes": {},
            "error": None,
        }
        status = manager.get_pipeline_status(execution_id, force_refresh=True)
        assert status["total_queries"] == 1
        assert status["active_queries"] == 1
        assert status["execution_id"] == execution_id

    def test_status_cache_serves_fresh_reads(self, manager, mock_streaming_query):
        q1 = mock_streaming_query(name="a", query_id="a")
        execution_id = "exec1"
        manager._status_cache_ttl = 60.0
        manager._running_pipelines[execution_id] = {
            "pipeline_name": "p1",
            "pipeline_config": {},
            "status": "running",
            "start_time": 0,
            "queries": {"a": q1},
            "completed_nodes": 1,
            "failed_nodes": {},
            "skipped_nodes": {},
            "error": None,
        }
        first = manager.get_pipeline_status(execution_id, force_refresh=True)
        # Mutate underlying state without a force refresh — cached copy should win.
        manager._running_pipelines[execution_id]["completed_nodes"] = 99
        second = manager.get_pipeline_status(execution_id)
        assert second is first

    def test_list_running_pipelines_only_lists_active_statuses(self, manager, mock_streaming_query):
        manager._running_pipelines["exec1"] = {
            "pipeline_name": "p1",
            "pipeline_config": {},
            "status": "running",
            "start_time": 0,
            "queries": {},
            "completed_nodes": 0,
            "failed_nodes": {},
            "skipped_nodes": {},
            "error": None,
        }
        manager._running_pipelines["exec2"] = {
            "pipeline_name": "p2",
            "pipeline_config": {},
            "status": "stopped",
            "start_time": 0,
            "queries": {},
            "completed_nodes": 0,
            "failed_nodes": {},
            "skipped_nodes": {},
            "error": None,
        }
        pipelines = manager.list_running_pipelines()
        assert len(pipelines) == 1
        assert pipelines[0]["execution_id"] == "exec1"

    def test_get_pipeline_metrics_computes_health_score(self, manager, mock_streaming_query):
        q1 = mock_streaming_query(name="a", query_id="a")
        execution_id = "exec1"
        manager._running_pipelines[execution_id] = {
            "pipeline_name": "p1",
            "pipeline_config": {},
            "status": "running",
            "start_time": 0,
            "queries": {"a": q1},
            "completed_nodes": 1,
            "failed_nodes": {},
            "skipped_nodes": {},
            "error": None,
        }
        metrics = manager.get_pipeline_metrics(execution_id)
        assert metrics["performance_metrics"]["health_score"] == 100.0

    def test_get_pipeline_metrics_unknown_returns_none(self, manager):
        assert manager.get_pipeline_metrics("missing") is None


class TestProgressSinkCleanup:
    def test_signal_pipeline_done_forgets_progress_metrics(self, manager, mock_streaming_query):
        """Regression: _signal_pipeline_done must purge the progress sink,
        otherwise _latest/_trigger_ms grow forever (one set of keys per
        execution_id that never gets cleaned up)."""
        q1 = mock_streaming_query(name="p1_a_exec1", query_id="a")
        execution_id = "exec1"
        manager._running_pipelines[execution_id] = {
            "pipeline_name": "p1",
            "pipeline_config": {},
            "status": "running",
            "start_time": 0,
            "queries": {"a": q1},
            "completed_nodes": 1,
            "failed_nodes": {},
            "skipped_nodes": {},
            "error": None,
        }
        manager._pipeline_events[execution_id] = MagicMock()
        manager.progress_sink._latest["p1_a_exec1"] = {"batchId": 1}

        manager._signal_pipeline_done(execution_id)

        assert manager.progress_sink.get_latest("p1_a_exec1") is None


class TestNodeStartRetryShutdown:
    def test_shutdown_interrupts_in_flight_retry(self, manager):
        """Regression: the retry loop must react to _shutdown_event promptly
        instead of blocking out the full retry delay via time.sleep(), which
        shutdown()'s future.cancel() cannot interrupt once the thread is
        already running."""
        manager.node_start_retry_attempts = 50
        manager.node_start_retry_delay_seconds = 5.0
        manager._is_transient_start_error = MagicMock(return_value=True)
        manager.query_manager.create_and_start_query = MagicMock(
            side_effect=RuntimeError("PATH_NOT_FOUND")
        )

        def trigger_shutdown():
            time.sleep(0.05)
            manager._shutdown_event.set()

        Thread(target=trigger_shutdown, daemon=True).start()

        start = time.time()
        with pytest.raises(RuntimeError):
            manager._start_node_query_with_retry(
                execution_id="exec1",
                pipeline_name="p1",
                node_name="n1",
                node_config=_node("n1"),
            )
        elapsed = time.time() - start

        # Without the fix this would block ~5s (a full retry delay); with the
        # fix it aborts within a fraction of a second of the shutdown signal.
        assert elapsed < 2.0

    def test_per_execution_stop_event_interrupts_in_flight_retry_without_global_shutdown(
        self, manager
    ):
        """Regression: only a manager-wide _shutdown_event could interrupt a
        retry loop — stop_pipeline() on a single execution_id had no way to
        stop *its own* in-flight retry without also stopping every other
        pipeline the manager is running."""
        manager.node_start_retry_attempts = 50
        manager.node_start_retry_delay_seconds = 5.0
        manager._is_transient_start_error = MagicMock(return_value=True)
        manager.query_manager.create_and_start_query = MagicMock(
            side_effect=RuntimeError("PATH_NOT_FOUND")
        )
        manager._pipeline_stop_events["exec1"] = Event()

        def trigger_stop():
            time.sleep(0.05)
            manager._pipeline_stop_events["exec1"].set()

        Thread(target=trigger_stop, daemon=True).start()

        start = time.time()
        with pytest.raises(RuntimeError):
            manager._start_node_query_with_retry(
                execution_id="exec1",
                pipeline_name="p1",
                node_name="n1",
                node_config=_node("n1"),
            )
        elapsed = time.time() - start

        assert elapsed < 2.0
        assert manager._shutdown_event.is_set() is False  # other pipelines unaffected


class TestShutdown:
    def test_shutdown_stops_all_running_pipelines(self, manager, mock_streaming_query):
        q1 = mock_streaming_query(name="a", query_id="a")
        execution_id = "exec1"
        manager._running_pipelines[execution_id] = {
            "pipeline_name": "p1",
            "pipeline_config": {},
            "status": "running",
            "start_time": 0,
            "queries": {"a": q1},
            "completed_nodes": 1,
            "failed_nodes": {},
            "skipped_nodes": {},
            "error": None,
        }
        manager._pipeline_events[execution_id] = MagicMock()

        results = manager.shutdown(timeout_seconds=2)

        assert results[execution_id] is True
        assert manager._shutdown_event.is_set()

    def test_shutdown_with_no_pipelines_returns_empty(self, manager):
        assert manager.shutdown(timeout_seconds=1) == {}
