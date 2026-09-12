"""Regression: a failed hybrid pipeline did not stop the chain.

`HybridExecutor._execute_unified_hybrid_pipeline` reports failures in its result
dict instead of raising. `PipelineExecutor.run_pipeline` reflected that in the
run certificate but still `return`ed normally, so `run_pipeline_chain`'s
try/except never fired and every downstream pipeline ran against data its failed
ancestor never produced — while the CLI/API saw a successful call.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ducta.core.executors.facade import PipelineExecutor
from ducta.core.settings import CoreSettings


def _executor(pipeline_type="hybrid"):
    context = MagicMock()
    context.global_config = {
        "preflight_enabled": False,
        "enable_run_certificate": False,
        "start_date": "2024-01-01",
        "end_date": "2024-01-02",
    }
    engine = PipelineExecutor(context, settings=CoreSettings.from_context(context))
    pipeline_cfg = {"type": pipeline_type, "nodes": ["n1"], "requires_dates": False}

    batch = MagicMock()
    batch._get_pipeline_config.return_value = pipeline_cfg
    engine._batch_executor = batch
    engine._hybrid_executor = MagicMock()
    return engine


class TestHybridFailureSurfaces:
    def test_failed_hybrid_result_raises(self):
        engine = _executor()
        engine._hybrid_executor.execute.return_value = {
            "status": "failed",
            "errors": ["Batch node failed: n1 - boom"],
            "batch_execution": {},
            "streaming_execution_ids": [],
        }

        with pytest.raises(RuntimeError, match="boom"):
            engine.run_pipeline("hybrid_pipeline")

    def test_error_message_names_the_pipeline(self):
        engine = _executor()
        engine._hybrid_executor.execute.return_value = {"status": "failed", "errors": ["boom"]}

        with pytest.raises(RuntimeError, match="hybrid_pipeline"):
            engine.run_pipeline("hybrid_pipeline")

    def test_full_outcome_stays_reachable_on_the_exception(self):
        engine = _executor()
        engine._hybrid_executor.execute.return_value = {
            "status": "failed",
            "errors": ["boom"],
            "streaming_execution_ids": ["e1"],
        }

        with pytest.raises(RuntimeError) as caught:
            engine.run_pipeline("hybrid_pipeline")

        run_result = getattr(caught.value, "run_result")
        assert run_result.failed
        assert run_result.errors == ["boom"]
        assert run_result.streaming_execution_ids == ["e1"]

    def test_failure_with_no_error_details_still_raises(self):
        engine = _executor()
        engine._hybrid_executor.execute.return_value = {"status": "failed", "errors": []}

        with pytest.raises(RuntimeError, match="hybrid pipeline failed"):
            engine.run_pipeline("hybrid_pipeline")

    def test_successful_hybrid_returns_an_ok_result(self):
        engine = _executor()
        engine._hybrid_executor.execute.return_value = {
            "status": "success",
            "errors": [],
            "streaming_execution_ids": ["e1"],
        }

        result = engine.run_pipeline("hybrid_pipeline")

        assert result.ok
        assert result.pipeline == "hybrid_pipeline"
        assert result.streaming_execution_ids == ["e1"]


class TestChainStopsOnHybridFailure:
    def test_downstream_pipelines_do_not_run_after_a_failed_hybrid_ancestor(self):
        engine = _executor()
        ran: list = []

        def fake_run_pipeline(pipeline_name, *args, **kwargs):
            ran.append(pipeline_name)
            if pipeline_name == "upstream_hybrid":
                raise RuntimeError("Hybrid pipeline 'upstream_hybrid' failed: boom")
            return None

        engine.run_pipeline = fake_run_pipeline
        engine.context.pipelines_config = {
            "upstream_hybrid": {"type": "hybrid", "nodes": ["n1"]},
            "downstream": {"type": "batch", "nodes": ["n2"], "depends_on": ["upstream_hybrid"]},
        }
        engine.context.nodes_config = {"n1": {}, "n2": {}}

        with pytest.raises(RuntimeError, match="Pipeline chain failed"):
            engine.run_pipeline_chain("downstream")

        assert ran == ["upstream_hybrid"]
        assert "downstream" not in ran
