"""Unit tests for the storage-path resolution helpers in
ducta.api.routes.mlops.

These endpoints used to resolve storage_path by parsing global_config.*
directly off disk — never building a real Context — so a pipeline run that
wrote its tracking data under output_path/<env>/<schema>/<pipeline> (the
default whenever global_config.mlops_path isn't set) was invisible unless
the caller passed storage_path explicitly.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from ducta.api.exceptions import ValidationError
from ducta.api.routes import mlops as mlops_routes


def _fake_context(output_path, env="dev"):
    return SimpleNamespace(
        global_config={},
        output_path=output_path,
        env=env,
        execution_mode="local",
    )


class TestResolveMlopsStoragePrecedence:
    def test_explicit_override_always_wins(self, tmp_path):
        got = mlops_routes._resolve_mlops_storage(tmp_path, "explicit/path", env="dev")
        assert got == str((tmp_path / "explicit" / "path").resolve())

    def test_explicit_override_outside_the_workspace_is_rejected(self, tmp_path):
        # The override comes straight from the request and these endpoints
        # delete runs, model versions and GC'd artifacts under it.
        with pytest.raises(ValidationError):
            mlops_routes._resolve_mlops_storage(tmp_path, "/explicit/path", env="dev")
        with pytest.raises(ValidationError):
            mlops_routes._resolve_mlops_storage(tmp_path, "../elsewhere", env="dev")

    def test_env_resolves_via_workspace_context_4_tier_fallback(self, tmp_path):
        ctx = _fake_context(str(tmp_path / "output"))

        class FakeWorkspaceManager:
            def __init__(self, source_path):
                self.root = source_path

            def load_context(self, env):
                return ctx

        with mock.patch.object(
            __import__("ducta.api.workspace.manager", fromlist=["WorkspaceManager"]),
            "WorkspaceManager",
            FakeWorkspaceManager,
        ):
            got = mlops_routes._resolve_mlops_storage(
                tmp_path, None, env="dev", pipeline_name="sales.train"
            )
        assert got == str(Path(tmp_path / "output" / "dev" / "sales" / "train"))

    def test_no_env_falls_back_to_workspace_default(self, tmp_path):
        got = mlops_routes._resolve_mlops_storage(tmp_path, None, env=None)
        assert got == str(tmp_path / "mlops_data")

    def test_workspace_context_failure_falls_back_to_default(self, tmp_path):
        # No real ducta workspace at tmp_path: WorkspaceManager(...).load_context
        # must fail internally and _resolve_mlops_storage must not raise.
        got = mlops_routes._resolve_mlops_storage(tmp_path, None, env="dev")
        assert got == str(tmp_path / "mlops_data")


class TestResolveGlobalConfigSharedWithPromotionPolicy:
    def test_prefers_context_over_flat_files(self, tmp_path):
        ctx = _fake_context(str(tmp_path / "output"))
        ctx.global_config = {"mlops": {"promotion_policy": {"metric": "f1"}}}

        class FakeWorkspaceManager:
            def __init__(self, source_path):
                self.root = source_path

            def load_context(self, env):
                return ctx

        with mock.patch.object(
            __import__("ducta.api.workspace.manager", fromlist=["WorkspaceManager"]),
            "WorkspaceManager",
            FakeWorkspaceManager,
        ):
            gs = mlops_routes._resolve_global_config(tmp_path, env="dev")
        assert gs["mlops"]["promotion_policy"]["metric"] == "f1"

    def test_no_env_and_no_files_returns_empty_dict(self, tmp_path):
        assert mlops_routes._resolve_global_config(tmp_path, env=None) == {}
