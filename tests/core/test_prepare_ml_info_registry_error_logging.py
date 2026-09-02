"""Regression: BaseExecutor._prepare_ml_info swallowed model_registry.get_model()
errors with a bare `except Exception: pass` — unlike every other except block in
this file, which logs. A misconfigured registry, bad credentials, or a missing
model version failed silently, and the pipeline ran on without ml_info["model"]
with no trace of why.
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


class TestModelRegistryErrorIsLogged:
    def test_registry_error_is_logged_as_a_warning(self, monkeypatch):
        import ducta.core.executors.base as base_module

        warnings = []
        monkeypatch.setattr(base_module.logger, "warning", lambda *a, **k: warnings.append((a, k)))

        registry = MagicMock()
        registry.get_model.side_effect = RuntimeError("registry unreachable")

        executor = _executor(registry)
        result = executor._prepare_ml_info("my_pipeline", None, {})

        assert "model" not in result
        assert len(warnings) == 1
        assert "my_pipeline" in warnings[0][0]

    def test_successful_lookup_still_populates_model(self):
        registry = MagicMock()
        registry.get_model.return_value = "the-model"

        executor = _executor(registry)
        result = executor._prepare_ml_info("my_pipeline", None, {})

        assert result["model"] == "the-model"
