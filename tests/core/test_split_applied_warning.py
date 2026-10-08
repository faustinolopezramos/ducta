"""Regression: MLNodeCommand exposes whether the node actually called
split_dataframe/kfold_splits. What the executor does with that is in
tests/core/test_ml_contract.py.
"""

from __future__ import annotations

import pandas as pd

from ducta.core.commands import MLNodeCommand
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
        cmd = _make_command(
            lambda df, start_date=None, end_date=None, ml_context=None: df,
            {"method": "random", "test_size": 0.2},
        )
        assert cmd.split_was_applied() is False

    def test_true_when_node_calls_split_dataframe(self):
        def node(df, start_date=None, end_date=None, ml_context=None):
            split_dataframe(df, ml_context["split"], default_seed=1, ml_context=ml_context)
            return df

        cmd = _make_command(node, {"method": "random", "test_size": 0.2})
        cmd.execute()
        assert cmd.split_was_applied() is True

    def test_false_when_node_ignores_the_split(self):
        cmd = _make_command(
            lambda df, start_date=None, end_date=None, ml_context=None: df,
            {"method": "random", "test_size": 0.2},
        )
        cmd.execute()
        assert cmd.split_was_applied() is False

    def test_no_split_declared_reports_false(self):
        # A node without a declared split never needs to apply one — callers
        # (NodeExecutor._enforce_split) must check `command.split` separately
        # rather than trusting this alone. The enforcement itself is covered in
        # tests/core/test_ml_contract.py.
        cmd = _make_command(
            lambda df, start_date=None, end_date=None, ml_context=None: df, split_config=None
        )
        cmd.execute()
        assert cmd.split_was_applied() is False
