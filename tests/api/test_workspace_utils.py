"""Regression tests for `find_config_files`'s path confinement.

`find_config_files` resolved `base_path` and every per-file path declared in a
workspace's own `environment.yaml` with plain `(base / rel_path).resolve()`.
`environment.yaml` is content a cloned repo controls (see
`api/workspace/manager.py::load_context`), and pathlib's `Path.__truediv__`
silently discards the left operand when the right one is absolute — so
`global_settings_path: "/etc/passwd"` (or a `base_path` of `/etc`) escaped the
workspace with no `..` required.
"""

from __future__ import annotations

import yaml

from ducta.api.workspace.utils import find_config_files


def _write_environment_yaml(workspace_root, env_config, base_path=None):
    payload = {"env_config": env_config}
    if base_path is not None:
        payload["base_path"] = base_path
    (workspace_root / "environment.yaml").write_text(yaml.safe_dump(payload))


class TestFindConfigFilesRejectsEscapingRelPath:
    def test_absolute_path_in_env_config_is_rejected(self, tmp_path):
        _write_environment_yaml(
            tmp_path,
            {"base": {"global_settings_path": "/etc/passwd"}},
        )
        try:
            find_config_files(tmp_path, "base")
        except ValueError as e:
            assert "traversal" in str(e).lower() or "outside" in str(e).lower()
        else:
            raise AssertionError("expected ValueError for absolute path escape")

    def test_dotdot_in_env_config_is_rejected(self, tmp_path):
        _write_environment_yaml(
            tmp_path,
            {"base": {"global_settings_path": "../../../etc/passwd"}},
        )
        try:
            find_config_files(tmp_path, "base")
        except ValueError:
            pass
        else:
            raise AssertionError("expected ValueError for '..' traversal")


class TestFindConfigFilesRejectsEscapingBasePath:
    def test_absolute_base_path_is_rejected(self, tmp_path):
        _write_environment_yaml(
            tmp_path,
            {"base": {"global_settings_path": "global_settings.yaml"}},
            base_path="/etc",
        )
        try:
            find_config_files(tmp_path, "base")
        except ValueError:
            pass
        else:
            raise AssertionError("expected ValueError for absolute base_path escape")


class TestFindConfigFilesAllowsLegitimatePaths:
    def test_ordinary_relative_paths_resolve_within_workspace(self, tmp_path):
        (tmp_path / "config").mkdir()
        (tmp_path / "config" / "global_settings.yaml").write_text("mode: local\n")
        _write_environment_yaml(
            tmp_path,
            {"base": {"global_settings_path": "config/global_settings.yaml"}},
        )
        result = find_config_files(tmp_path, "base")
        assert result["global_settings"] == (tmp_path / "config" / "global_settings.yaml").resolve()

    def test_default_base_path_dot_resolves_to_workspace_root(self, tmp_path):
        (tmp_path / "global_settings.yaml").write_text("mode: local\n")
        _write_environment_yaml(
            tmp_path,
            {"base": {"global_settings_path": "global_settings.yaml"}},
            base_path=".",
        )
        result = find_config_files(tmp_path, "base")
        assert result["global_settings"] == (tmp_path / "global_settings.yaml").resolve()
