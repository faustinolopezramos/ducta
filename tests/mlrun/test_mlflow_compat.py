"""Ducta's MLflow bridge on both MLflow 2.x and 3.x, against a real local store.

MLflow 3 changed two things Ducta depends on: it refuses a local-folder tracking
store unless ``MLFLOW_ALLOW_FILE_STORE`` is set, and ``log_model`` takes ``name=``
instead of the deprecated ``artifact_path``. ``log_model`` swallows its own errors
(a tracking failure must not fail a pipeline), so these tests read the model back
rather than trusting that no exception was raised.
"""

from __future__ import annotations

import sys

import pytest

mlflow = pytest.importorskip("mlflow")
sklearn_linear = pytest.importorskip("sklearn.linear_model")

from ducta.mlrun import mlflow as bridge  # noqa: E402
from ducta.mlrun.mlflow import MLflowPipelineTracker  # noqa: E402

MLFLOW_3 = bridge._mlflow_major() >= 3


@pytest.fixture(autouse=True)
def _real_pyspark_free(monkeypatch, tmp_path):
    # With a database store MLflow puts artifacts under the working directory.
    monkeypatch.chdir(tmp_path)
    # tests/setting/conftest.py may leave a fake `pyspark` in sys.modules; MlflowClient
    # probes for a Spark session on construction and the stub cannot answer.
    # Only a stub (no __file__): removing the real pyspark would make MLflow import
    # a second copy without the submodules (pyspark.ml) other tests already loaded.
    for name in ("pyspark", "pyspark.sql"):
        module = sys.modules.get(name)
        if module is not None and getattr(module, "__file__", None) is None:
            monkeypatch.delitem(sys.modules, name)
    # tests/stream and tests/gate install a stub `polars` too; MLflow 3 inspects
    # `polars` when it is already imported, and the stub has no `Series`.
    monkeypatch.delitem(sys.modules, "polars", raising=False)
    monkeypatch.delenv("MLFLOW_ALLOW_FILE_STORE", raising=False)


def _tracker(uri: str) -> MLflowPipelineTracker:
    return MLflowPipelineTracker(
        experiment_name="compat", tracking_uri=uri, enable_autolog=False, nested_runs=True
    )


def _model():
    return sklearn_linear.LinearRegression().fit([[0.0], [1.0], [2.0]], [1.0, 3.0, 5.0])


class TestTrackingStores:
    def test_a_local_folder_store_still_works(self, tmp_path):
        tracker = _tracker(f"file://{tmp_path / 'mlruns'}")
        with tracker.start_pipeline_run("p") as run_id:
            assert run_id is not None

    def test_a_relative_folder_store_still_works(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with _tracker("mlruns").start_pipeline_run("p") as run_id:
            assert run_id is not None

    @pytest.mark.skipif(not MLFLOW_3, reason="MLflow 2 needs no opt-in for a file store")
    def test_on_mlflow_3_the_folder_store_is_opted_in_with_a_warning(self, tmp_path):
        import os

        messages = []
        # Ducta disables its own logs as a library; the CLI and the API turn them on.
        bridge.logger.enable("ducta")
        handle = bridge.logger.add(lambda m: messages.append(str(m)), level="WARNING")
        try:
            _tracker(f"file://{tmp_path / 'mlruns'}")
        finally:
            bridge.logger.remove(handle)
            bridge.logger.disable("ducta")
        assert os.environ.get("MLFLOW_ALLOW_FILE_STORE") == "true"
        assert any("sqlite:///" in m and "migrate-filestore" in m for m in messages)

    def test_an_explicit_opt_out_is_respected(self, tmp_path, monkeypatch):
        import os

        monkeypatch.setenv("MLFLOW_ALLOW_FILE_STORE", "false")
        bridge._allow_file_store(f"file://{tmp_path}")
        assert os.environ["MLFLOW_ALLOW_FILE_STORE"] == "false"

    def test_a_database_store_needs_no_opt_in(self, tmp_path):
        import os

        tracker = _tracker(f"sqlite:///{tmp_path / 'mlflow.db'}")
        with tracker.start_pipeline_run("p") as run_id:
            assert run_id is not None
        assert "MLFLOW_ALLOW_FILE_STORE" not in os.environ


@pytest.mark.parametrize("store", ["file", "sqlite"])
class TestModels:
    def _uri(self, store, tmp_path):
        return (
            f"file://{tmp_path / 'mlruns'}" if store == "file" else f"sqlite:///{tmp_path / 'm.db'}"
        )

    def test_a_logged_model_can_be_loaded_back_and_predicts(self, store, tmp_path):
        tracker = _tracker(self._uri(store, tmp_path))
        with tracker.start_pipeline_run("p"):
            with tracker.start_node_step("train") as run_id:
                tracker.log_model(_model(), "model", flavor="sklearn", node_name="train")
        loaded = mlflow.sklearn.load_model(f"runs:/{run_id}/model")
        assert loaded.predict([[3.0]])[0] == pytest.approx(7.0)

    def test_a_model_without_a_flavor_is_detected_as_sklearn(self, store, tmp_path):
        tracker = _tracker(self._uri(store, tmp_path))
        with tracker.start_pipeline_run("p"):
            with tracker.start_node_step("train") as run_id:
                tracker.log_model(_model(), "model", node_name="train")
        assert mlflow.sklearn.load_model(f"runs:/{run_id}/model").predict([[0.0]])[
            0
        ] == pytest.approx(1.0)

    def test_metrics_and_params_land_on_the_node_run(self, store, tmp_path):
        tracker = _tracker(self._uri(store, tmp_path))
        with tracker.start_pipeline_run("p"):
            with tracker.start_node_step("train") as run_id:
                tracker.log_node_metric("rmse", 0.5, node_name="train")
                tracker.log_node_param("alpha", "0.1", node_name="train")
        run = tracker._client.get_run(run_id)
        assert run.data.metrics["rmse"] == 0.5 and run.data.params["alpha"] == "0.1"


def test_the_model_location_keyword_matches_the_installed_mlflow():
    assert bridge._model_location("model") == (
        {"name": "model"} if MLFLOW_3 else {"artifact_path": "model"}
    )


class TestAFailedLogIsNotSilent:
    """A model that fails to reach MLflow used to be a warning and a 'successful' run."""

    def _failing_log(self, tracker):
        # The tensorflow flavor needs tensorflow, which is not installed here.
        with tracker.start_pipeline_run("p"):
            with tracker.start_node_step("train"):
                tracker.log_model(_model(), "model", flavor="tensorflow", node_name="train")

    def test_when_mlflow_is_required_the_node_fails(self, tmp_path):
        tracker = MLflowPipelineTracker(
            experiment_name="compat",
            tracking_uri=f"sqlite:///{tmp_path / 'm.db'}",
            enable_autolog=False,
            required=True,
        )
        with pytest.raises(bridge.MLflowTrackingError, match="did not record the model 'model'"):
            self._failing_log(tracker)

    def test_otherwise_it_is_an_error_in_the_log_not_a_warning(self, tmp_path):
        tracker = _tracker(f"sqlite:///{tmp_path / 'm.db'}")
        records = []
        bridge.logger.enable("ducta")
        handle = bridge.logger.add(lambda m: records.append(m.record), level="WARNING")
        try:
            self._failing_log(tracker)
        finally:
            bridge.logger.remove(handle)
            bridge.logger.disable("ducta")
        errors = [r for r in records if r["level"].name == "ERROR"]
        assert any("did NOT record the model 'model'" in r["message"] for r in errors)
        assert any("settings.mlflow.required: true" in r["message"] for r in errors)

    def test_required_comes_from_settings_mlflow_or_mlops_required(self):
        class Ctx:
            def __init__(self, gs):
                self.global_config = gs

        def required(gs):
            return MLflowPipelineTracker.from_context(Ctx(gs), "e").required

        assert required({"mlflow": {"required": True, "tracking_uri": "sqlite:///:memory:"}})
        assert required({"mlops_required": True, "mlflow": {"tracking_uri": "sqlite:///:memory:"}})
        assert not required({"mlflow": {"tracking_uri": "sqlite:///:memory:"}})
