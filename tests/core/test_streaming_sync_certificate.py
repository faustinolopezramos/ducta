"""Regression test: a sync-mode streaming pipeline must emit a Run Certificate.

Before the fix, `run_pipeline` returned early for *any* execution_mode when
pipeline_type == STREAMING, reasoning that streaming runs "return before
completion" — true for async mode, but StreamingExecutor.execute(...,
execution_mode="sync") actually blocks until the stream stops and shuts
itself down before returning, i.e. it IS a terminating run like batch/ml/hybrid.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from ducta.core.executors.facade import PipelineExecutor
from ducta.core.results import RunStatus
from ducta.core.settings import CoreSettings
from ducta.stream.constants import PipelineType


def _executor(pipeline_type: str, execution_id: str = "exec-1") -> PipelineExecutor:
    executor = PipelineExecutor.__new__(PipelineExecutor)
    executor.context = MagicMock()
    executor.context.global_config = {"preflight_enabled": False}
    # __new__ bypasses __init__, so resolve the settings the executor now
    # expects to have been resolved once at construction time.
    executor.settings = CoreSettings.from_context(executor.context)

    fake_batch = MagicMock()
    fake_batch._get_pipeline_config.return_value = {"type": pipeline_type}
    executor._batch_executor = fake_batch

    fake_streaming = MagicMock()
    fake_streaming.execute.return_value = execution_id
    executor._streaming_executor = fake_streaming

    # `_emit_run_certificate` returns (path, reason_not_written); the caller
    # unpacks it, so a bare MagicMock would fail to iterate.
    executor._emit_run_certificate = MagicMock(return_value=("cert.json", None))
    executor._record_chain_state = MagicMock()
    return executor


class TestStreamingCertificateEmission:
    def test_sync_mode_emits_a_certificate(self):
        executor = _executor(PipelineType.STREAMING.value)

        result = executor.run_pipeline("stream1", execution_mode="sync")

        assert result.streaming_execution_ids == ["exec-1"]
        assert result.ok
        executor._emit_run_certificate.assert_called_once()
        call_kwargs = executor._emit_run_certificate.call_args.kwargs
        assert call_kwargs["status"] == "success"

    def test_async_mode_returns_early_without_a_certificate(self):
        executor = _executor(PipelineType.STREAMING.value)

        result = executor.run_pipeline("stream1", execution_mode="async")

        # Still running, so not a terminal outcome — and therefore not ok.
        assert result.streaming_execution_ids == ["exec-1"]
        assert result.status is RunStatus.RUNNING
        assert not result.ok
        executor._emit_run_certificate.assert_not_called()

    def test_sync_mode_failure_is_reflected_in_certificate_status(self):
        executor = _executor(PipelineType.STREAMING.value)
        executor._streaming_executor.execute.side_effect = RuntimeError("stream crashed")

        try:
            executor.run_pipeline("stream1", execution_mode="sync")
        except RuntimeError:
            pass

        executor._emit_run_certificate.assert_called_once()
        call_kwargs = executor._emit_run_certificate.call_args.kwargs
        assert call_kwargs["status"] == "failed"
        assert "stream crashed" in call_kwargs["error"]
