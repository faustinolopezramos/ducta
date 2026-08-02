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
    exec_obj.run_pipeline_chain.return_value = None
    exec_obj.reused_pipelines = None

    context_init = MagicMock()
    context_init.initialize.return_value = MagicMock()

    import ducta.core

    original = ducta.core.PipelineExecutor
    ducta.core.PipelineExecutor = MagicMock(return_value=exec_obj)
    try:
        return cmd._execute_pipeline(context_init)
    finally:
        ducta.core.PipelineExecutor = original


class TestGateBlockedReportsNonZeroExit:
    def test_gate_blocked_node_is_not_reported_as_success(self):
        exec_obj = MagicMock()
        exec_obj.batch_executor._skipped_atomic_node = None
        exec_obj.batch_executor.node_executor.gate_blocked = {
            "risky_node": {"status": "gate_blocked", "error": "score 0.4 below threshold 0.8"}
        }

        result = _cmd_with_fake_executor(exec_obj)

        assert result == ExitCode.EXECUTION_ERROR.value

    def test_clean_run_still_reports_success(self):
        exec_obj = MagicMock()
        exec_obj.batch_executor._skipped_atomic_node = None
        exec_obj.batch_executor.node_executor.gate_blocked = {}

        result = _cmd_with_fake_executor(exec_obj)

        assert result == ExitCode.SUCCESS.value

    def test_missing_deps_skip_still_takes_priority_and_reports_success(self):
        # Unchanged existing behavior: an atomic --node skip (missing deps)
        # is reported as success, same as before this fix.
        exec_obj = MagicMock()
        exec_obj.batch_executor._skipped_atomic_node = {
            "node": "n1",
            "reason": "missing upstream input",
        }
        exec_obj.batch_executor.node_executor.gate_blocked = {}

        result = _cmd_with_fake_executor(exec_obj)

        assert result == ExitCode.SUCCESS.value
