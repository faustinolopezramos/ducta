"""Hybrid must report what actually happened to its streaming nodes.

``_execute_streaming_phase`` called ``start_pipeline``, got an execution id back
and immediately marked every node it had handed over as completed. But
``start_pipeline`` is asynchronous: it submits the startup work and returns
before a single query exists. So the id proved only that the work had been
*queued*, and hybrid reported a clean success for runs in which every streaming
query was skipped or failed to start.

Combined with the dependency-lookup bug (see
``tests/stream/test_pipeline_manager_external_deps.py``), a hybrid pipeline whose
streaming node depended on a batch node reported success while doing nothing at
all.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from ducta.core.executors.hybrid import HybridExecutor
from ducta.core.pipeline_state import NodeType, UnifiedPipelineState


class FakeStreamingManager:
    """Records what it was asked to start and reports a canned outcome."""

    def __init__(self, skipped=None, failed=None, started=None):
        self.skipped = skipped or {}
        self.failed = failed or {}
        self.started = started if started is not None else []
        self.start_calls: List[Dict[str, Any]] = []
        self.waited: List[str] = []

    def start_pipeline(self, name: str, pipeline_config: Dict[str, Any]) -> str:
        self.start_calls.append({"name": name, "config": pipeline_config})
        return "exec-1"

    def wait_for_pipeline_started(self, execution_id: str, timeout: Optional[float] = None):
        self.waited.append(execution_id)
        return True

    def get_pipeline_status(self, execution_id: str) -> Dict[str, Any]:
        # Mirrors StreamingPipelineManager.get_pipeline_status, which strips the
        # live `queries` handles and reports their names under `query_statuses`.
        # Getting this wrong in the fake is not a harmless detail: it made these
        # tests pass against a reader that found nothing in the real object, and
        # the run reported "started no queries" for a pipeline whose queries had
        # both started. See TestFakeMatchesTheRealManager below.
        return {
            "skipped_nodes": self.skipped,
            "failed_nodes": self.failed,
            "query_statuses": {n: {"is_active": True} for n in self.started},
        }

    def stop_pipeline(self, execution_id: str, graceful: bool = True) -> bool:
        return True


def _executor(streaming_manager, batch_nodes=("extract",), streaming_nodes=("enrich",)):
    executor = HybridExecutor.__new__(HybridExecutor)
    executor.streaming_manager = streaming_manager
    executor._mlops_pipeline_name = "hybrid_pipe"
    state = UnifiedPipelineState()
    for node in batch_nodes:
        state.register_node(node, NodeType.BATCH, [])
    for node in streaming_nodes:
        state.register_node(node, NodeType.STREAMING, list(batch_nodes))
    for node in batch_nodes:
        state.start_node_execution(node)
        state.complete_node_execution(node)
    executor.unified_state = state
    return executor


class TestStreamingPhaseReportsRealOutcomes:
    def test_a_skipped_node_is_not_reported_as_completed(self):
        manager = FakeStreamingManager(skipped={"enrich": "unmet deps"})
        executor = _executor(manager)

        executor._execute_streaming_phase(["enrich"], {}, "async")

        assert executor.unified_state.get_node_status("enrich").value != "completed"

    def test_a_started_node_is_reported_as_completed(self):
        manager = FakeStreamingManager(started=["enrich"])
        executor = _executor(manager)

        executor._execute_streaming_phase(["enrich"], {}, "async")

        assert executor.unified_state.get_node_status("enrich").value == "completed"

    def test_it_waits_for_startup_before_judging(self):
        manager = FakeStreamingManager(started=["enrich"])
        executor = _executor(manager)

        executor._execute_streaming_phase(["enrich"], {}, "async")

        assert manager.waited == ["exec-1"], "must not judge before startup finishes"

    def test_completed_batch_nodes_are_declared_satisfied(self):
        """Without this the manager looks 'extract' up among the streaming nodes,
        does not find it, and skips the node that depends on it."""
        manager = FakeStreamingManager(started=["enrich"])
        executor = _executor(manager)

        executor._execute_streaming_phase(["enrich"], {}, "async")

        config = manager.start_calls[0]["config"]
        assert "extract" in set(config.get("satisfied_dependencies") or [])


class TestRunStatusFollowsTheStreamingPhase:
    def _phase(self, streaming_ids, batch_results=None):
        executor = HybridExecutor.__new__(HybridExecutor)
        executor._execute_batch_phase = lambda *a, **k: (
            batch_results if batch_results is not None else {"extract": {"status": "completed"}}
        )
        executor._execute_streaming_phase = lambda *a, **k: streaming_ids
        return executor._execute_unified_hybrid_pipeline(
            batch_nodes=["extract"],
            streaming_nodes=["enrich"],
            node_configs={},
            start_date="2024-01-01",
            end_date="2024-01-02",
            ml_info={},
            execution_mode="async",
        )

    def test_a_streaming_phase_that_started_nothing_is_not_a_success(self):
        result = self._phase(streaming_ids=[])

        assert result["status"] == "failed"
        assert result["errors"]

    def test_a_streaming_phase_that_started_is_a_success(self):
        result = self._phase(streaming_ids=["exec-1"])

        assert result["status"] == "success"
        assert result["streaming_execution_ids"] == ["exec-1"]

    def test_a_halted_batch_phase_is_still_not_a_failure(self):
        """Guard: the gate-blocked semantics from test_hybrid_gate_blocked.py
        must survive this change — no streaming ids, but not an error either."""
        result = self._phase(
            streaming_ids=[], batch_results={"extract": {"status": "gate_blocked", "error": "x"}}
        )

        assert result["status"] == "success"
        assert result["errors"] == []


class TestFakeMatchesTheRealManager:
    """Pin the contract the fake above stands in for.

    ``FakeStreamingManager`` originally reported started nodes under ``queries``
    — the key the real manager holds *internally* and deliberately removes from
    what ``get_pipeline_status`` returns. The tests passed and the feature did
    not: the hybrid executor and the CLI both read a key that is never present,
    concluded nothing had started, and failed runs whose queries were running.

    A fake is only worth having if it is wrong in the same places the real thing
    is, so this asserts the key against the real implementation.
    """

    def test_status_reports_started_nodes_under_query_statuses(self):
        from threading import Event
        from unittest.mock import MagicMock, patch

        from ducta.stream.pipeline_manager import StreamingPipelineManager

        context = MagicMock()
        context.global_config = {}
        context.nodes_config = {}
        with patch("ducta.stream.pipeline_manager.listener_available", return_value=False):
            manager = StreamingPipelineManager(context, max_concurrent_pipelines=1)

        query = MagicMock()
        query.isActive = True
        query.exception.return_value = None
        manager._running_pipelines["e1"] = {
            "pipeline_name": "p",
            "pipeline_config": {},
            "status": "running",
            "start_time": 0,
            "queries": {"enrich": query},
            "completed_nodes": 1,
            "failed_nodes": {},
            "skipped_nodes": {},
            "error": None,
        }
        manager._pipeline_events["e1"] = Event()

        status = manager.get_pipeline_status("e1")

        assert "queries" not in status, "the live handles are stripped on purpose"
        assert "enrich" in (status.get("query_statuses") or {})
