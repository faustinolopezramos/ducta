"""Regression tests: `mlops_required` must actually abort the pipeline, and
node functions must receive the real MLOps context handle.

Previously both `_init_mlops_if_needed` and `_start_mlops_integration` caught
every failure with just a `logger.warning`, regardless of `mlops_required`;
and `NodeExecutor` was always constructed with `mlops_context=None`, with
nothing ever updating it once the real MLOpsContext was resolved later.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ducta.core.execution.runner import NodeExecutor
from ducta.core.executors.base import BaseExecutor
from ducta.core.executors.batch import BatchExecutor
from ducta.core.settings import CoreSettings


def _base_executor(mlops_required: bool) -> BaseExecutor:
    executor = BaseExecutor.__new__(BaseExecutor)
    executor.context = MagicMock()
    executor.context.global_settings = {"mlops_required": mlops_required, "mlops_enabled": True}
    executor._mlops_context = None
    executor._mlops_init_attempted = False
    executor._mlflow_required = mlops_required
    executor._mlops_auto_config = MagicMock()
    executor._mlops_auto_config.should_init_mlops_for_pipeline.return_value = True
    # __new__ bypasses __init__; settings are resolved once at construction.
    executor.settings = CoreSettings.from_context(executor.context)
    return executor


def _batch_executor(mlops_required: bool) -> BatchExecutor:
    executor = BatchExecutor.__new__(BatchExecutor)
    executor.context = MagicMock()
    executor.context.global_settings = {"mlops_required": mlops_required, "mlops_enabled": True}
    executor._mlflow_required = mlops_required
    executor.settings = CoreSettings.from_context(executor.context)
    return executor


class TestInitMlopsIfNeededRequired:
    def test_required_true_raises_on_init_failure(self):
        executor = _base_executor(mlops_required=True)
        with patch(
            "ducta.mlrun.config.MLOpsContext.from_context",
            side_effect=RuntimeError("storage backend unresolvable"),
        ):
            with pytest.raises(RuntimeError, match="mlops_required=true"):
                executor._init_mlops_if_needed()

    def test_required_false_degrades_to_warning(self):
        executor = _base_executor(mlops_required=False)
        with patch(
            "ducta.mlrun.config.MLOpsContext.from_context",
            side_effect=RuntimeError("storage backend unresolvable"),
        ):
            executor._init_mlops_if_needed()  # must not raise
        assert executor._mlops_context is None


class TestStartMlopsIntegrationRequired:
    def test_required_true_raises_when_construction_fails(self):
        executor = _batch_executor(mlops_required=True)
        with patch(
            "ducta.core.executors.base.MLOpsExecutorIntegration",
            side_effect=RuntimeError("boom"),
        ):
            with pytest.raises(RuntimeError, match="mlops_required=true"):
                executor._start_mlops_integration({}, "pipeline1", {})

    def test_required_true_raises_when_not_available(self):
        executor = _batch_executor(mlops_required=True)
        fake_integration = MagicMock()
        fake_integration.is_available.return_value = False
        with patch(
            "ducta.core.executors.base.MLOpsExecutorIntegration", return_value=fake_integration
        ):
            with pytest.raises(RuntimeError, match="mlops_required=true"):
                executor._start_mlops_integration({}, "pipeline1", {})

    def test_required_false_returns_none_when_not_available(self):
        executor = _batch_executor(mlops_required=False)
        fake_integration = MagicMock()
        fake_integration.is_available.return_value = False
        with patch(
            "ducta.core.executors.base.MLOpsExecutorIntegration", return_value=fake_integration
        ):
            integration, run_id = executor._start_mlops_integration({}, "pipeline1", {})
        assert run_id is None

    def test_required_false_degrades_to_warning_on_exception(self):
        executor = _batch_executor(mlops_required=False)
        with patch(
            "ducta.core.executors.base.MLOpsExecutorIntegration",
            side_effect=RuntimeError("boom"),
        ):
            integration, run_id = executor._start_mlops_integration({}, "pipeline1", {})
        assert integration is None
        assert run_id is None


class TestNodeExecutorSetMlopsContext:
    def _node_executor(self) -> NodeExecutor:
        context = MagicMock()
        context.global_settings = {}
        context.is_ml_layer = False
        input_loader = MagicMock()
        output_manager = MagicMock()
        return NodeExecutor(context, input_loader, output_manager, max_workers=1)

    def test_initially_none(self):
        ne = self._node_executor()
        assert ne.mlops_context is None
        assert ne._ml_builder.mlops_context is None

    def test_set_mlops_context_updates_both_attributes(self):
        ne = self._node_executor()
        sentinel = object()
        ne.set_mlops_context(sentinel)
        assert ne.mlops_context is sentinel
        assert ne._ml_builder.mlops_context is sentinel

    def test_coordinator_shares_the_same_ml_builder_instance(self):
        # _ml_builder is handed to ParallelCoordinator by reference at
        # construction time — mutating it in place (not replacing the
        # attribute) is what makes set_mlops_context visible there too.
        ne = self._node_executor()
        sentinel = object()
        ne.set_mlops_context(sentinel)
        assert ne._coordinator._ml_builder.mlops_context is sentinel
