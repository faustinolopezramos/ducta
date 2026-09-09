"""Regression: an upstream chain step that did not refresh its outputs was
treated as a success.

`run_pipeline` only raises for a *failed* run. A blocked quality gate and a
skipped node are recorded on the result and returned normally — right for one
pipeline, wrong for a chain, where "this pipeline wrote nothing" means every
pipeline after it silently reads whatever an earlier run left on disk. The
chain used to log "completed successfully" for the blocked step and exit 0.
"""

from __future__ import annotations

import pytest

from ducta.core.errors import ChainExecutionError, ChainStepNotRefreshedError
from ducta.core.executors.facade import PipelineExecutor
from ducta.core.results import PipelineRunResult, RunStatus
from ducta.core.settings import CoreSettings


def _build(settings: CoreSettings) -> PipelineExecutor:
    """A facade with just the settings the decision reads — no Spark, no config."""
    executor = object.__new__(PipelineExecutor)
    executor.settings = settings
    return executor


def _blocked() -> PipelineRunResult:
    return PipelineRunResult(
        pipeline="bronze",
        status=RunStatus.GATE_BLOCKED,
        gate_blocked={"extract": {"error": "row_count below min"}},
    )


class TestStopIsTheDefault:
    def test_a_gate_blocked_ancestor_aborts_the_chain(self):
        executor = _build(CoreSettings())

        with pytest.raises(ChainExecutionError) as excinfo:
            executor._enforce_chain_step_outcome(
                _blocked(), step=1, chain=["bronze", "gold"], pipeline="bronze"
            )

        assert isinstance(excinfo.value.__cause__, ChainStepNotRefreshedError)

    def test_the_cancelled_pipelines_are_named(self):
        executor = _build(CoreSettings())

        with pytest.raises(ChainExecutionError) as excinfo:
            executor._enforce_chain_step_outcome(
                _blocked(), step=1, chain=["bronze", "silver", "gold"], pipeline="bronze"
            )

        assert excinfo.value.cancelled == ["silver", "gold"]

    def test_the_message_names_the_blocked_node(self):
        # The CLI logs str(e) and only shows the traceback under --verbose, so
        # a cause reachable solely through __cause__ never reaches the user.
        executor = _build(CoreSettings())

        with pytest.raises(ChainExecutionError) as excinfo:
            executor._enforce_chain_step_outcome(
                _blocked(), step=1, chain=["bronze", "gold"], pipeline="bronze"
            )

        assert "extract" in str(excinfo.value)

    def test_a_skipped_ancestor_also_aborts(self):
        executor = _build(CoreSettings())
        result = PipelineRunResult(
            pipeline="bronze",
            status=RunStatus.SKIPPED,
            skipped={"extract": "missing inputs"},
        )

        with pytest.raises(ChainExecutionError):
            executor._enforce_chain_step_outcome(
                result, step=1, chain=["bronze", "gold"], pipeline="bronze"
            )

    def test_a_clean_ancestor_lets_the_chain_continue(self):
        executor = _build(CoreSettings())

        executor._enforce_chain_step_outcome(
            PipelineRunResult(pipeline="bronze"),
            step=1,
            chain=["bronze", "gold"],
            pipeline="bronze",
        )

    def test_a_still_running_stream_is_not_treated_as_a_failure(self):
        executor = _build(CoreSettings())
        result = PipelineRunResult(pipeline="bronze", status=RunStatus.RUNNING)

        executor._enforce_chain_step_outcome(
            result, step=1, chain=["bronze", "gold"], pipeline="bronze"
        )


class TestContinueIsOptIn:
    def test_continue_lets_the_chain_run_on(self):
        executor = _build(CoreSettings(chain_on_gate_blocked="continue"))

        executor._enforce_chain_step_outcome(
            _blocked(), step=1, chain=["bronze", "gold"], pipeline="bronze"
        )

    def test_an_unknown_value_fails_closed_to_stop(self):
        # Resolved through coerce_choice, so a typo cannot quietly re-enable
        # the behavior this whole check exists to remove.
        settings = CoreSettings.from_context({"chain": {"on_gate_blocked": "carry-on"}})

        assert settings.chain_on_gate_blocked == "stop"

    def test_the_configured_value_is_read(self):
        settings = CoreSettings.from_context({"chain": {"on_gate_blocked": "continue"}})

        assert settings.chain_on_gate_blocked == "continue"

    def test_the_default_is_stop(self):
        assert CoreSettings.from_context({}).chain_on_gate_blocked == "stop"
