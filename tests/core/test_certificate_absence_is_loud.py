"""A missing Run Certificate must never be silent.

Emission used to swallow every failure into `logger.debug` and return None,
which made "the certificate could not be written" indistinguishable from "this
run produced no evidence because it never happened" — the easiest failure to
induce in the one artifact the trust story rests on. These tests pin the three
distinguishable outcomes and the opt-in escalation.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ducta.core.executors.facade import PipelineExecutor
from ducta.core.results import PipelineRunResult, RunStatus
from ducta.core.settings import CoreSettings
from ducta.stream.constants import PipelineType


def _executor(global_config: dict) -> PipelineExecutor:
    executor = PipelineExecutor.__new__(PipelineExecutor)
    executor.context = MagicMock()
    executor.context.global_config = {"preflight_enabled": False, **global_config}
    executor.settings = CoreSettings.from_context(executor.context)

    fake_batch = MagicMock()
    fake_batch._get_pipeline_config.return_value = {
        "type": PipelineType.BATCH.value,
        # These tests are about certificate bookkeeping, not date validation.
        "requires_dates": False,
    }
    executor._batch_executor = fake_batch
    executor._streaming_executor = MagicMock()
    executor._record_chain_state = MagicMock()
    executor._collect_batch_outcome = MagicMock()
    return executor


class TestSettings:
    def test_requirement_is_off_by_default(self):
        assert (
            CoreSettings.from_context(MagicMock(global_config={})).require_run_certificate is False
        )

    def test_requirement_reads_from_global_config(self):
        ctx = MagicMock(global_config={"evidence_level": "required"})
        assert CoreSettings.from_context(ctx).require_run_certificate is True


class TestEmissionReportsWhyItWroteNothing:
    def test_disabled_says_so_rather_than_returning_a_bare_none(self):
        executor = _executor({"evidence_level": "off"})

        path, reason = executor._emit_run_certificate(
            pipeline_name="p",
            run_id="r1",
            started_at=None,
            ended_at=None,
            status="success",
            error=None,
        )

        assert path is None
        assert "disabled by configuration" in reason

    def test_a_failed_emission_reports_the_cause(self):
        executor = _executor({})

        with patch(
            "ducta.core.certificate.build_certificate", side_effect=RuntimeError("disk gone")
        ):
            path, reason = executor._emit_run_certificate(
                pipeline_name="p",
                run_id="r1",
                started_at=None,
                ended_at=None,
                status="success",
                error=None,
            )

        assert path is None
        assert "disk gone" in reason


class TestEscalation:
    def test_a_successful_run_fails_when_a_required_certificate_is_missing(self):
        executor = _executor({"evidence_level": "required"})
        executor._emit_run_certificate = MagicMock(return_value=(None, "disk gone"))

        with pytest.raises(Exception) as excinfo:
            executor.run_pipeline("p")

        assert "certificate" in str(excinfo.value).lower()

    def test_a_successful_run_is_untouched_when_the_certificate_is_written(self):
        executor = _executor({"evidence_level": "required"})
        executor._emit_run_certificate = MagicMock(return_value=("/tmp/cert.json", None))

        result = executor.run_pipeline("p")

        assert result.ok
        assert result.certificate_path == "/tmp/cert.json"
        assert result.certificate_error is None

    def test_a_missing_certificate_does_not_fail_the_run_by_default(self):
        executor = _executor({})
        executor._emit_run_certificate = MagicMock(return_value=(None, "disk gone"))

        result = executor.run_pipeline("p")

        assert result.ok, "the default must stay non-breaking on upgrade"
        assert result.certificate_error == "disk gone"

    def test_the_real_error_survives_when_the_run_itself_failed(self):
        """The escalation lives in a `finally`; it must not replace the error
        the user actually needs to see."""
        executor = _executor({"evidence_level": "required"})
        executor._emit_run_certificate = MagicMock(return_value=(None, "disk gone"))
        executor._batch_executor.execute.side_effect = ValueError("the real failure")

        with pytest.raises(ValueError, match="the real failure"):
            executor.run_pipeline("p")


class TestStreamingSaysWhyItHasNoCertificate:
    def test_async_streaming_explains_the_absence(self):
        executor = _executor({})
        executor._batch_executor._get_pipeline_config.return_value = {
            "type": PipelineType.STREAMING.value,
            "requires_dates": False,
        }
        executor._streaming_executor.execute.return_value = "exec-1"

        result = executor.run_pipeline("p", execution_mode="async")

        assert result.status is RunStatus.RUNNING
        assert result.certificate_path is None
        assert "streaming" in result.certificate_error


class TestResultCarriesTheReason:
    def test_to_dict_exposes_it(self):
        result = PipelineRunResult(pipeline="p", certificate_error="disabled")
        assert result.to_dict()["certificate_error"] == "disabled"
