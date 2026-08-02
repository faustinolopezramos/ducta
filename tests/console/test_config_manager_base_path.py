"""Regression: `ConfigManager.change_to_config_directory` validated the
target directory against `self.original_cwd` (the CLI's launch directory)
instead of `self.base_path` (the explicit `--base-path`, defaulting to cwd
when unset). `ducta start --base-path /some/project` from an unrelated
launch directory is normal, legitimate usage — checking against
original_cwd instead of the intended project root either wrongly rejects
that valid case or fails to actually confine to the intended boundary.
"""

from __future__ import annotations

import os

import pytest

from ducta.console.config import ConfigManager
from ducta.console.core import ConfigurationError


def _bare_manager(base_path, active_config_dir, original_cwd):
    mgr = ConfigManager.__new__(ConfigManager)
    mgr.original_cwd = original_cwd
    mgr.base_path = base_path
    mgr.active_config_dir = active_config_dir
    return mgr


class TestChangeToConfigDirectoryConfinesToBasePath:
    def test_target_within_base_path_but_outside_launch_cwd_is_allowed(self, tmp_path):
        launch_cwd = tmp_path / "launch"
        launch_cwd.mkdir()
        project = tmp_path / "project"
        (project / "config").mkdir(parents=True)

        mgr = _bare_manager(
            base_path=project,
            active_config_dir=project / "config",
            original_cwd=launch_cwd,
        )
        original = os.getcwd()
        try:
            mgr.change_to_config_directory()
            assert os.getcwd() == str((project / "config").resolve())
        finally:
            os.chdir(original)

    def test_target_outside_base_path_is_rejected(self, tmp_path):
        base = tmp_path / "project"
        base.mkdir()
        outside = tmp_path / "elsewhere"
        outside.mkdir()

        mgr = _bare_manager(base_path=base, active_config_dir=outside, original_cwd=base)
        with pytest.raises(ConfigurationError):
            mgr.change_to_config_directory()
