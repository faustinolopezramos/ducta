"""`ConfigManager`: which project a CLI command works on.

The project is the nearest directory holding a format-2 ``ducta.yaml``, found
from ``--base-path`` (default: the current directory) upwards. A command run
with ``--base-path`` from an unrelated launch directory is normal usage, and
must run inside that project, not the launch directory. A format-1 project is
refused with the command that converts it.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ducta.console.config import ConfigManager
from ducta.console.core import ConfigurationError


def _project(root: Path) -> Path:
    (root / "pipelines").mkdir(parents=True)
    (root / "ducta.yaml").write_text(
        "version: 2\nproject: demo\npaths: {input: data, output: data}\n"
    )
    return root


@pytest.fixture
def restore_cwd():
    before = os.getcwd()
    yield
    os.chdir(before)


class TestFindingTheProject:
    def test_base_path_is_the_project(self, tmp_path):
        project = _project(tmp_path / "project")
        assert ConfigManager(str(project)).project_root == project.resolve()

    def test_a_subdirectory_finds_the_enclosing_project(self, tmp_path):
        project = _project(tmp_path / "project")
        nested = project / "pipelines" / "code"
        nested.mkdir(parents=True)
        assert ConfigManager(str(nested)).project_root == project.resolve()

    def test_a_manifest_under_config_is_found(self, tmp_path):
        wrapper = tmp_path / "wrapper"
        _project(wrapper / "config")
        assert ConfigManager(str(wrapper)).project_root == (wrapper / "config").resolve()

    def test_no_project_is_an_error_that_names_the_directory(self, tmp_path):
        with pytest.raises(ConfigurationError, match="No Ducta project found"):
            ConfigManager(str(tmp_path))

    def test_no_project_is_accepted_when_not_required(self, tmp_path):
        mgr = ConfigManager(str(tmp_path), require_config=False)
        assert mgr.project_root is None
        assert mgr.get_config_directory() == tmp_path

    @pytest.mark.parametrize(
        "marker", ["environment.yaml", "settings.json", "config/global_config.yaml"]
    )
    def test_a_format_1_project_points_at_migrate(self, tmp_path, marker):
        (tmp_path / marker).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / marker).write_text("{}\n")
        with pytest.raises(ConfigurationError, match="ducta config migrate --path"):
            ConfigManager(str(tmp_path))

    def test_a_format_1_manifest_named_ducta_yaml_points_at_migrate(self, tmp_path):
        (tmp_path / "ducta.yaml").write_text("project: {type: layered}\nlayers: {}\n")
        with pytest.raises(ConfigurationError, match="configuration format 1"):
            ConfigManager(str(tmp_path))


class TestWorkingDirectory:
    def test_runs_in_the_project_even_from_an_unrelated_launch_directory(
        self, tmp_path, restore_cwd
    ):
        launch = tmp_path / "launch"
        launch.mkdir()
        project = _project(tmp_path / "project")
        os.chdir(launch)

        mgr = ConfigManager(str(project))
        mgr.change_to_config_directory()
        assert Path.cwd() == project.resolve()

        mgr.restore_original_directory()
        assert Path.cwd() == launch.resolve()
