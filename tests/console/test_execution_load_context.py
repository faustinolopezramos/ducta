"""`console.execution.load_context`: the Context of the project containing a path.

It accepts the project directory, any directory inside it, or a file in it
(``--config ducta.yaml``), and always goes through the format-2 validator —
there is no path that builds a Context from unvalidated configuration.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ducta.console.core import ConfigurationError
from ducta.console.execution import load_context


def _project(root: Path) -> Path:
    (root / "pipelines").mkdir(parents=True)
    (root / "ducta.yaml").write_text(
        "version: 2\nproject: demo\npaths: {input: data, output: data}\n"
    )
    return root


@pytest.fixture
def loader():
    with patch("ducta.console.execution.load_project_v2") as fake:
        fake.return_value = MagicMock()
        yield fake


class TestLoadContext:
    def test_a_file_in_the_project_resolves_to_its_root(self, tmp_path, loader):
        project = _project(tmp_path / "p")
        load_context(project / "ducta.yaml", "dev")
        loader.assert_called_once_with(project.resolve(), "dev")

    def test_a_nested_directory_resolves_to_the_enclosing_project(self, tmp_path, loader):
        project = _project(tmp_path / "p")
        load_context(project / "pipelines", "prod")
        loader.assert_called_once_with(project.resolve(), "prod")

    def test_the_environment_defaults_to_base(self, tmp_path, loader):
        project = _project(tmp_path / "p")
        load_context(project)
        loader.assert_called_once_with(project.resolve(), "base")

    def test_a_format_1_project_is_refused_with_the_migrate_command(self, tmp_path, loader):
        (tmp_path / "environment.yaml").write_text("env_config: {}\n")
        with pytest.raises(ConfigurationError, match="ducta config migrate"):
            load_context(tmp_path)
        loader.assert_not_called()

    def test_an_invalid_project_surfaces_the_validation_error(self, tmp_path):
        project = _project(tmp_path / "p")
        (project / "pipelines" / "etl.yaml").write_text("nodes:\n  a: {run: m:f, typo: 1}\n")
        with pytest.raises(ConfigurationError, match="etl.yaml"):
            load_context(project, "dev")
