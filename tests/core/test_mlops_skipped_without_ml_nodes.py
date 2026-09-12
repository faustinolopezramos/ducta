"""Experiment tracking belongs to pipelines that do ML.

``_start_mlops_integration`` consulted only ``settings.mlops_enabled`` — which
defaults to true — and never asked whether the pipeline it was about to track
contained anything ML-shaped. So a plain ETL created an ``experiment_tracking/``
tree under the output path and opened, tagged and closed a tracking run on every
execution. Measured on the ``medallion_basic`` scaffold, which has no ML node at
all:

    INFO  MLOpsContext initialized from execution context
    WARNING  Non-retryable exception in 'read_dataframe': .../runs/index.parquet not found
    WARNING  Non-retryable exception in 'read_dataframe': .../metrics/index.parquet not found
    INFO  Ended MLOps run f3419051-… with status COMPLETED

The detection this needed already existed —
``MLOpsAutoConfigurator.should_init_mlops_for_pipeline`` — but nothing in the
execution path called it: the only caller was a ``BaseExecutor.mlops_context``
property that no production code read.

It also has to look at *this pipeline's* nodes. It was being handed
``context.nodes_config``, every node in the project, so one ML node anywhere
turned tracking on for every batch pipeline that shared the config.
"""

from __future__ import annotations

import pytest

from ducta.core.mlops_auto_config import MLOpsAutoConfigurator

BATCH_NODES = {
    "extract": {"module": "nodes", "function": "extract", "output": ["bronze.raw"]},
    "transform": {
        "module": "nodes",
        "function": "transform",
        "input": ["bronze.raw"],
        "output": ["silver.clean"],
    },
}

ML_NODES = {
    "train_model": {"module": "nodes", "function": "fit", "ml_stage": "training"},
}


class TestPipelineScopedDetection:
    def test_a_pure_batch_pipeline_needs_no_tracking(self):
        assert MLOpsAutoConfigurator.should_init_mlops_for_pipeline(dict(BATCH_NODES), {}) is False

    def test_an_ml_pipeline_still_gets_tracking(self):
        assert MLOpsAutoConfigurator.should_init_mlops_for_pipeline(dict(ML_NODES), {}) is True

    def test_an_ml_node_in_another_pipeline_does_not_leak(self):
        """The caller must pass this pipeline's nodes, not the whole project.

        This is the assertion that pins the call-site fix: given only the batch
        pipeline's nodes, detection says no — so if tracking still starts for the
        ETL, the caller handed over the wrong set.
        """
        whole_project = {**BATCH_NODES, **ML_NODES}

        assert MLOpsAutoConfigurator.should_init_mlops_for_pipeline(whole_project, {}) is True
        assert MLOpsAutoConfigurator.should_init_mlops_for_pipeline(dict(BATCH_NODES), {}) is False


class TestExplicitSettingsWin:
    def test_nested_enabled_false_disables(self):
        assert (
            MLOpsAutoConfigurator.should_init_mlops_for_pipeline(
                dict(ML_NODES), {"mlops": {"enabled": False}}
            )
            is False
        )

    def test_nested_enabled_true_forces_on(self):
        assert (
            MLOpsAutoConfigurator.should_init_mlops_for_pipeline(
                dict(BATCH_NODES), {"mlops": {"enabled": True}}
            )
            is True
        )

    def test_flat_mlops_enabled_false_disables(self):
        """``mlops_enabled`` is the spelling GlobalConfigSchema documents, and
        CoreSettings honours both — this function honoured only the nested one,
        so the documented flag did nothing here."""
        assert (
            MLOpsAutoConfigurator.should_init_mlops_for_pipeline(
                dict(ML_NODES), {"mlops_enabled": False}
            )
            is False
        )

    def test_flat_mlops_enabled_true_forces_on(self):
        assert (
            MLOpsAutoConfigurator.should_init_mlops_for_pipeline(
                dict(BATCH_NODES), {"mlops_enabled": True}
            )
            is True
        )

    def test_nested_beats_flat(self):
        """The more specific declaration wins, matching CoreSettings."""
        assert (
            MLOpsAutoConfigurator.should_init_mlops_for_pipeline(
                dict(ML_NODES), {"mlops_enabled": True, "mlops": {"enabled": False}}
            )
            is False
        )
