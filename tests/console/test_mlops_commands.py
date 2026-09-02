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
        global_settings={},
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

    def test_env_var_used_when_no_context_and_no_global_settings(self, monkeypatch):
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


class _RaisingRegistry:
    """Stand-in for ModelRegistry whose promote_model always raises `exc`."""

    def __init__(self, exc):
        self._exc = exc

    def promote_model(self, *args, **kwargs):
        raise self._exc
