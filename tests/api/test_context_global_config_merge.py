"""Regression: API-driven runs dropped the base global config for environments
that declare their own ``global_config_path``.

The CLI (``AppConfigManager._merge_base_and_env``) passes ``ContextLoader`` a
``base_global_config_path`` so the environment's file is deep-merged over the
base one. ``WorkspaceManager.load_context`` did not, so the environment's file
*replaced* the base: every base-only setting vanished. In the demo workspace
that was ``spark_config: {spark.sql.execution.arrow.pyspark.enabled: "false"}``
— ``ducta start -e dev`` trained the model, the same pipeline launched from the
UI hit Arrow's Java 21 failure in ``toPandas()``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ducta.api.workspace.utils import find_base_global_config, find_config_files

_BASE = {
    "global_config_path": "config/global_config.yaml",
    "pipelines_config_path": "config/pipelines.yaml",
    "nodes_config_path": "config/nodes.yaml",
    "input_config_path": "config/input.yaml",
    "output_config_path": "config/output.yaml",
}

_BASE_GLOBAL = {
    "input_path": "./data",
    "output_path": "./data",
    "mode": "local",
    "environment": "base",
    "spark_config": {"spark.sql.execution.arrow.pyspark.enabled": "false"},
    "mlops_enabled": True,
}

_DEV_GLOBAL = {"environment": "dev", "mlops_enabled": False}


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "env").mkdir()
    for key, rel in _BASE.items():
        content = _BASE_GLOBAL if key == "global_config_path" else {}
        (tmp_path / rel).write_text(yaml.safe_dump(content))
    (tmp_path / "env" / "dev.yaml").write_text(yaml.safe_dump(_DEV_GLOBAL))
    (tmp_path / "environment.yaml").write_text(
        yaml.safe_dump(
            {
                "env_config": {
                    "base": _BASE,
                    "dev": {"global_config_path": "env/dev.yaml"},
                    # Overrides another document but keeps base's global config.
                    "prod": {"pipelines_config_path": "config/pipelines.yaml"},
                }
            }
        )
    )
    return tmp_path


class TestFindBaseGlobalConfig:
    def test_env_with_its_own_global_config_gets_the_base_to_merge_over(self, workspace):
        assert find_config_files(workspace, "dev")["global_config"].name == "dev.yaml"
        assert find_base_global_config(workspace, "dev") == (
            workspace / "config" / "global_config.yaml"
        )

    def test_base_itself_has_nothing_to_merge(self, workspace):
        assert find_base_global_config(workspace, "base") is None

    def test_env_reusing_the_base_global_config_has_nothing_to_merge(self, workspace):
        assert find_base_global_config(workspace, "prod") is None

    def test_matches_the_cli_resolution(self, workspace):
        """Same environment.yaml, same answer as `ducta start` — the parity this fixes."""
        from ducta.console.config import AppConfigManager

        cli_paths = AppConfigManager(str(workspace / "environment.yaml")).get_env_config("dev")

        api_base = find_base_global_config(workspace, "dev")
        assert api_base is not None
        assert Path(cli_paths["base_global_config_path"]).resolve() == api_base.resolve()


class TestLoadContextMergesGlobalConfig:
    def test_load_context_passes_the_base_global_config(self, workspace, monkeypatch):
        from ducta.api.workspace.manager import WorkspaceManager

        captured: dict = {}

        class _StubLoader:
            def __init__(self, *a, **k):
                pass

            def load_from_paths(self, config_paths, env):
                captured.update(config_paths)
                return type("Ctx", (), {})()

        monkeypatch.setattr("ducta.setting.context_loader.ContextLoader", _StubLoader)
        WorkspaceManager(workspace).load_context("dev")

        assert captured["global_config_path"].endswith("dev.yaml")
        assert captured["base_global_config_path"].endswith("global_config.yaml")

    def test_base_only_settings_survive_and_env_overrides_win(self, workspace):
        """End to end through the real ContextLoader."""
        from ducta.api.workspace.manager import WorkspaceManager

        global_config = WorkspaceManager(workspace).load_context("dev").global_config

        assert global_config["spark_config"] == _BASE_GLOBAL["spark_config"]
        assert global_config["mlops_enabled"] is False
        assert global_config["environment"] == "dev"
