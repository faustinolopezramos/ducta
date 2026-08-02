"""Unit tests for ducta.core.mlops_auto_config.MLOpsAutoConfigurator.

Regression coverage for the I/O-pattern false-positive fix: matching used to
be plain substring (`pattern in io_str`), which flagged ordinary BI/analytics
datasets as ML workloads whenever a pattern like "metrics" appeared inside an
unrelated compound name.
"""

from __future__ import annotations

from ducta.core.mlops_auto_config import MLOpsAutoConfigurator


class TestIOPatternWholeTokenMatching:
    def test_ordinary_bi_dataset_does_not_trigger_mlops(self):
        node_config = {"input": ["raw.sales"], "output": ["core.analytics.sales_metrics_daily"]}
        assert (
            MLOpsAutoConfigurator.should_enable_mlops(node_config, node_name="compute_sales")
            is False
        )

    def test_underscore_named_dataset_does_not_false_positive_on_substring(self):
        # "score" is a substring of "underscore" but not a whole token.
        node_config = {"input": ["raw.add_underscore_prefix"], "output": []}
        assert MLOpsAutoConfigurator.should_enable_mlops(node_config, node_name="clean") is False

    def test_model_dataset_name_triggers_mlops(self):
        # node_name "step1" deliberately matches no ML_NODE_PATTERNS/
        # ML_FUNCTION_PATTERNS, so only the I/O-pattern check is exercised.
        node_config = {"input": [], "output": ["predictions.step1_model_v2"]}
        assert MLOpsAutoConfigurator.should_enable_mlops(node_config, node_name="step1") is True

    def test_checkpoint_dataset_name_triggers_mlops(self):
        node_config = {"input": ["artifacts.step1_checkpoint"], "output": []}
        assert MLOpsAutoConfigurator.should_enable_mlops(node_config, node_name="step1") is True


class TestShouldInitMlopsForPipeline:
    def test_bi_pipeline_not_auto_enabled(self):
        nodes_config = {
            "compute_sales": {
                "input": ["raw.sales"],
                "output": ["core.analytics.sales_metrics_daily"],
            }
        }
        assert MLOpsAutoConfigurator.should_init_mlops_for_pipeline(nodes_config, {}) is False

    def test_ml_pipeline_auto_enabled(self):
        nodes_config = {
            "train_model": {
                "input": ["features.train_set"],
                "output": ["predictions.train_model_v2"],
            }
        }
        assert MLOpsAutoConfigurator.should_init_mlops_for_pipeline(nodes_config, {}) is True
