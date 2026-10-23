"""What the MLOps API shows of a run: its final metrics, the user's hyperparameters apart
from Ducta's own bookkeeping, and the run table that joins runs, models and certificates."""

from __future__ import annotations

import pickle
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ducta.api.dependencies import get_current_user
from ducta.api.main import create_app
from ducta.api.models.auth import User
from ducta.api.routes.mlops import _registry_at, _resolve_mlops_storage
from ducta.core.certificate import RunCertificate, write_certificate
from ducta.mlrun.experiment_tracking import ExperimentTracker, RunStatus
from ducta.mlrun.storage import LocalStorageBackend

PIPELINE = "score"


def _client() -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: User(
        id="dev", username="dev", email="dev@example.com", roles=["developer"]
    )
    return TestClient(app)


@pytest.fixture
def project(tmp_path, monkeypatch) -> Path:
    from ducta.console.template import TemplateGenerator, TemplateType

    monkeypatch.chdir(tmp_path)  # the server's source confinement base
    root = tmp_path / "proj"
    TemplateGenerator(root).generate_project(TemplateType.ML_SCORING, "proj")
    return root


@pytest.fixture
def storage(project) -> str:
    return _resolve_mlops_storage(project, None, "dev", PIPELINE)


def _params(project: Path, **extra) -> dict:
    return {"source": str(project), "env": "dev", "pipeline": PIPELINE, **extra}


def _run(storage: str, *, params=None, metrics=None, tags=None, model=None) -> str:
    tracker = ExperimentTracker(
        storage=LocalStorageBackend(base_path=storage), tracking_path="experiment_tracking"
    )
    known = {e["name"]: e["experiment_id"] for e in tracker.list_experiments()}
    experiment_id = known.get(PIPELINE) or tracker.create_experiment(PIPELINE).experiment_id
    run = tracker.start_run(
        experiment_id=experiment_id, name="r", parameters=params or {}, tags=tags or {}
    )
    for key, value in (metrics or {}).items():
        tracker.log_metric(run.run_id, key, value)
    tracker.end_run(run.run_id, RunStatus.COMPLETED)
    if model:
        artifact = Path(storage).parent / f"{run.run_id}.pkl"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_bytes(pickle.dumps({"w": 1}))
        _registry_at(storage).register_model(
            name=model,
            artifact_path=str(artifact),
            artifact_type="pickle",
            framework="sklearn",
            experiment_run_id=run.run_id,
        )
    return run.run_id


def _experiment_runs(project: Path) -> list:
    client = _client()
    experiments = client.get("/api/mlops/experiments", params=_params(project)).json()
    (experiment,) = experiments
    r = client.get(f"/api/mlops/experiments/{experiment['experiment_id']}", params=_params(project))
    assert r.status_code == 200, r.text
    return r.json()["runs"]


class TestARunInAnExperiment:
    def test_carries_the_final_value_of_each_metric(self, project, storage):
        _run(storage, metrics={"val_auc": 0.91})

        (run,) = _experiment_runs(project)

        assert run["metrics"]["val_auc"][-1]["value"] == pytest.approx(0.91)

    def test_keeps_the_users_hyperparameters_apart_from_the_ones_ducta_records(
        self, project, storage
    ):
        _run(storage, params={"max_depth": 6, "_environment_snapshot": '{"python": "3.11"}'})

        (run,) = _experiment_runs(project)

        assert run["parameters"] == {"max_depth": 6}
        assert run["internal_parameters"] == {"_environment_snapshot": '{"python": "3.11"}'}


class TestTheRunTable:
    def test_one_row_per_run_with_its_params_metrics_and_model(self, project, storage):
        run_id = _run(storage, params={"max_depth": 6}, metrics={"auc": 0.91}, model="churn-model")

        r = _client().get("/api/mlops/run-table", params=_params(project))

        assert r.status_code == 200, r.text
        body = r.json()
        (row,) = body["rows"]
        assert row["run_id"] == run_id and row["pipeline"] == PIPELINE
        assert row["param_max_depth"] == 6 and row["metric_auc"] == pytest.approx(0.91)
        assert row["model_name"] == "churn-model" and row["model_version"] == 1
        assert "param_max_depth" in body["columns"] and body["columns"][0] == "run_id"

    def test_is_ordered_by_the_column_asked_for(self, project, storage):
        for auc in (0.7, 0.9, 0.8):
            _run(storage, metrics={"auc": auc})

        r = _client().get(
            "/api/mlops/run-table", params=_params(project, sort_by="metric_auc", ascending=False)
        )

        assert [row["metric_auc"] for row in r.json()["rows"]] == [0.9, 0.8, 0.7]

    def test_a_column_that_does_not_exist_is_a_validation_error_naming_the_columns(
        self, project, storage
    ):
        _run(storage, metrics={"auc": 0.7})

        r = _client().get("/api/mlops/run-table", params=_params(project, sort_by="nope"))

        assert r.status_code == 400
        assert "metric_auc" in r.text

    def test_nothing_tracked_yet_is_an_empty_table_not_an_error(self, project):
        r = _client().get("/api/mlops/run-table", params=_params(project))

        assert r.status_code == 200, r.text
        assert r.json()["rows"] == []

    def test_certificates_are_only_checked_when_asked(self, project, storage):
        _run(storage, tags={"ducta_run_id": "abc123"})

        r = _client().get("/api/mlops/run-table", params=_params(project))

        (row,) = r.json()["rows"]
        assert row["certificate_id"] == "abc123"
        assert "certificate_ok" not in row  # nobody checked: the column is left out


class TestTheRunTableChecksCertificates:
    """A run's certificate is looked up where the certificate routes look for it."""

    def _certify(self, project, run_id):
        from ducta.api.services.run_certificates import env_runs_dir

        runs_dir = env_runs_dir(project, "dev")
        assert runs_dir is not None
        cert = RunCertificate(
            run_id=run_id,
            pipeline=PIPELINE,
            environment_name="dev",
            status="success",
            started_at="2026-01-01T00:00:00+00:00",
            ended_at="2026-01-01T00:01:00+00:00",
            ducta_version="1.0.0",
        )
        cert.certificate_hash = cert.compute_hash()
        return write_certificate(cert, runs_dir / "dev" / run_id)

    def test_an_intact_certificate_is_ok(self, project, storage):
        self._certify(project, "run-intact")
        _run(storage, tags={"ducta_run_id": "run-intact"})

        r = _client().get("/api/mlops/run-table", params=_params(project, verify_certificates=True))

        (row,) = r.json()["rows"]
        assert row["certificate_ok"] is True

    def test_an_altered_certificate_is_not(self, project, storage):
        path = self._certify(project, "run-altered")
        path.write_text(path.read_text().replace('"success"', '"failed"'), encoding="utf-8")
        _run(storage, tags={"ducta_run_id": "run-altered"})

        r = _client().get("/api/mlops/run-table", params=_params(project, verify_certificates=True))

        (row,) = r.json()["rows"]
        assert row["certificate_ok"] is False

    def test_a_certificate_that_is_gone_is_not_ok(self, project, storage):
        _run(storage, tags={"ducta_run_id": "run-missing"})

        r = _client().get("/api/mlops/run-table", params=_params(project, verify_certificates=True))

        (row,) = r.json()["rows"]
        assert row["certificate_ok"] is False
