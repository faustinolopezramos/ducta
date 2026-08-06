"""The core's exception taxonomy.

Replaces bare ValueError/RuntimeError/`raise Exception` plus the string sniffing
callers had to do to tell them apart (`type(e).__name__ == "..."`,
`error.startswith("[QualityGateBlocked]")`).
"""

from __future__ import annotations

import pytest

from ducta.core.errors import (
    ChainExecutionError,
    ConfigurationError,
    DataError,
    DuctaError,
    ExecutionError,
    MLOpsRequiredError,
    NodeExecutionError,
    NodeNotFoundError,
    NodeTimeoutError,
    PipelineExecutionError,
    PipelineNotFoundError,
    PreflightError,
    SanityCheckFailedError,
)


class TestHierarchy:
    def test_everything_is_a_ducta_error(self):
        for cls in (ConfigurationError, ExecutionError, DataError):
            assert issubclass(cls, DuctaError)

    def test_catching_ducta_error_catches_them_all(self):
        for error in (
            PipelineNotFoundError("p"),
            NodeExecutionError("n"),
            SanityCheckFailedError("n", 1),
        ):
            with pytest.raises(DuctaError):
                raise error

    def test_a_genuine_bug_is_not_swallowed_by_except_ducta_error(self):
        # A TypeError from a mistake inside ducta must still propagate.
        with pytest.raises(TypeError):
            try:
                raise TypeError("real bug")
            except DuctaError:  # pragma: no cover - must not match
                pytest.fail("DuctaError should not catch a TypeError")


class TestBackwardCompatibleBases:
    def test_configuration_errors_are_still_value_errors(self):
        # Existing `except ValueError` call sites must keep working.
        with pytest.raises(ValueError):
            raise PipelineNotFoundError("p")

    def test_execution_errors_are_still_runtime_errors(self):
        with pytest.raises(RuntimeError):
            raise PipelineExecutionError("p")

    def test_data_errors_are_still_runtime_errors(self):
        with pytest.raises(RuntimeError):
            raise SanityCheckFailedError("n", 2)


class TestStatusMapping:
    def test_config_errors_map_to_a_client_error(self):
        assert ConfigurationError("x").http_status == 400
        assert ConfigurationError("x").exit_code == 2

    def test_not_found_errors_map_to_404(self):
        assert PipelineNotFoundError("p").http_status == 404
        assert NodeNotFoundError("n").http_status == 404

    def test_execution_errors_map_to_a_server_error(self):
        assert ExecutionError("x").http_status == 500
        assert ExecutionError("x").exit_code == 4

    def test_data_errors_map_to_unprocessable(self):
        assert DataError("x").http_status == 422

    def test_only_a_timeout_is_marked_retryable(self):
        assert NodeTimeoutError("n", 30).retryable is True
        assert NodeExecutionError("n").retryable is False
        assert ConfigurationError("x").retryable is False


class TestStructuredContext:
    def test_node_errors_carry_the_node_and_phase(self):
        error = NodeExecutionError("extract", cause=ValueError("boom"), phase="load_inputs")

        assert error.node == "extract"
        assert error.phase == "load_inputs"
        assert error.to_dict()["node"] == "extract"
        assert error.to_dict()["phase"] == "load_inputs"

    def test_the_original_cause_is_chained(self):
        original = ValueError("column not found")
        error = NodeExecutionError("extract", cause=original)

        assert error.cause is original
        assert error.__cause__ is original

    def test_to_dict_is_json_serializable(self):
        import json

        payload = json.dumps(NodeTimeoutError("n", 30.0).to_dict())

        assert '"error": "NodeTimeoutError"' in payload
        assert '"node": "n"' in payload

    def test_none_context_values_are_dropped(self):
        assert "cause_type" not in NodeExecutionError("n").to_dict()


class TestMessages:
    def test_pipeline_not_found_lists_the_alternatives(self):
        message = str(PipelineNotFoundError("typo", ["sales", "raw"]))
        assert "typo" in message
        assert "raw, sales" in message

    def test_node_not_found_truncates_a_long_listing(self):
        message = str(NodeNotFoundError("x", [f"n{i}" for i in range(25)]))
        assert "total: 25 nodes" in message

    def test_preflight_lists_every_error_and_the_bypass(self):
        error = PreflightError("sales", ["missing module", "bad output key"])

        assert "2 error(s)" in str(error)
        assert "missing module" in str(error)
        assert "preflight_enabled=false" in str(error)
        assert error.context["errors"] == ["missing module", "bad output key"]

    def test_chain_error_names_what_was_cancelled(self):
        error = ChainExecutionError("clean", step=2, total=4, cancelled=["report", "publish"])

        assert "clean" in str(error)
        assert "step 2/4" in str(error)
        assert "report" in str(error)
        assert error.cancelled == ["report", "publish"]

    def test_timeout_names_the_node_and_the_budget(self):
        assert "30s" in str(NodeTimeoutError("slow", 30.0))

    def test_mlops_required_explains_the_flag(self):
        assert "mlops_required=true" in str(MLOpsRequiredError("no tracker"))

    def test_sanity_failure_reports_the_count(self):
        error = SanityCheckFailedError("extract", 3)
        assert "extract" in str(error)
        assert "3 error(s)" in str(error)
        assert error.errors_count == 3
