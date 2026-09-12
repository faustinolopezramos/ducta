"""Preflight must not call a key "ignored" when the engine reads it.

``_check_unknown_node_keys`` warns about node keys that are not declared on
``NodeSchema``, on the reasoning that a misspelled key is dropped in silence.
That is a good warning to have — but its allow-list was built from
``NodeSchema.model_fields`` plus a short hand-written set, and several keys that
other layers consume never made it in.

The result was a warning that was wrong for every ingestion node, every
vectorized node, every ML node carrying metrics, and every streaming node
declaring ``depends_on`` — telling users their working configuration was being
dropped. A warning nobody can trust is worse than no warning: it trains people
to ignore the one that is real.

Each key below is paired with the module that actually reads it.
"""

from __future__ import annotations

import pytest

from ducta.core.preflight import PreflightReport, _check_unknown_node_keys


def _warnings_for(node_config):
    report = PreflightReport(pipeline_name="p")
    _check_unknown_node_keys(report, "n", node_config)
    return report.warnings


def _assert_no_warning_about(node_config, *keys):
    warnings = _warnings_for(node_config)
    for key in keys:
        assert not any(
            f"'{key}'" in w or f" {key}," in w or f"{key}'" in w for w in warnings
        ), f"preflight claims '{key}' is ignored; warnings: {warnings}"


class TestKeysTheEngineActuallyReads:
    def test_ingestion_keys(self):
        """Read by ducta.core.execution.ingestion. ``source`` is *required* by
        preflight's own ``_check_ingestion_node`` in the same module."""
        _assert_no_warning_about(
            {
                "type": "ingestion",
                "source": "crm",
                "table": "public.orders",
                "columns": ["id"],
                "where": "id > 1",
                "options": {"fetchsize": "1000"},
                "output": ["bronze.orders"],
            },
            "source",
            "columns",
            "where",
            "options",
        )

    def test_streaming_depends_on(self):
        """Read by StreamingPipelineManager._process_pipeline_nodes."""
        _assert_no_warning_about(
            {
                "type": "streaming",
                "depends_on": ["extract"],
                "input": {"format": "kafka"},
                "output": {"format": "delta"},
            },
            "depends_on",
        )

    def test_vectorized_execution_keys(self):
        """Read by ducta.core.commands.NodeCommand.execute."""
        _assert_no_warning_about(
            {
                "module": "m",
                "function": "f",
                "execution_mode": "vectorized",
                "execution_mode_max_rows": 1000,
            },
            "execution_mode",
            "execution_mode_max_rows",
        )

    def test_ml_node_keys(self):
        """``metrics`` is read by MLConfigMixin.get_node_ml_config;
        ``model_artifacts`` by DataOutputManager._save_model_artifacts."""
        _assert_no_warning_about(
            {
                "module": "m",
                "function": "f",
                "ml_stage": "training",
                "metrics": ["auc"],
                "model_artifacts": [{"name": "model"}],
            },
            "metrics",
            "model_artifacts",
        )

    def test_mlops_opt_out(self):
        """Read by MLOpsAutoConfigurator.should_enable_mlops."""
        _assert_no_warning_about(
            {"module": "m", "function": "f", "mlops_enabled": False}, "mlops_enabled"
        )


class TestRealTyposAreStillReported:
    """The warning must keep doing its job — that is why it exists."""

    def test_misspelled_dependencies_is_reported(self):
        warnings = _warnings_for({"module": "m", "function": "f", "dependencie": ["a"]})

        assert any("dependencie" in w for w in warnings)

    def test_a_clean_node_produces_no_warning(self):
        assert (
            _warnings_for(
                {"module": "m", "function": "f", "input": ["a"], "output": ["b"], "retry": 1}
            )
            == []
        )
