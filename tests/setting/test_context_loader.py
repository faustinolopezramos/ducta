from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from ducta.setting.context_loader import ContextLoader
from ducta.setting.exceptions import ConfigLoadError

_GLOBAL_CONFIG = {"input_path": "/in", "output_path": "/out", "mode": "local"}


def _config_by_path(global_config=None, **overrides):
    """Build a load_config side effect that answers according to the file asked for.

    Every config file has its own schema (PipelineSchema, NodeSchema, ...), so a
    mock that returns one global-config-shaped dict for *every* path makes
    ConfigSchema validation fail on the four catalog sections. Keyed on the
    filename stem, each section gets a payload its own schema accepts.
    """
    settings = dict(global_config or _GLOBAL_CONFIG)

    def _side_effect(path):
        name = Path(str(path)).name
        for stem, payload in overrides.items():
            if stem in name:
                return dict(payload)
        if "global" in name:
            return dict(settings)
        # pipelines / nodes / input / output catalogs: empty but valid mappings.
        return {}

    return _side_effect


class TestContextLoader:
    def test_init(self):
        loader = ContextLoader()
        assert loader.loader_factory is not None

    @patch("ducta.setting.context_loader.ConfigLoaderFactory")
    def test_init_default_allows_python(self, mock_loader_cls):
        ContextLoader()
        mock_loader_cls.assert_called_once_with(allow_python=True)

    @patch("ducta.setting.context_loader.ConfigLoaderFactory")
    def test_init_can_disallow_python(self, mock_loader_cls):
        loader = ContextLoader(allow_python_config=False)
        mock_loader_cls.assert_called_once_with(allow_python=False)
        assert loader.allow_python_config is False

    @patch("ducta.setting.contexts.ConfigLoaderFactory")
    @patch("ducta.setting.contexts.SparkSessionFactory.get_session")
    def test_load_from_paths_threads_allow_python_into_context(
        self, mock_get_session, mock_ctx_loader_cls
    ):
        """Regression: a workspace/repo path (e.g. api/workspace/manager.py's
        load_context) must be able to keep PythonConfigLoader out of the
        Context it builds, not just out of ContextLoader's own base/env-merge
        loader."""
        mock_get_session.return_value = MagicMock()
        mock_loader = MagicMock()
        mock_loader.load_config.side_effect = _config_by_path()
        mock_ctx_loader_cls.return_value = mock_loader

        loader = ContextLoader(allow_python_config=False)
        ctx = loader.load_from_paths(
            {
                "global_config_path": "/path/global.yaml",
                "pipelines_config_path": "/path/pipelines.yaml",
                "nodes_config_path": "/path/nodes.yaml",
                "input_config_path": "/path/input.yaml",
                "output_config_path": "/path/output.yaml",
            },
            env="dev",
        )
        assert ctx.allow_python_config is False
        mock_ctx_loader_cls.assert_called_once_with(allow_python=False)

    @patch("ducta.setting.contexts.ConfigLoaderFactory")
    @patch("ducta.setting.contexts.SparkSessionFactory.get_session")
    def test_load_from_paths_success(self, mock_get_session, mock_ctx_loader_cls):
        mock_get_session.return_value = MagicMock()
        mock_loader = MagicMock()
        mock_loader.load_config.side_effect = _config_by_path()
        mock_ctx_loader_cls.return_value = mock_loader

        loader = ContextLoader()
        ctx = loader.load_from_paths(
            {
                "global_config_path": "/path/global.yaml",
                "pipelines_config_path": "/path/pipelines.yaml",
                "nodes_config_path": "/path/nodes.yaml",
                "input_config_path": "/path/input.yaml",
                "output_config_path": "/path/output.yaml",
            },
            env="dev",
        )
        assert ctx is not None
        assert ctx.env == "dev"

    @patch("ducta.setting.context_loader.ConfigLoaderFactory")
    def test_load_from_paths_missing_paths(self, mock_loader_cls):
        loader = ContextLoader()
        with pytest.raises(ValueError, match="Missing config paths"):
            loader.load_from_paths(
                {"global_config_path": "/path/global.yaml"},
                env="dev",
            )

    # The base/env merge is performed by ContextLoader itself via its own
    # loader_factory, so that module's factory must be patched too — patching
    # only ducta.setting.contexts leaves the base file going to the real loader.
    @patch("ducta.setting.context_loader.ConfigLoaderFactory")
    @patch("ducta.setting.contexts.ConfigLoaderFactory")
    @patch("ducta.setting.contexts.SparkSessionFactory.get_session")
    def test_load_from_paths_with_base_merge(
        self, mock_get_session, mock_ctx_loader_cls, mock_own_loader_cls
    ):
        mock_get_session.return_value = MagicMock()

        base_settings = {"input_path": "/base/in", "output_path": "/base/out", "mode": "local"}
        env_settings = {"mode": "distributed"}

        side_effect = _config_by_path(global_config=env_settings, base_global=base_settings)
        mock_loader = MagicMock()
        mock_loader.load_config.side_effect = side_effect
        mock_ctx_loader_cls.return_value = mock_loader
        mock_own_loader_cls.return_value = mock_loader

        loader = ContextLoader()
        ctx = loader.load_from_paths(
            {
                "global_config_path": "/env/global.yaml",
                "base_global_config_path": "/base/base_global.yaml",
                "pipelines_config_path": "/path/pipelines.yaml",
                "nodes_config_path": "/path/nodes.yaml",
                "input_config_path": "/path/input.yaml",
                "output_config_path": "/path/output.yaml",
            },
            env="dev",
        )
        assert ctx is not None

    @patch("ducta.setting.context_loader.ConfigLoaderFactory")
    def test_load_file_raises_config_load_error(self, mock_loader_cls):
        mock_loader = MagicMock()
        mock_loader.load_config.side_effect = ConfigLoadError("failed")
        mock_loader_cls.return_value = mock_loader

        loader = ContextLoader()
        with pytest.raises(ConfigLoadError):
            loader._load_file("/path/config.yaml")

    @patch("ducta.setting.context_loader.ConfigLoaderFactory")
    def test_load_file_raises_on_unexpected(self, mock_loader_cls):
        mock_loader = MagicMock()
        mock_loader.load_config.side_effect = ValueError("unexpected")
        mock_loader_cls.return_value = mock_loader

        loader = ContextLoader()
        with pytest.raises(ConfigLoadError, match="Failed to load config"):
            loader._load_file("/path/config.yaml")

    @patch("ducta.setting.contexts.ConfigLoaderFactory")
    @patch("ducta.setting.contexts.SparkSessionFactory.get_session")
    def test_load_from_paths_with_extensions(self, mock_get_session, mock_ctx_loader_cls):
        mock_get_session.return_value = MagicMock()

        settings_with_quality = {
            "input_path": "/in",
            "output_path": "/out",
            "mode": "local",
            "quality": {"extensions": ["my_checks"]},
        }

        mock_loader = MagicMock()
        mock_loader.load_config.side_effect = _config_by_path(global_config=settings_with_quality)
        mock_ctx_loader_cls.return_value = mock_loader

        loader = ContextLoader()
        ctx = loader.load_from_paths(
            {
                "global_config_path": "/path/global.yaml",
                "pipelines_config_path": "/path/pipelines.yaml",
                "nodes_config_path": "/path/nodes.yaml",
                "input_config_path": "/path/input.yaml",
                "output_config_path": "/path/output.yaml",
            },
            env="dev",
        )
        assert ctx is not None

    @patch("ducta.check.core.load_quality_extensions")
    @patch("ducta.setting.contexts.ConfigLoaderFactory")
    @patch("ducta.setting.contexts.SparkSessionFactory.get_session")
    def test_load_from_paths_with_extensions_and_python_disallowed_skips_loading(
        self, mock_get_session, mock_ctx_loader_cls, mock_load_extensions
    ):
        """Regression: allow_python_config=False must also block the
        quality.extensions import path, not just PythonConfigLoader —
        load_quality_extensions() does importlib.import_module() on
        config-supplied module names, the same code-execution trust
        boundary allow_python_config exists to close."""
        mock_get_session.return_value = MagicMock()

        settings_with_quality = {
            "input_path": "/in",
            "output_path": "/out",
            "mode": "local",
            "quality": {"extensions": ["my_checks"]},
        }

        mock_loader = MagicMock()
        mock_loader.load_config.side_effect = _config_by_path(global_config=settings_with_quality)
        mock_ctx_loader_cls.return_value = mock_loader

        loader = ContextLoader(allow_python_config=False)
        ctx = loader.load_from_paths(
            {
                "global_config_path": "/path/global.yaml",
                "pipelines_config_path": "/path/pipelines.yaml",
                "nodes_config_path": "/path/nodes.yaml",
                "input_config_path": "/path/input.yaml",
                "output_config_path": "/path/output.yaml",
            },
            env="dev",
        )
        assert ctx is not None
        mock_load_extensions.assert_not_called()
