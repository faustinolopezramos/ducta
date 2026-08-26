"""Regression: MLNodeCommand exposes whether the node actually called
split_dataframe/kfold_splits, and NodeExecutor warns when a node declared a
split but never applied it — otherwise the run certificate records a split
configuration the node silently ignored.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd

from ducta.core.commands import MLNodeCommand
from ducta.core.execution.runner import NodeExecutor
from ducta.mlrun.split import split_dataframe


def _make_command(function, split_config):
    return MLNodeCommand(
        function=function,
        input_dfs=[pd.DataFrame({"x": range(10)})],
        start_date="2026-01-01",
        end_date="2026-01-01",
        node_name="n1",
        model_version="v1",
        split=split_config,
        seed=1,
    )


class TestMLNodeCommandSplitWasApplied:
    def test_false_before_execute(self):
        cmd = _make_command(lambda df, start_date=None, end_date=None, ml_context=None: df, {"method": "random", "test_size": 0.2})
        assert cmd.split_was_applied() is False

    def test_true_when_node_calls_split_dataframe(self):
        def node(df, start_date=None, end_date=None, ml_context=None):
            split_dataframe(df, ml_context["split"], default_seed=1, ml_context=ml_context)
            return df

        cmd = _make_command(node, {"method": "random", "test_size": 0.2})
        cmd.execute()
        assert cmd.split_was_applied() is True

    def test_false_when_node_ignores_the_split(self):
        cmd = _make_command(lambda df, start_date=None, end_date=None, ml_context=None: df, {"method": "random", "test_size": 0.2})
        cmd.execute()
        assert cmd.split_was_applied() is False

    def test_no_split_declared_reports_false(self):
        # A node without a declared split never needs to apply one — callers
        # (NodeExecutor._warn_if_split_not_applied) must check `command.split`
        # separately rather than trusting this alone.
        cmd = _make_command(lambda df, start_date=None, end_date=None, ml_context=None: df, split_config=None)
        cmd.execute()
        assert cmd.split_was_applied() is False


class TestNodeExecutorWarnsWhenSplitNotApplied:
    def test_warns_when_split_declared_but_not_applied(self):
        cmd = MagicMock()
        cmd.split = {"method": "random", "test_size": 0.2}
        cmd.split_was_applied.return_value = False

        with patch("ducta.core.execution.runner.logger") as mock_logger:
            NodeExecutor._warn_if_split_not_applied(cmd, "n1")
            mock_logger.warning.assert_called_once()

    def test_no_warning_when_split_was_applied(self):
        cmd = MagicMock()
        cmd.split = {"method": "random", "test_size": 0.2}
        cmd.split_was_applied.return_value = True

        with patch("ducta.core.execution.runner.logger") as mock_logger:
            NodeExecutor._warn_if_split_not_applied(cmd, "n1")
            mock_logger.warning.assert_not_called()

    def test_no_warning_when_no_split_declared(self):
        cmd = MagicMock()
        cmd.split = None

        with patch("ducta.core.execution.runner.logger") as mock_logger:
            NodeExecutor._warn_if_split_not_applied(cmd, "n1")
            mock_logger.warning.assert_not_called()

    def test_plain_node_command_without_split_attribute_is_ignored(self):
        # A non-ML NodeCommand has no `.split` attribute at all — the
        # getattr(..., None) duck-typing must not raise for it.
        cmd = MagicMock(spec=[])

        with patch("ducta.core.execution.runner.logger") as mock_logger:
            NodeExecutor._warn_if_split_not_applied(cmd, "n1")
            mock_logger.warning.assert_not_called()
