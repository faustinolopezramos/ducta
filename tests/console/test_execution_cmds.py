"""Regression: a `skip_downstream` quality-gate block used to report CLI exit 0.

`ExecutionCommands._execute_pipeline` only checked `_skipped_atomic_node`
(missing-dependency skips) after `run_pipeline_chain` returned — a gate block
under the default `skip_downstream` behavior lets that call return normally
(no exception), so the CLI reported a clean success even though a node was
blocked and its descendants skipped.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

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

    def test_missing_deps_skip_reports_a_dependency_error(self):
        # A skip used to exit 0, so no script wrapping `ducta` could tell a run
        # that did its work from one that skipped it. DEPENDENCY_ERROR names the
        # reason and stays distinct from a gate block's EXECUTION_ERROR.
        exec_obj = _executor_returning(
            PipelineRunResult(
                pipeline="my_pipeline",
                status=RunStatus.SKIPPED,
                skipped={"n1": "missing upstream input"},
            )
        )

        result = _cmd_with_fake_executor(exec_obj)

        assert result == ExitCode.DEPENDENCY_ERROR.value

    def test_a_gate_block_outranks_the_skips_it_caused(self):
        # A blocking gate cascades skips onto every descendant, so both
        # collections are populated. Only the gate names the cause; reporting
        # the consequence instead labelled a rejected-data run "missing
        # dependencies" and exited 5 rather than 4.
        exec_obj = _executor_returning(
            PipelineRunResult(
                pipeline="my_pipeline",
                status=RunStatus.GATE_BLOCKED,
                gate_blocked={"n2": {"error": "blocked"}},
                skipped={"n3": "skipped: upstream quality gate blocked at 'n2'"},
            )
        )

        assert _cmd_with_fake_executor(exec_obj) == ExitCode.EXECUTION_ERROR.value

    def test_reused_upstream_pipelines_are_reported(self):
        exec_obj = _executor_returning(
            PipelineRunResult(pipeline="my_pipeline", reused_pipelines=["raw", "clean"])
        )

        result = _cmd_with_fake_executor(exec_obj)

        assert result == ExitCode.SUCCESS.value


class TestSweepParallelCap:
    """Regression: --sweep-parallel had no ceiling and no relationship to
    available cores — requesting more workers than cores silently
    oversubscribed the machine instead of being capped with a warning."""

    def test_default_without_flag_is_unchanged(self):
        parsed_args = SimpleNamespace(sweep_parallel=None)
        assert ExecutionCommands._resolve_sweep_parallel(parsed_args) == 1

    def test_requested_within_core_count_is_unchanged(self, monkeypatch):
        monkeypatch.setattr("os.cpu_count", lambda: 8)
        parsed_args = SimpleNamespace(sweep_parallel=4)
        assert ExecutionCommands._resolve_sweep_parallel(parsed_args) == 4

    def test_requested_above_core_count_is_capped_with_warning(self, monkeypatch):
        monkeypatch.setattr("os.cpu_count", lambda: 4)
        parsed_args = SimpleNamespace(sweep_parallel=16)

        with patch("ducta.console.commands.execution_cmds.logger") as mock_logger:
            result = ExecutionCommands._resolve_sweep_parallel(parsed_args)
            mock_logger.warning.assert_called_once()

        assert result == 4

    def test_zero_or_negative_floors_at_one(self, monkeypatch):
        monkeypatch.setattr("os.cpu_count", lambda: 4)
        parsed_args = SimpleNamespace(sweep_parallel=0)
        assert ExecutionCommands._resolve_sweep_parallel(parsed_args) == 1


class TestWarnIfParallelSpark:
    def test_warns_when_context_has_spark(self):
        exec_obj = SimpleNamespace(context=SimpleNamespace(spark=MagicMock()))

        with patch("ducta.console.commands.execution_cmds.logger") as mock_logger:
            ExecutionCommands._warn_if_parallel_spark(exec_obj, 2)
            mock_logger.warning.assert_called_once()

    def test_no_warning_without_spark(self):
        exec_obj = SimpleNamespace(context=SimpleNamespace(spark=None))

        with patch("ducta.console.commands.execution_cmds.logger") as mock_logger:
            ExecutionCommands._warn_if_parallel_spark(exec_obj, 2)
            mock_logger.warning.assert_not_called()

    def test_no_warning_when_context_has_no_spark_attribute(self):
        exec_obj = SimpleNamespace(context=SimpleNamespace())

        with patch("ducta.console.commands.execution_cmds.logger") as mock_logger:
            ExecutionCommands._warn_if_parallel_spark(exec_obj, 2)
            mock_logger.warning.assert_not_called()


class TestMaxSweepSize:
    """Regression: --sweep and the API both called expand_sweep(spec) without
    max_runs=, so expand_sweep_grid truncated at its own internal default of
    50 during expansion — configuring max_sweep_size above 50 had no effect."""

    def test_parse_config_defaults_to_50(self):
        cmd = ExecutionCommands()
        parsed_args = SimpleNamespace(env="dev", pipeline="p", max_sweep_size=None)
        config = cmd._parse_config(parsed_args)
        assert config.max_sweep_size == 50

    def test_parse_config_honors_explicit_flag(self):
        cmd = ExecutionCommands()
        parsed_args = SimpleNamespace(env="dev", pipeline="p", max_sweep_size=200)
        config = cmd._parse_config(parsed_args)
        assert config.max_sweep_size == 200


class TestRunTrialsParallelSharedPrefix:
    """Trial 1 runs first, sequentially, into a shared prefix directory —
    only afterward do trials 2..N run in parallel, each given that directory
    as a read fallback (if trial 1 succeeded)."""

    def _cmd(self, tmp_path):
        cmd = ExecutionCommands()
        cmd.config = CLIConfig(env="dev", pipeline="p", sweep_parallel=2)
        exec_obj = SimpleNamespace(
            context=SimpleNamespace(
                global_settings={"output_path": str(tmp_path)}, output_path=str(tmp_path)
            )
        )
        return cmd, exec_obj

    def test_single_trial_materializes_shared_prefix_without_touching_the_pool(
        self, tmp_path, monkeypatch
    ):
        # A single-trial sweep never has a "rest" to parallelize — it must
        # return right after the sequential trial 1, never constructing a
        # ProcessPoolExecutor at all.
        cmd, exec_obj = self._cmd(tmp_path)

        calls = []

        def fake_run_trial_in_process(payload):
            calls.append(dict(payload))
            return {
                "index": payload["trial_index"],
                "params": payload["params"],
                "metrics": {"val_f1": 0.9},
                "gate_blocked": [],
                "failed": False,
                "reason": None,
            }

        monkeypatch.setattr(
            "ducta.core.sweep_worker.run_trial_in_process", fake_run_trial_in_process
        )

        def _pool_should_not_be_used(*a, **k):
            raise AssertionError("ProcessPoolExecutor must not be constructed for one trial")

        monkeypatch.setattr("concurrent.futures.ProcessPoolExecutor", _pool_should_not_be_used)

        trials = [{"index": 1, "params": {"depth": 3}, "hyperparams": {"depth": 3}}]
        outcomes = cmd._run_trials_parallel(exec_obj, trials, "search-1", workers=2)

        assert len(calls) == 1
        from ducta.core.sweep_worker import shared_prefix_path

        assert calls[0]["output_path"] == shared_prefix_path(str(tmp_path), "search-1")
        assert outcomes == [
            {
                "index": 1,
                "params": {"depth": 3},
                "metrics": {"val_f1": 0.9},
                "gate_blocked": [],
                "failed": False,
                "reason": None,
            }
        ]

    def test_failed_trial_one_disables_fallback_for_the_rest(self, tmp_path, monkeypatch):
        cmd, exec_obj = self._cmd(tmp_path)

        seen_fallback_paths = []

        def fake_build_payloads(trials, *, read_fallback_paths=None, **kwargs):
            seen_fallback_paths.append(list(read_fallback_paths or []))
            return [
                {"trial_index": t["index"], "params": t.get("params") or {}, "output_path": None}
                for t in trials
            ]

        def fake_run_trial_in_process(payload):
            if payload["trial_index"] == 1:
                return {
                    "index": 1,
                    "params": {},
                    "metrics": {},
                    "gate_blocked": [],
                    "failed": True,
                    "reason": "boom",
                }
            return {
                "index": payload["trial_index"],
                "params": {},
                "metrics": {},
                "gate_blocked": [],
                "failed": False,
                "reason": None,
            }

        monkeypatch.setattr("ducta.core.sweep_worker.build_payloads", fake_build_payloads)
        monkeypatch.setattr(
            "ducta.core.sweep_worker.run_trial_in_process", fake_run_trial_in_process
        )

        class _FakeFuture:
            def __init__(self, value):
                self._value = value

            def result(self):
                return self._value

        class _FakePool:
            def __init__(self, *a, **k):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def submit(self, fn, payload):
                return _FakeFuture(fn(payload))

        monkeypatch.setattr("concurrent.futures.ProcessPoolExecutor", _FakePool)
        monkeypatch.setattr("concurrent.futures.as_completed", lambda futures: list(futures.keys()))

        trials = [{"index": i, "params": {}, "hyperparams": {}} for i in range(1, 4)]
        outcomes = cmd._run_trials_parallel(exec_obj, trials, "search-1", workers=2)

        # Only the call for trials 2..3 goes through fake_build_payloads
        # (trial 1's payload is built via a direct single-trial call too —
        # both calls are recorded, the second must carry an empty fallback).
        assert seen_fallback_paths[-1] == []
        assert len(outcomes) == 3
        assert outcomes[0]["failed"] is True
