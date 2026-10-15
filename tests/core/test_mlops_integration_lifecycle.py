"""One pipeline run through the MLOps layer, against a real tracker and registry.

`MLOpsExecutorIntegration` is what the executors call around every run: open a
run in the pipeline's experiment, log each node, close the run with its final
metrics, register a model. Everything here uses the local storage backend, so
what is asserted is what the Models page later reads.
"""

from __future__ import annotations

import json
import pickle
from types import SimpleNamespace

import pytest

from ducta.core.mlops_integration import MLInfoConfigLoader, MLOpsExecutorIntegration
from ducta.mlrun.experiment_tracking import ExperimentTracker, RunStatus
from ducta.mlrun.model_registry import ModelRegistry
from ducta.mlrun.storage import LocalStorageBackend


@pytest.fixture
def mlops(tmp_path, monkeypatch):
    storage = LocalStorageBackend(base_path=str(tmp_path / "mlops"))
    context = SimpleNamespace(
        experiment_tracker=ExperimentTracker(storage=storage),
        model_registry=ModelRegistry(storage=storage, validate_artifacts=False),
    )
    integration = MLOpsExecutorIntegration(mlops_context=context, auto_init=False)  # type: ignore[arg-type]
    # A package listing per run is slow and says nothing about the integration.
    monkeypatch.setattr(integration, "_capture_environment", lambda: None)
    return integration


def _run(mlops, pipeline="train.churn"):
    experiment_id = mlops.create_pipeline_experiment(pipeline, "batch")
    run_id = mlops.start_pipeline_run(experiment_id, pipeline, hyperparams={"depth": 3})
    assert run_id is not None
    return experiment_id, run_id


def test_unavailable_without_a_tracker_and_does_nothing():
    integration = MLOpsExecutorIntegration(auto_init=False)

    assert integration.is_available() is False
    assert integration.create_pipeline_experiment("p", "batch") is None
    assert integration.start_pipeline_run("e", "p") is None
    assert integration.end_pipeline_run("r") == {}
    assert integration.log_artifact("r", "/nope") is None
    assert integration.register_model_from_run("r", "m", "/nope", "pickle", "sklearn") is None
    integration.log_node_execution("r", "n", "success", 1.0)  # no error either
    with pytest.raises(RuntimeError, match="is_available"):
        integration._tracker  # noqa: B018 — the accessor states the guard


def test_a_run_records_its_nodes_and_ends_with_its_final_metrics(mlops):
    _, run_id = _run(mlops)
    assert mlops.active_run_id == run_id and mlops.pipeline_runs["train.churn"] == run_id

    mlops.log_node_execution(run_id, "train", "success", 2.5, metrics={"auc": 0.91, "note": "x"})
    mlops.log_node_execution(run_id, "score", "failed", 0.5, error="boom")
    mlops.log_pipeline_metrics(run_id, {"rows": 1000, "label": "ignored"})

    final = mlops.end_pipeline_run(run_id, RunStatus.COMPLETED, summary={"nodes": 2})

    assert final["node_train_auc"] == pytest.approx(0.91)
    assert final["node_train_duration_seconds"] == pytest.approx(2.5)
    assert final["rows"] == 1000 and final["summary_nodes"] == 2
    assert "node_train_note" not in final and "label" not in final  # numeric only
    run = mlops._tracker.get_run(run_id)
    assert run.parameters["node_score_status"] == "failed"
    assert run.parameters["node_score_error"] == "boom"
    assert run.parameters["depth"] == 3
    assert mlops.active_run_id is None


def test_a_logged_artifact_and_a_registered_model(mlops, tmp_path):
    _, run_id = _run(mlops)
    model = tmp_path / "model.pkl"
    model.write_bytes(pickle.dumps({"weights": [1, 2, 3]}))

    uri = mlops.log_artifact(run_id, str(model), artifact_type="model")
    assert uri and mlops.node_artifacts[run_id] == [uri]

    registered = mlops.register_model_from_run(
        run_id, "churn", str(model), "pickle", "sklearn", metrics={"auc": 0.9}
    )
    assert registered is not None
    versions = mlops._registry.list_model_versions("churn")
    assert [v["experiment_run_id"] for v in versions] == [run_id]


def test_runs_of_one_experiment_can_be_compared(mlops):
    experiment_id, first = _run(mlops)
    mlops.log_pipeline_metrics(first, {"auc": 0.8})
    mlops.end_pipeline_run(first)
    _, second = _run(mlops)
    mlops.log_pipeline_metrics(second, {"auc": 0.9})
    mlops.end_pipeline_run(second)

    comparison = mlops.get_run_comparison(experiment_id)

    assert comparison is not None and len(comparison) == 2


def test_the_config_snapshot_is_logged_with_a_context(mlops):
    mlops.context = SimpleNamespace(
        global_config={"environment": "dev"}, pipelines_config={}, nodes_config={}
    )
    _, run_id = _run(mlops)

    artifacts = mlops._tracker.get_run(run_id).artifacts
    assert any("config_snapshot" in str(a) for a in artifacts)


class TestMLInfoConfigLoader:
    def test_reads_yaml_and_json(self, tmp_path):
        (tmp_path / "ml.yaml").write_text("model_name: churn\nhyperparams: {depth: 3}\n")
        (tmp_path / "ml.json").write_text(json.dumps({"model_name": "churn"}))

        assert MLInfoConfigLoader.load_ml_info_from_file(str(tmp_path / "ml.yaml"))["hyperparams"]
        assert MLInfoConfigLoader.load_ml_info_from_file(str(tmp_path / "ml.json")) == {
            "model_name": "churn"
        }

    def test_a_missing_or_unknown_file_is_empty(self, tmp_path):
        assert MLInfoConfigLoader.load_ml_info_from_file(str(tmp_path / "nope.yaml")) == {}
        (tmp_path / "ml.ini").write_text("x=1")
        assert MLInfoConfigLoader.load_ml_info_from_file(str(tmp_path / "ml.ini")) == {}

    def test_merge_overrides_and_merges_nested_maps(self):
        base = {"model_name": "a", "hyperparams": {"depth": 3, "lr": 0.1}, "tags": {"x": "1"}}
        override = {"model_name": "b", "hyperparams": {"lr": 0.2}, "tags": {"y": "2"}}

        merged = MLInfoConfigLoader.merge_ml_info(base, override)

        assert merged["model_name"] == "b"
        assert merged["hyperparams"] == {"depth": 3, "lr": 0.2}
        assert merged["tags"] == {"x": "1", "y": "2"}
