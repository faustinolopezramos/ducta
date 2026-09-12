"""Regression tests for the workspace file browser.

`list_directory` called `posix_relative(self.root, item)` — the helper's signature
is `(path, base)`, so this computed `root.relative_to(entry)`. A directory entry is
never a parent of the root, so it raised `ValueError` for *every* non-empty
directory, which the route turned into a 404. The UI's file browser could
therefore never list anything, and nothing caught it: no Python test covered
`list_directory`, and the UI tests mock the endpoint.
"""

from __future__ import annotations

import pytest

from ducta.api.workspace.manager import WorkspaceManager


@pytest.fixture
def workspace(tmp_path):
    """A directory shaped like a Ducta project, with nesting and a skipped dir."""
    (tmp_path / "config" / "dev").mkdir(parents=True)
    (tmp_path / "pipelines").mkdir()
    (tmp_path / "__pycache__").mkdir()  # in _SKIP_DIRS

    (tmp_path / "environment.yaml").write_text("project_name: demo\n")
    (tmp_path / "config" / "global_config.yaml").write_text("mode: local\n")
    (tmp_path / "config" / "dev" / "input.yaml").write_text("{}\n")
    (tmp_path / "pipelines" / "etl.py").write_text("def run():\n    pass\n")

    return WorkspaceManager(tmp_path)


class TestListDirectory:
    def test_lists_the_workspace_root(self, workspace):
        names = {e["name"] for e in workspace.list_directory("")}

        assert {"config", "pipelines", "environment.yaml"} <= names

    def test_paths_are_relative_to_the_workspace_root(self, workspace):
        by_name = {e["name"]: e for e in workspace.list_directory("")}

        assert by_name["environment.yaml"]["path"] == "environment.yaml"
        assert by_name["config"]["path"] == "config"

    def test_nested_paths_keep_their_prefix(self, workspace):
        by_name = {e["name"]: e for e in workspace.list_directory("config")}

        assert by_name["dev"]["path"] == "config/dev"
        assert by_name["global_config.yaml"]["path"] == "config/global_config.yaml"

    def test_reports_entry_types_and_sizes(self, workspace):
        by_name = {e["name"]: e for e in workspace.list_directory("pipelines")}
        entry = by_name["etl.py"]

        assert entry["type"] == "file"
        assert entry["size"] > 0
        assert by_name.keys() == {"etl.py"}

    def test_directories_sort_before_files(self, workspace):
        types = [e["type"] for e in workspace.list_directory("")]

        assert types == sorted(types, key=lambda t: t != "dir")

    def test_skips_noise_directories(self, workspace):
        assert "__pycache__" not in {e["name"] for e in workspace.list_directory("")}

    def test_empty_directory_returns_no_entries(self, workspace, tmp_path):
        (tmp_path / "empty").mkdir()

        assert workspace.list_directory("empty") == []

    def test_rejects_a_path_outside_the_workspace(self, workspace):
        with pytest.raises(ValueError):
            workspace.list_directory("../..")

    def test_rejects_a_file_path(self, workspace):
        with pytest.raises(ValueError, match="not a directory"):
            workspace.list_directory("environment.yaml")
