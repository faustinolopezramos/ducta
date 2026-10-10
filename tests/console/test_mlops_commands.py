"""Unit tests for ducta.console.mlops_commands.

Two bugs this pins down:

1. ``_resolve_storage_path`` used to import
   ``ducta.setting.context_loader.discover_context`` — a function that does
   not exist anywhere in this codebase — so "auto-discovery" always raised
   ImportError, was silently swallowed, and every invocation without
   ``--storage-path`` fell back to ``./mlops_data`` regardless of where a
   pipeline actually wrote its tracking data.
2. ``model_promote`` collapsed every failure (bad model name, a policy
   rejection, a genuine crash) into exit code 1.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import pytest

from ducta.console import mlops_commands
from ducta.console.core import ExitCode
from ducta.mlrun.exceptions import ModelNotFoundError, PromotionGateError


def _fake_context(output_path, env="dev"):
    return SimpleNamespace(
        global_config={},
        output_path=output_path,
        env=env,
        execution_mode="local",
    )


def _patch_context_discovery(ctx):
    """Patch ConfigManager/ContextInitializer so _discover_context(env)
    returns `ctx` without touching the real filesystem/cwd."""

    class FakeConfigManager:
        def __init__(self, base_path=None, require_config=False):
            pass

        def change_to_config_directory(self):
            pass

    class FakeContextInitializer:
        def __init__(self, config_manager):
            pass

        def initialize(self, env):
            return ctx

    return mock.patch.multiple(
        "ducta.console.config",
        ConfigManager=FakeConfigManager,
    ), mock.patch.multiple(
        "ducta.console.execution",
        ContextInitializer=FakeContextInitializer,
    )


class TestResolveStoragePathPrecedence:
    def test_explicit_storage_path_always_wins(self, tmp_path):
        got = mlops_commands._resolve_storage_path(str(tmp_path / "explicit"), env="dev")
        assert got == str(tmp_path / "explicit")

    def test_env_resolves_via_real_context_4_tier_fallback(self, tmp_path):
        ctx = _fake_context(str(tmp_path / "output"))
        p1, p2 = _patch_context_discovery(ctx)
        with p1, p2:
            got = mlops_commands._resolve_storage_path(None, env="dev", pipeline_name="sales.train")
        assert got == str(tmp_path / "output" / "dev" / "sales" / "train")

    def test_no_env_and_no_project_falls_back_to_default(self, tmp_path, monkeypatch):
        monkeypatch.delenv("Ducta_MLOPS_PATH", raising=False)
        monkeypatch.delenv("DUCTA_MLOPS_PATH", raising=False)
        got = mlops_commands._resolve_storage_path(None, env=None)
        assert got == "./mlops_data"

    def test_context_discovery_failure_falls_back_to_default(self, monkeypatch):
        monkeypatch.delenv("Ducta_MLOPS_PATH", raising=False)
        monkeypatch.delenv("DUCTA_MLOPS_PATH", raising=False)
        # No patching of ConfigManager/ContextInitializer: with no real ducta
        # project at cwd, _discover_context must swallow the failure and
        # return None rather than raising out of _resolve_storage_path.
        got = mlops_commands._resolve_storage_path(None, env="dev")
        assert got == "./mlops_data"

    def test_env_var_used_when_no_context_and_no_global_config(self, monkeypatch):
        monkeypatch.setenv("Ducta_MLOPS_PATH", "/from/env/var")
        got = mlops_commands._resolve_storage_path(None, env=None)
        assert got == "/from/env/var"


class TestModelPromoteExitCodes:
    def test_model_not_found_maps_to_validation_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            mlops_commands,
            "_build_registry",
            lambda storage: _RaisingRegistry(ModelNotFoundError("x")),
        )
        rc = mlops_commands.model_promote(
            "missing-model", "1", "production", str(tmp_path), env=None
        )
        assert rc == ExitCode.VALIDATION_ERROR.value

    def test_promotion_gate_error_maps_to_execution_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            mlops_commands,
            "_build_registry",
            lambda storage: _RaisingRegistry(PromotionGateError("m", 1, "not good enough")),
        )
        rc = mlops_commands.model_promote("m", "1", "production", str(tmp_path), env=None)
        assert rc == ExitCode.EXECUTION_ERROR.value

    def test_unexpected_error_maps_to_general_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            mlops_commands,
            "_build_registry",
            lambda storage: _RaisingRegistry(RuntimeError("boom")),
        )
        rc = mlops_commands.model_promote("m", "1", "production", str(tmp_path), env=None)
        assert rc == ExitCode.GENERAL_ERROR.value

    def test_invalid_stage_maps_to_validation_error(self, tmp_path):
        rc = mlops_commands.model_promote("m", "1", "not-a-stage", str(tmp_path), env=None)
        assert rc == ExitCode.VALIDATION_ERROR.value

    @pytest.mark.parametrize("version", ["1.2.0", "latest", "", "v", "3.0"])
    def test_a_semantic_version_is_a_validation_error_not_a_crash(
        self, tmp_path, monkeypatch, version
    ):
        # Registry versions are whole numbers; "1.2.0" used to die in int() and exit 1.
        monkeypatch.setattr(
            mlops_commands,
            "_build_registry",
            lambda storage: pytest.fail("the registry must not be touched"),
        )
        rc = mlops_commands.model_promote("m", version, "production", str(tmp_path), env=None)
        assert rc == ExitCode.VALIDATION_ERROR.value

    @pytest.mark.parametrize("version,expected", [("3", 3), ("v3", 3), (" V12 ", 12)])
    def test_whole_numbers_and_v_prefix_are_accepted(
        self, tmp_path, monkeypatch, version, expected
    ):
        seen = {}

        class _Registry:
            def promote_model(self, name, number, stage, **kwargs):
                seen["number"] = number

        monkeypatch.setattr(mlops_commands, "_build_registry", lambda storage: _Registry())
        rc = mlops_commands.model_promote("m", version, "staging", str(tmp_path), env=None)
        assert rc == 0 and seen["number"] == expected


class _RaisingRegistry:
    """Stand-in for ModelRegistry whose promote_model always raises `exc`."""

    def __init__(self, exc):
        self._exc = exc

    def promote_model(self, *args, **kwargs):
        raise self._exc


class TestExperimentRunsShowCompare:
    """Real tracker on a temp directory: `list` showed experiments but nothing could be
    done with a run afterwards, so two experiments could not be compared from the CLI."""

    @pytest.fixture
    def tracked(self, tmp_path):
        from ducta.mlrun.config import DEFAULT_TRACKING_PATH
        from ducta.mlrun.experiment_tracking import ExperimentTracker
        from ducta.mlrun.storage import LocalStorageBackend

        tracker = ExperimentTracker(
            storage=LocalStorageBackend(base_path=str(tmp_path)),
            tracking_path=DEFAULT_TRACKING_PATH,
        )
        exp = tracker.create_experiment("churn")
        exp_id = exp.experiment_id if hasattr(exp, "experiment_id") else exp
        run_ids = []
        for name, depth, auc in (("shallow", 3, 0.71), ("deep", 8, 0.78)):
            run = tracker.start_run(exp_id, name=name, parameters={"max_depth": depth})
            run_id = run.run_id if hasattr(run, "run_id") else run
            tracker.log_metric(run_id, "auc", auc)
            tracker.end_run(run_id)
            run_ids.append(run_id)
        return SimpleNamespace(path=str(tmp_path), exp_id=exp_id, run_ids=run_ids)

    def test_runs_lists_every_run_of_the_experiment(self, tracked, capsys):
        rc = mlops_commands.experiment_runs(tracked.exp_id, tracked.path)

        out = capsys.readouterr().out
        assert rc == 0
        assert all(run_id in out for run_id in tracked.run_ids)

    def test_runs_json_is_machine_readable(self, tracked, capsys):
        import json

        rc = mlops_commands.experiment_runs(tracked.exp_id, tracked.path, output_format="json")

        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert {r["run_id"] for r in data} == set(tracked.run_ids)

    def test_runs_of_an_unknown_experiment_is_empty_not_an_error(self, tracked, capsys):
        rc = mlops_commands.experiment_runs("nope", tracked.path)

        assert rc == 0
        assert "No runs found" in capsys.readouterr().out

    def test_show_prints_parameters_and_latest_metrics(self, tracked, capsys):
        rc = mlops_commands.experiment_show(tracked.run_ids[1], tracked.path)

        out = capsys.readouterr().out
        assert rc == 0
        assert "max_depth" in out and "8" in out
        assert "auc" in out and "0.78" in out

    def test_show_accepts_a_unique_prefix(self, tracked, capsys):
        rc = mlops_commands.experiment_show(tracked.run_ids[0][:12], tracked.path)

        assert rc == 0
        assert tracked.run_ids[0] in capsys.readouterr().out

    def test_show_unknown_run_is_a_validation_error_that_names_the_path(self, tracked, caplog):
        rc = mlops_commands.experiment_show("no-such-run", tracked.path)

        assert rc == ExitCode.VALIDATION_ERROR.value

    def test_compare_puts_both_runs_side_by_side(self, tracked, capsys):
        rc = mlops_commands.experiment_compare(tracked.run_ids, tracked.path)

        out = capsys.readouterr().out
        assert rc == 0
        assert "param_max_depth" in out and "metric_auc" in out
        assert "0.71" in out and "0.78" in out

    def test_compare_json(self, tracked, capsys):
        import json

        rc = mlops_commands.experiment_compare(tracked.run_ids, tracked.path, output_format="json")

        rows = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert sorted(r["metric_auc"] for r in rows) == [0.71, 0.78]

    def test_compare_needs_two_runs(self, tracked):
        rc = mlops_commands.experiment_compare(tracked.run_ids[:1], tracked.path)

        assert rc == ExitCode.VALIDATION_ERROR.value

    def test_compare_with_an_unknown_run_is_a_validation_error(self, tracked):
        rc = mlops_commands.experiment_compare([tracked.run_ids[0], "ghost"], tracked.path)

        assert rc == ExitCode.VALIDATION_ERROR.value


class TestExperimentCliWiring:
    """The parser and the dispatcher know the three new subcommands."""

    @pytest.mark.parametrize(
        "argv",
        [
            ["experiment", "runs", "exp1", "--status", "completed", "--output-format", "json"],
            ["experiment", "show", "abc123"],
            ["experiment", "compare", "a", "b", "--output-format", "json"],
        ],
    )
    def test_parser_accepts(self, argv):
        from ducta.console.parser import UnifiedArgumentParser

        args = UnifiedArgumentParser.create().parse_args(argv)

        assert args.experiment_command == argv[1]

    def test_dispatch_routes_compare(self, monkeypatch):
        from ducta.console.cli import UnifiedCLI
        from ducta.console.parser import UnifiedArgumentParser

        seen = {}

        def fake_compare(run_ids, storage_path, **kwargs):
            seen.update(run_ids=run_ids, storage_path=storage_path, **kwargs)
            return 0

        monkeypatch.setattr(mlops_commands, "experiment_compare", fake_compare)
        args = UnifiedArgumentParser.create().parse_args(
            ["experiment", "compare", "a", "b", "--storage-path", "/x", "--output-format", "json"]
        )

        rc = UnifiedCLI()._handle_experiment_command(args)

        assert rc == 0
        assert seen["run_ids"] == ["a", "b"] and seen["output_format"] == "json"
