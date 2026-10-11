"""One experiment per pipeline: each execution is a run in it.

`create_pipeline_experiment` used to create a new experiment on every
execution, so the Models page listed `bronze.ingestion` eight times — one
experiment per run, each holding a single run.
"""

from __future__ import annotations

from types import SimpleNamespace

from ducta.core.mlops_integration import MLOpsExecutorIntegration
from ducta.mlrun.experiment_tracking import ExperimentTracker
from ducta.mlrun.storage import LocalStorageBackend


def _integration(tmp_path) -> MLOpsExecutorIntegration:
    tracker = ExperimentTracker(storage=LocalStorageBackend(base_path=str(tmp_path)))
    mlops = SimpleNamespace(experiment_tracker=tracker, model_registry=object())
    return MLOpsExecutorIntegration(mlops_context=mlops, auto_init=False)  # type: ignore[arg-type]


def test_a_second_execution_reuses_the_pipelines_experiment(tmp_path):
    first = _integration(tmp_path).create_pipeline_experiment("silver.clean", "batch")
    second = _integration(tmp_path).create_pipeline_experiment("silver.clean", "batch")
    other = _integration(tmp_path).create_pipeline_experiment("golden.transformation", "batch")

    assert first is not None and first == second
    assert other not in (None, first)
    names = [e["name"] for e in _integration(tmp_path)._tracker.list_experiments()]
    assert sorted(names) == ["golden.transformation", "silver.clean"]
