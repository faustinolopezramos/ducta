"""Streaming nodes whose dependencies were satisfied outside this sub-pipeline.

``_process_pipeline_nodes`` decides a node is startable by looking its
``depends_on`` entries up in ``node_outcomes`` — the outcomes of the nodes *in
this execution*. That is right for a standalone streaming pipeline, where a
dependency nobody in the pipeline produced is genuinely unresolvable.

It is wrong for the streaming phase of a hybrid pipeline, where the batch phase
has already run to completion and only the streaming node names are handed to
the manager. A streaming node declaring ``depends_on: [<a batch node>]`` had that
dependency looked up, not found, and was skipped — every time, on a dependency
that had in fact been satisfied minutes earlier.

``satisfied_dependencies`` lets the caller say which names are already done,
without weakening the check for anyone who does not pass it.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

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


def _register(manager, execution_id, pipeline_config):
    from threading import Event

    manager._running_pipelines[execution_id] = {
        "pipeline_name": "hybrid__streaming",
        "pipeline_config": pipeline_config,
        "status": "starting",
        "start_time": 0,
        "queries": {},
        "completed_nodes": 0,
        "failed_nodes": {},
        "skipped_nodes": {},
        "error": None,
    }
    manager._pipeline_events[execution_id] = Event()
    manager._pipeline_stop_events[execution_id] = Event()


class TestExternallySatisfiedDependencies:
    def test_batch_dependency_declared_satisfied_lets_the_node_start(
        self, manager, mock_streaming_query
    ):
        """The hybrid case: 'extract' ran in the batch phase and is not here."""
        manager.query_manager.create_and_start_query = MagicMock(
            side_effect=lambda cfg, eid, name: mock_streaming_query(
                name=cfg["name"], query_id=cfg["name"]
            )
        )
        nodes = [_node("enrich", depends_on=["extract"])]
        _register(manager, "e1", {"nodes": nodes, "satisfied_dependencies": ["extract"]})

        processed = manager._process_pipeline_nodes(
            "e1", "hybrid__streaming", nodes, satisfied_dependencies={"extract"}
        )

        assert processed == ["enrich"]
        assert manager._running_pipelines["e1"]["skipped_nodes"] == {}

    def test_unsatisfied_dependency_still_skips(self, manager, mock_streaming_query):
        """A standalone streaming pipeline must keep rejecting a dangling dep."""
        manager.query_manager.create_and_start_query = MagicMock(
            side_effect=lambda cfg, eid, name: mock_streaming_query(
                name=cfg["name"], query_id=cfg["name"]
            )
        )
        nodes = [_node("enrich", depends_on=["nowhere"])]
        _register(manager, "e2", {"nodes": nodes})

        processed = manager._process_pipeline_nodes("e2", "stream", nodes)

        assert processed == []
        assert "enrich" in manager._running_pipelines["e2"]["skipped_nodes"]

    def test_in_pipeline_ordering_is_unaffected(self, manager, mock_streaming_query):
        """Satisfied externals must not short-circuit real in-pipeline waves."""
        started = []

        def fake_create(cfg, eid, name):
            started.append(cfg["name"])
            return mock_streaming_query(name=cfg["name"], query_id=cfg["name"])

        manager.query_manager.create_and_start_query = MagicMock(side_effect=fake_create)
        nodes = [_node("b", depends_on=["a", "extract"]), _node("a")]
        _register(manager, "e3", {"nodes": nodes})

        processed = manager._process_pipeline_nodes(
            "e3", "hybrid__streaming", nodes, satisfied_dependencies={"extract"}
        )

        assert set(processed) == {"a", "b"}
        assert started.index("a") < started.index("b")


class TestStartupCompletionSignal:
    """Callers need to know when the startup pass is over, not just when the
    queries have terminated. Without it, hybrid reported every node as started
    the instant ``start_pipeline`` returned its execution id."""

    def test_wait_returns_after_startup_finishes(self, manager, mock_streaming_query):
        manager.query_manager.create_and_start_query = MagicMock(
            side_effect=lambda cfg, eid, name: mock_streaming_query(
                name=cfg["name"], query_id=cfg["name"]
            )
        )
        execution_id = manager.start_pipeline("p", {"nodes": [_node("a")]})

        assert manager.wait_for_pipeline_started(execution_id, timeout=5.0) is True
        assert "a" in manager._running_pipelines[execution_id]["queries"]

    def test_wait_returns_even_when_every_node_is_skipped(self, manager, mock_streaming_query):
        """A node deferred forever behind a failed sibling still ends startup."""

        def fake_create(cfg, eid, name):
            if cfg["name"] == "a":
                raise RuntimeError("a will not start")
            return mock_streaming_query(name=cfg["name"], query_id=cfg["name"])

        manager.query_manager.create_and_start_query = MagicMock(side_effect=fake_create)
        execution_id = manager.start_pipeline(
            "p", {"nodes": [_node("a"), _node("b", depends_on=["a"])]}
        )

        assert manager.wait_for_pipeline_started(execution_id, timeout=5.0) is True
        assert manager._running_pipelines[execution_id]["skipped_nodes"]

    def test_wait_returns_when_a_dangling_dependency_aborts_ordering(self, manager):
        """A dependency nobody satisfies is rejected while ordering the nodes.

        That raises before any query is created, so the whole startup ends in
        ``error``. The waiter must still be released — this is the case that
        would otherwise block for the caller's full timeout.
        """
        manager.query_manager.create_and_start_query = MagicMock(
            side_effect=AssertionError("must not be called")
        )
        execution_id = manager.start_pipeline("p", {"nodes": [_node("a", depends_on=["nowhere"])]})

        assert manager.wait_for_pipeline_started(execution_id, timeout=5.0) is True
        assert manager._running_pipelines[execution_id]["status"] == "error"

    def test_wait_returns_when_startup_raises(self, manager):
        manager.query_manager.create_and_start_query = MagicMock(side_effect=RuntimeError("boom"))
        execution_id = manager.start_pipeline("p", {"nodes": [_node("a")]})

        assert manager.wait_for_pipeline_started(execution_id, timeout=5.0) is True

    def test_unknown_execution_id_does_not_hang(self, manager):
        assert manager.wait_for_pipeline_started("nope", timeout=0.1) is True
