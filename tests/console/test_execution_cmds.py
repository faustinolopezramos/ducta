"""Regression: a `skip_downstream` quality-gate block used to report CLI exit 0.

`ExecutionCommands._execute_pipeline` only checked `_skipped_atomic_node`
(missing-dependency skips) after `run_pipeline_chain` returned — a gate block
under the default `skip_downstream` behavior lets that call return normally
(no exception), so the CLI reported a clean success even though a node was
blocked and its descendants skipped.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from ducta.console.commands.execution_cmds import ExecutionCommands
from ducta.console.core import CLIConfig, ExitCode
from ducta.core.results import PipelineRunResult, RunStatus


class TestReuseUpstreamRerunAllConflict:
    """Regression: --reuse-upstream/--rerun-all are directly contradictory
    ("reuse what's materialized" vs "force everything to re-run") but both
    were silently threaded through with no validation — whichever won
    downstream did so with no indication the user's own flags disagreed."""

    def test_both_flags_set_is_rejected(self):
        cmd = ExecutionCommands()
        parsed_args = SimpleNamespace(reuse_upstream=True, rerun_all=True)

        result = cmd.handle_start(parsed_args)

        assert result == ExitCode.VALIDATION_ERROR.value

    def test_only_reuse_upstream_is_fine(self, monkeypatch):
        cmd = ExecutionCommands()
        parsed_args = SimpleNamespace(reuse_upstream=True, rerun_all=False)
        monkeypatch.setattr(
            "ducta.setting.detect_and_prepare_layered_execution",
            lambda _: (False, None, None),
        )
        # Past the conflict check it will fail later (missing config attrs,
        # no discoverable configuration, ...) — that's fine, we only care
        # that the conflict check itself didn't short-circuit it.
        try:
            result = cmd.handle_start(parsed_args)
        except Exception:
            return
        assert result != ExitCode.VALIDATION_ERROR.value


def _cmd_with_fake_executor(exec_obj):
    cmd = ExecutionCommands()
    cmd.config = CLIConfig(env="dev", pipeline="my_pipeline", node=None)
    cmd.config_manager = MagicMock()
    cmd.config_manager.get_config_directory.return_value = "/tmp/does-not-matter"

    exec_obj.validate_pipeline.return_value = True
    exec_obj.list_pipelines.return_value = ["my_pipeline"]

    context_init = MagicMock()
    context_init.initialize.return_value = MagicMock()

    import ducta.core

    original = ducta.core.PipelineExecutor
    ducta.core.PipelineExecutor = MagicMock(return_value=exec_obj)
    try:
        return cmd._execute_pipeline(context_init)
    finally:
        ducta.core.PipelineExecutor = original


def _executor_returning(run_result: PipelineRunResult):
    """An executor whose chain run produces *run_result*.

    Everything the CLI reports now comes off the typed result, so the test no
    longer has to model which sub-executor a pipeline type happened to use, nor
    stub two levels of private attributes.
    """
    exec_obj = MagicMock()
    exec_obj.run_pipeline_chain.return_value = run_result
    return exec_obj


class TestGateBlockedReportsNonZeroExit:
    def test_gate_blocked_node_is_not_reported_as_success(self):
        exec_obj = _executor_returning(
            PipelineRunResult(
                pipeline="my_pipeline",
                status=RunStatus.GATE_BLOCKED,
                gate_blocked={
                    "risky_node": {
                        "status": "gate_blocked",
                        "error": "score 0.4 below threshold 0.8",
                    }
                },
            )
        )

        result = _cmd_with_fake_executor(exec_obj)

        assert result == ExitCode.EXECUTION_ERROR.value

    def test_hybrid_gate_block_is_not_reported_as_success(self):
        # A hybrid pipeline runs its batch phase through HybridExecutor's own
        # node_executor. The result carries gate blocks from whichever executor
        # ran, so the CLI no longer has to know which one that was.
        exec_obj = _executor_returning(
            PipelineRunResult(
                pipeline="my_pipeline",
                status=RunStatus.GATE_BLOCKED,
                gate_blocked={"hybrid_node": {"status": "gate_blocked", "error": "freshness gate"}},
            )
        )

        result = _cmd_with_fake_executor(exec_obj)

        assert result == ExitCode.EXECUTION_ERROR.value

    def test_clean_run_still_reports_success(self):
        exec_obj = _executor_returning(PipelineRunResult(pipeline="my_pipeline"))

        result = _cmd_with_fake_executor(exec_obj)

        assert result == ExitCode.SUCCESS.value

    def test_streaming_run_reports_success(self):
        exec_obj = _executor_returning(
            PipelineRunResult(
                pipeline="my_pipeline",
                status=RunStatus.RUNNING,
                streaming_execution_ids=["exec-1"],
            )
        )

        result = _cmd_with_fake_executor(exec_obj)

        assert result == ExitCode.SUCCESS.value

    def test_missing_deps_skip_still_takes_priority_and_reports_success(self):
        # Unchanged existing behavior: an atomic --node skip (missing deps)
        # is reported as success.
        exec_obj = _executor_returning(
            PipelineRunResult(
                pipeline="my_pipeline",
                status=RunStatus.SKIPPED,
                skipped={"n1": "missing upstream input"},
            )
        )

        result = _cmd_with_fake_executor(exec_obj)

        assert result == ExitCode.SUCCESS.value

    def test_reused_upstream_pipelines_are_reported(self):
        exec_obj = _executor_returning(
            PipelineRunResult(pipeline="my_pipeline", reused_pipelines=["raw", "clean"])
        )

        result = _cmd_with_fake_executor(exec_obj)

        assert result == ExitCode.SUCCESS.value
