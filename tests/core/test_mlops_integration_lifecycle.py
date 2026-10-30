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

from ducta.core.mlops_integration import MLOpsExecutorIntegration
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


def test_the_config_snapshot_is_logged_with_a_context(mlops):
    mlops.context = SimpleNamespace(
        global_config={"environment": "dev"}, pipelines_config={}, nodes_config={}
    )
    _, run_id = _run(mlops)

    artifacts = mlops._tracker.get_run(run_id).artifacts
    assert any("config_snapshot" in str(a) for a in artifacts)


class TestTheRunKnowsItsCertificate:
    """A tracked run carries the id of the certificate that will attest it, and two facts
    that certificate holds, so a run table needs no certificate to be read."""

    @pytest.fixture
    def with_ledger(self, mlops):
        from ducta.core.ledger import RunLedger

        mlops.context = SimpleNamespace(
            global_config={}, pipelines_config={}, nodes_config={}, input_config={}
        )
        return RunLedger.start(mlops.context, "cert-123")

    def test_the_run_is_tagged_with_the_certificates_run_id(self, mlops, with_ledger):
        _, run_id = _run(mlops)

        assert mlops._tracker.get_run(run_id).tags["ducta_run_id"] == "cert-123"

    def test_without_a_ledger_run_id_there_is_no_tag(self, mlops):
        _, run_id = _run(mlops)

        assert "ducta_run_id" not in mlops._tracker.get_run(run_id).tags

    def test_ending_the_run_logs_the_code_hash(self, mlops, with_ledger):
        _, run_id = _run(mlops)
        with_ledger.record_code("train", {"module_hash": "sha256:aaa"})
        with_ledger.record_code("clean", {"source_hash": "sha256:bbb"})

        mlops.end_pipeline_run(run_id)

        code_hash = mlops._tracker.get_run(run_id).parameters["_code_hash"]
        assert code_hash.startswith("sha256:") and len(code_hash) == len("sha256:") + 64

    def test_changing_the_code_changes_the_code_hash(self, mlops, with_ledger):
        _, first = _run(mlops)
        with_ledger.record_code("train", {"module_hash": "sha256:aaa"})
        mlops.end_pipeline_run(first)
        with_ledger.record_code("train", {"module_hash": "sha256:zzz"})
        _, second = _run(mlops)
        mlops.end_pipeline_run(second)

        hashes = [mlops._tracker.get_run(r).parameters["_code_hash"] for r in (first, second)]
        assert hashes[0] != hashes[1]

    @pytest.mark.parametrize(
        "nodes, expected",
        [
            ([{"split_required": True, "split_applied": True}], "true"),
            ([{"split_required": True, "split_applied": False}], "false"),
            (
                [
                    {"split_required": True, "split_applied": True},
                    {"split_required": True, "split_applied": False},
                ],
                "false",
            ),
        ],
    )
    def test_the_run_says_whether_the_declared_split_was_applied(
        self, mlops, with_ledger, nodes, expected
    ):
        _, run_id = _run(mlops)
        for i, ml in enumerate(nodes):
            with_ledger.record_node(f"n{i}", "success", ml=ml)

        mlops.end_pipeline_run(run_id)

        assert mlops._tracker.get_run(run_id).parameters["_split_applied"] == expected

    def test_no_node_bound_to_a_split_means_no_claim(self, mlops, with_ledger):
        _, run_id = _run(mlops)
        with_ledger.record_node("features", "success", ml={"split_required": False})

        mlops.end_pipeline_run(run_id)

        assert "_split_applied" not in mlops._tracker.get_run(run_id).parameters
