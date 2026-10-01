"""A node reading the output of a node with a terminating trigger waits for it.

Dependants were started as soon as their upstream query *started*. That is
right for continuous streams, but with ``once``/``available_now`` the upstream
processes what exists and stops: a dependant started alongside it read an
empty source and stopped as well, so an ``available_now`` backfill of a
bronze → silver chain wrote nothing to silver.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ducta.stream.pipeline_manager import StreamingPipelineManager
from tests.stream.test_pipeline_manager_external_deps import _node, _register


@pytest.fixture
def manager(obj_context):
    with patch("ducta.stream.pipeline_manager.listener_available", return_value=False):
        mgr = StreamingPipelineManager(obj_context, max_concurrent_pipelines=5)
    mgr.validator.validate_streaming_pipeline_config = MagicMock()
    return mgr


def _with_trigger(node, trigger):
    return {**node, "streaming": {"trigger": {"type": trigger}}}


def _run(manager, mock_streaming_query, nodes, events):
    def fake_create(cfg, eid, name):
        events.append(f"start:{cfg['name']}")
        query = mock_streaming_query(name=cfg["name"], query_id=cfg["name"])

        def await_termination(timeout=None):
            events.append(f"awaited:{cfg['name']}")
            return True

        query.awaitTermination = await_termination
        return query

    manager.query_manager.create_and_start_query = MagicMock(side_effect=fake_create)
    _register(manager, "e1", {"nodes": nodes})
    return manager._process_pipeline_nodes("e1", "stream", nodes)


@pytest.mark.parametrize("trigger", ["available_now", "once"])
def test_the_dependant_starts_after_a_terminating_upstream_finishes(
    manager, mock_streaming_query, trigger
):
    events: list = []
    nodes = [
        _with_trigger(_node("bronze"), trigger),
        _with_trigger(_node("silver", depends_on=["bronze"]), trigger),
    ]
    assert _run(manager, mock_streaming_query, nodes, events) == ["bronze", "silver"]
    assert events == ["start:bronze", "awaited:bronze", "start:silver"]


def test_a_continuous_upstream_is_not_waited_for(manager, mock_streaming_query):
    events: list = []
    nodes = [
        _with_trigger(_node("bronze"), "processing_time"),
        _node("silver", depends_on=["bronze"]),
    ]
    _run(manager, mock_streaming_query, nodes, events)
    assert events == ["start:bronze", "start:silver"]


def test_a_terminating_node_nobody_depends_on_is_not_waited_for(manager, mock_streaming_query):
    events: list = []
    _run(manager, mock_streaming_query, [_with_trigger(_node("only"), "available_now")], events)
    assert events == ["start:only"]
