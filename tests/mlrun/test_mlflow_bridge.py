"""Unit tests for ducta.mlrun.mlflow.MLflowPipelineTracker.

Uses a local file-based MLflow tracking store (no network) so these run
without a real tracking server.
"""

from __future__ import annotations

import sys

import pytest

mlflow = pytest.importorskip("mlflow")

from ducta.mlrun.mlflow import MLflowPipelineTracker  # noqa: E402


@pytest.fixture
def tracker(tmp_path, monkeypatch):
    # tests/setting/conftest.py installs a fake `pyspark`/`pyspark.sql` module
    # into sys.modules for the whole session (no real pyspark is installed
    # here) with no teardown, so it can still be present when these tests run
    # in the same session. Real mlflow's MlflowClient() probes for an active
    # Spark session on construction, and the fake module's stub SparkSession
    # doesn't implement that API — remove it for the duration of this test
    # only; monkeypatch restores sys.modules afterward regardless.
    # Only a stub (no __file__): removing the real pyspark would make MLflow import
    # a second copy without the submodules (pyspark.ml) other tests already loaded.
    for name in ("pyspark", "pyspark.sql"):
        module = sys.modules.get(name)
        if module is not None and getattr(module, "__file__", None) is None:
            monkeypatch.delitem(sys.modules, name)
    return MLflowPipelineTracker(
        experiment_name="test_exp",
        tracking_uri=f"file://{tmp_path / 'mlruns'}",
        enable_autolog=False,
        nested_runs=True,
    )


class TestStartPipelineRunBestEffort:
    def test_normal_run_yields_run_id(self, tracker):
        with tracker.start_pipeline_run("my_pipeline") as run_id:
            assert run_id is not None
            assert run_id == tracker._active_pipeline_run

    def test_unreachable_server_degrades_to_no_op_instead_of_raising(self, tracker, monkeypatch):
        def broken_start_run(*args, **kwargs):
            raise ConnectionError("tracking server unreachable")

        monkeypatch.setattr(mlflow, "start_run", broken_start_run)

        # Must not raise, and the pipeline body underneath must still execute.
        body_ran = False
        with tracker.start_pipeline_run("my_pipeline") as run_id:
            body_ran = True
            assert run_id is None

        assert body_ran is True
        assert tracker._active_pipeline_run is None

    def test_genuine_pipeline_body_failure_still_propagates(self, tracker):
        # A real failure *inside* the pipeline body (not an MLflow-entry
        # failure) must still propagate and be treated as a failed run.
        with pytest.raises(ValueError, match="node blew up"):
            with tracker.start_pipeline_run("my_pipeline"):
                raise ValueError("node blew up")


class TestLogNodeArtifactUsesClientNotFluentApi:
    def test_log_artifact_within_node_step_does_not_end_the_run_early(self, tracker, tmp_path):
        artifact = tmp_path / "out.txt"
        artifact.write_text("hello")

        with tracker.start_pipeline_run("pipe"):
            with tracker.start_node_step("node1") as node_run_id:
                tracker.log_node_artifact(str(artifact), node_name="node1")
                # The node's run must still be RUNNING — logging the artifact
                # (via MlflowClient, not the fluent API) must not have ended it.
                run = tracker._client.get_run(node_run_id)
                assert run.info.status == "RUNNING"

    def test_artifact_is_actually_recorded_on_the_right_run(self, tracker, tmp_path):
        artifact = tmp_path / "out.txt"
        artifact.write_text("hello")

        with tracker.start_pipeline_run("pipe"):
            with tracker.start_node_step("node1") as node_run_id:
                tracker.log_node_artifact(str(artifact), node_name="node1")

        artifacts = [a.path for a in tracker._client.list_artifacts(node_run_id)]
        assert "out.txt" in artifacts
