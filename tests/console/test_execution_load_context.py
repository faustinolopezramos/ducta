"""Regression: `console.execution.load_context` always constructed its
`Context` with `validate=False` unconditionally — silently skipping schema
validation for every caller, regardless of whether they wanted that.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from ducta.console.execution import load_context

_CONFIG_DATA = {
    "global_config": {"input_path": "/in", "output_path": "/out", "mode": "local"},
    "pipelines_config": {},
    "nodes_config": {},
    "input_config": {},
    "output_config": {},
}


class TestLoadContextValidateDefault:
    @patch("ducta.console.execution.Context")
    @patch("ducta.setting.loaders.ConfigLoaderFactory")
    def test_defaults_to_validating(self, mock_factory_cls, mock_context_cls):
        mock_factory_cls.return_value.load_config.return_value = _CONFIG_DATA
        mock_context_cls.return_value = MagicMock()

        load_context("config.yaml")

        _, kwargs = mock_context_cls.call_args
        assert kwargs["validate"] is True

    @patch("ducta.console.execution.Context")
    @patch("ducta.setting.loaders.ConfigLoaderFactory")
    def test_caller_can_still_opt_out(self, mock_factory_cls, mock_context_cls):
        mock_factory_cls.return_value.load_config.return_value = _CONFIG_DATA
        mock_context_cls.return_value = MagicMock()

        load_context("config.yaml", validate=False)

        _, kwargs = mock_context_cls.call_args
        assert kwargs["validate"] is False
