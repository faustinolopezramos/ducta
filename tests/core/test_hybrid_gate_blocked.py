"""A blocking quality gate must mean the same thing in hybrid as it does in batch.

`skip_downstream` is deliberately not a failure: the run finishes, the blocked
node's descendants are skipped, and the result comes back `GATE_BLOCKED`. Hybrid
lumped `gate_blocked` in with `failed` when deciding whether its batch phase had
succeeded, so the identical gate aborted a hybrid pipeline with an exception —
and took the rest of the pipeline chain down with it — while leaving a batch one
to finish.

These also pin the interaction that makes the fix work: the facade can only
report `GATE_BLOCKED` because `absorb_trace` now runs before `resolve_status`.
`_execute_unified_hybrid_pipeline` had no coverage at all.
"""

from __future__ import annotations

import pytest

from ducta.core.executors.hybrid import HybridExecutor


def _phase(batch_results):
    """Drive `_execute_unified_hybrid_pipeline` with a canned batch outcome."""
    executor = HybridExecutor.__new__(HybridExecutor)
    executor._execute_batch_phase = lambda *a, **k: batch_results
    executor._execute_streaming_phase = lambda *a, **k: ["stream-1"]
    return executor._execute_unified_hybrid_pipeline(
        batch_nodes=list(batch_results),
        streaming_nodes=["live"],
        node_configs={},
        start_date="2024-01-01",
        end_date="2024-01-02",
        ml_info={},
        execution_mode="async",
    )


class TestGateBlockIsNotAFailure:
    def test_a_blocked_gate_does_not_fail_the_run(self):
        result = _phase({"clean": {"status": "gate_blocked", "error": "null_rate too high"}})

        assert result["status"] == "success"
        assert result["errors"] == []

    def test_a_blocked_gate_still_stops_the_streaming_phase(self):
        # Not a failure, but the streaming queries would consume data the blocked
        # node never wrote.
        result = _phase({"clean": {"status": "gate_blocked", "error": "null_rate too high"}})

        assert result["streaming_execution_ids"] == []

    def test_a_skip_behaves_the_same_way(self):
        result = _phase({"clean": {"status": "skipped", "reason": "missing inputs"}})

        assert result["status"] == "success"
        assert result["streaming_execution_ids"] == []

    def test_a_real_failure_still_fails_and_stops_streaming(self):
        result = _phase({"clean": {"status": "failed", "error": "boom"}})

        assert result["status"] == "failed"
        assert result["streaming_execution_ids"] == []
        assert "boom" in result["errors"][0]

    def test_a_clean_batch_phase_starts_the_streaming_phase(self):
        result = _phase({"clean": {"status": "completed"}})

        assert result["status"] == "success"
        assert result["streaming_execution_ids"] == ["stream-1"]

    def test_a_failure_alongside_a_gate_block_still_fails(self):
        result = _phase(
            {
                "clean": {"status": "gate_blocked", "error": "rejected"},
                "load": {"status": "failed", "error": "boom"},
            }
        )

        assert result["status"] == "failed"
        # Only the genuine failure is reported as an error.
        assert len(result["errors"]) == 1
        assert "load" in result["errors"][0]


class TestTheFacadeReportsItAsGateBlocked:
    """The end the user sees: a returned result, not an exception."""

    def _engine(self, hybrid_result, gate_blocked):
        from ducta.core.executors.facade import PipelineExecutor
        from tests.core.fakes import FakeContext

        pipelines = {"p": {"name": "p", "nodes": ["clean"], "type": "hybrid"}}
        context = FakeContext(
            nodes_config={"clean": {"module": "m", "function": "f"}},
            pipelines_config=pipelines,
            global_settings={"preflight_enabled": False, "enable_run_certificate": False},
        )
        engine = PipelineExecutor(context)

        class _StubHybrid:
            def __init__(self):
                self.node_executor = type("NE", (), {"gate_blocked": gate_blocked})()

            def execute(self, *a, **k):
                return hybrid_result

        engine._hybrid_executor = _StubHybrid()
        return engine

    def test_a_gate_blocked_hybrid_returns_instead_of_raising(self):
        from ducta.core.results import RunStatus

        engine = self._engine(
            hybrid_result={
                "status": "success",
                "errors": [],
                "streaming_execution_ids": [],
                "batch_execution": {},
            },
            gate_blocked={"clean": {"error": "null_rate too high"}},
        )

        result = engine.run_pipeline("p", start_date="2024-01-01", end_date="2024-01-02")

        assert result.status is RunStatus.GATE_BLOCKED
        assert not result.ok  # a gate block is not a success
        assert "clean" in result.gate_blocked

    def test_a_failed_hybrid_still_raises(self):
        from ducta.core.errors import PipelineExecutionError

        engine = self._engine(
            hybrid_result={
                "status": "failed",
                "errors": ["Batch node failed: clean - boom"],
                "streaming_execution_ids": [],
                "batch_execution": {},
            },
            gate_blocked={},
        )

        with pytest.raises(PipelineExecutionError):
            engine.run_pipeline("p", start_date="2024-01-01", end_date="2024-01-02")
