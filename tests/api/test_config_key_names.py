"""Regression tests for the `environment.yaml` key -> config-name mapping.

`find_config_files` derived each short name by stripping suffixes:
``key.removesuffix("_path").removesuffix("_config")``. That rule only held while
the first config was called ``global_settings_path`` — a name with no ``_config``
suffix, so the second strip was a no-op on it and a clean shortening on the other
four. Renaming it to ``global_config_path`` turned the no-op into a bite,
producing ``"global"``.

Nothing consumes that name: ``WorkspaceManager._CONTEXT_KEY_MAP`` fell back to
``"global_path"`` and ``ContextLoader.load_from_paths`` rejected the context with
``Missing config paths: ['global_config_path']`` — taking every API-driven
execution, MLOps and quality route down with it, while the four other configs
resolved fine and hid the breakage.
"""

from __future__ import annotations

import pytest
import yaml

from ducta.api.workspace.utils import CONFIG_FILE_NAMES, find_config_files

_DECLARATIONS = {
    "global_config_path": "config/global_config.yaml",
    "pipelines_config_path": "config/pipelines.yaml",
    "nodes_config_path": "config/nodes.yaml",
    "input_config_path": "config/input.yaml",
    "output_config_path": "config/output.yaml",
}


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "config").mkdir()
    for rel in _DECLARATIONS.values():
        (tmp_path / rel).write_text("{}\n")
    (tmp_path / "environment.yaml").write_text(
        yaml.safe_dump({"base_path": ".", "env_config": {"base": _DECLARATIONS}})
    )
    return tmp_path


def test_every_declared_config_resolves_to_its_documented_name(workspace):
    assert set(find_config_files(workspace, "base")) == set(CONFIG_FILE_NAMES)


def test_global_config_keeps_its_config_suffix(workspace):
    """The one name whose suffix must survive — see the module docstring."""
    resolved = find_config_files(workspace, "base")
    assert "global_config" in resolved
    assert "global" not in resolved
    assert resolved["global_config"].name == "global_config.yaml"


def test_names_round_trip_through_the_context_key_map(workspace):
    """Every produced name must be one `load_context` can map back to a *_path key."""
    from ducta.api.workspace.manager import WorkspaceManager

    produced = set(find_config_files(workspace, "base"))
    assert produced <= set(WorkspaceManager._CONTEXT_KEY_MAP)


def test_load_context_accepts_the_resolved_paths(workspace, monkeypatch):
    """The end-to-end symptom: the context could not be built at all."""
    from ducta.api.workspace.manager import WorkspaceManager

    captured: dict = {}

    class _StubLoader:
        def __init__(self, *a, **k):
            pass

        def load_from_paths(self, config_paths, env):
            captured.update(config_paths)
            return type("Ctx", (), {})()

    monkeypatch.setattr("ducta.setting.context_loader.ContextLoader", _StubLoader)
    WorkspaceManager(workspace).load_context("base")

    assert set(captured) == set(_DECLARATIONS), (
        "load_from_paths requires all five *_path keys; a mis-derived name "
        "silently degrades to '<name>_path' and fails validation"
    )
