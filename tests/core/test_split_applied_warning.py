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


class TestTheRunsOwnHyperparameters:
    """What a run was explicitly asked to use reaches the node apart from the merged
    ``hyperparams``, so a search inside the node can tell what is fixed."""

    def _run(self, cli_hyperparams, node_hyperparams=None):
        seen = {}

        def node(df, start_date=None, end_date=None, ml_context=None):
            seen["cli"] = dict(ml_context.cli_hyperparams)
            seen["merged"] = dict(ml_context.hyperparams)
            return df

        MLNodeCommand(
            function=node,
            input_dfs=[pd.DataFrame({"x": range(3)})],
            start_date="2026-01-01",
            end_date="2026-01-01",
            node_name="n1",
            model_version="v1",
            hyperparams={"max_depth": 6, "n_estimators": 100},
            node_config={"hyperparams": node_hyperparams or {}},
            cli_hyperparams=cli_hyperparams,
        ).execute()
        return seen

    def test_the_run_overrides_are_kept_apart_and_merged_into_hyperparams(self):
        seen = self._run({"max_depth": 3})

        assert seen["cli"] == {"max_depth": 3}
        assert seen["merged"] == {"max_depth": 3, "n_estimators": 100}

    def test_the_pipelines_own_hyperparams_are_not_overrides(self):
        assert self._run({}, node_hyperparams={"n_estimators": 50})["cli"] == {}

    def test_a_plain_run_has_none(self):
        assert self._run(None)["cli"] == {}
