"""Regression: BaseExecutor._prepare_ml_info used to call
``context.get_model_registry().get_model(...)`` — neither of which exists on the
real context, so the lookup never ran and no node ever received a model. Models
are now resolved per node by ``ml_stage: serving`` (``ducta.mlrun.serving``);
pipeline preparation must not touch the registry at all.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from ducta.core.executors.base import BaseExecutor


class _FakeContext:
    def __init__(self, registry):
        self.default_model_version = None
        self.default_hyperparams: dict = {}
        self.project_name = "proj"
        self.pipelines_config: dict = {}
        self._registry = registry

    def get_pipeline_ml_config(self, pipeline_name):
        return {"model_name": "m1"}

    def get_model_registry(self):
        return self._registry


def _executor(registry):
    executor = BaseExecutor.__new__(BaseExecutor)
    executor.context = _FakeContext(registry)
    executor.settings = SimpleNamespace(random_seed=None)
    executor.is_ml_layer = False
    return executor


class TestPipelinePreparationDoesNotLoadModels:
    def test_registry_is_not_consulted(self):
        registry = MagicMock()

        result = _executor(registry)._prepare_ml_info("my_pipeline", None, {})

        registry.get_model.assert_not_called()
        assert "model" not in result
