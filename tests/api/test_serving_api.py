"""What the API says about serving: who serves a model, which version they would get,
the details of each version, and the checks a model's output can be held to."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ducta.api.dependencies import get_current_user
from ducta.api.main import create_app
from ducta.api.models.auth import User

sklearn = pytest.importorskip("sklearn")
joblib = pytest.importorskip("joblib")


@pytest.fixture(autouse=True)
def _no_stub_modules(monkeypatch):
    # tests/gate, tests/stream and tests/setting install stub `polars`/`pyspark`
    # modules when the real ones are not installed or not yet imported; sklearn
    # inspects whatever is in sys.modules and fails on a stub.
    for name in ("polars", "pyspark", "pyspark.sql"):
        module = sys.modules.get(name)
        if module is not None and getattr(module, "__file__", None) is None:
            monkeypatch.delitem(sys.modules, name)


def _client(role: str = "developer") -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: User(
        id=role, username=role, email=f"{role}@example.com", roles=[role]
    )
    return TestClient(app)


@pytest.fixture
def project(tmp_path, monkeypatch) -> Path:
    from ducta.console.template import TemplateGenerator, TemplateType

    monkeypatch.chdir(tmp_path)  # the server's source confinement base
    root = tmp_path / "proj"
    TemplateGenerator(root).generate_project(TemplateType.ML_SCORING, "proj")
    return root


def _register(root: Path, versions: int = 1):
    """Register churn-model where the API (and the engine) look for it, in dev."""
    import pandas as pd
    from sklearn.linear_model import LogisticRegression

    from ducta.api.routes.mlops import _registry_at, _resolve_mlops_storage
    from ducta.mlrun.model_registry import ModelStage

    registry = _registry_at(_resolve_mlops_storage(root, None, "dev"))
    df = pd.DataFrame({"tenure_months": range(20), "monthly_spend": range(20)})
    y = [int(i >= 10) for i in range(20)]
    for v in range(1, versions + 1):
        path = root / f"m{v}.joblib"
        joblib.dump(LogisticRegression(C=v).fit(df, y), path)
        mv = registry.register_model(
            name="churn-model",
            artifact_path=str(path),
            artifact_type="sklearn",
            framework="sklearn",
            metrics={"val_auc": 0.9},
            input_schema={"tenure_months": "int64", "monthly_spend": "int64"},
            trust_artifact_source=True,
        )
    registry.promote_model("churn-model", mv.version, ModelStage.PRODUCTION)
    return mv


def _plan(root: Path) -> dict:
    r = _client().get(
        "/api/projects/proj/pipelines/score/ml-plan", params={"source": str(root), "env": "dev"}
    )
    assert r.status_code == 200, r.text
    return r.json()["nodes"]["score"]


class TestTheMLPlanSaysWhichVersionWouldServe:
    def test_the_version_in_production_now(self, project):
        mv = _register(project, versions=2)
        resolution = _plan(project)["model_resolution"]
        assert resolution == {
            "status": "resolved",
            "version": 2,
            "stage": "production",
            "framework": "sklearn",
            "artifact_sha256": mv.artifact_sha256,
        }

    def test_nothing_in_production_yet_is_explained(self, project):
        resolution = _plan(project)["model_resolution"]
        assert resolution["status"] == "unresolved"
        assert "promote a version to production" in resolution["message"]


class TestTheRegistrySaysWhoServesWhat:
    def _params(self, root):
        return {"source": str(root), "env": "dev", "pipeline": "score"}

    def test_each_model_lists_the_nodes_that_serve_it(self, project):
        _register(project)
        r = _client().get("/api/mlops/models", params=self._params(project))
        assert r.status_code == 200, r.text
        (model,) = r.json()
        assert model["served_by"] == [
            {
                "pipeline": "score",
                "node": "score",
                "stage": "production",
                "version": None,
                "streaming": False,
            }
        ]

    def test_a_version_carries_its_stage_metrics_features_and_hash(self, project):
        mv = _register(project)
        r = _client().get("/api/mlops/models/churn-model", params=self._params(project))
        assert r.status_code == 200, r.text
        (version,) = r.json()
        assert version["stage"] == "Production"
        assert version["metrics"] == {"val_auc": 0.9}
        assert version["features"] == ["tenure_months", "monthly_spend"]
        assert version["framework"] == "sklearn"
        assert version["artifact_sha256"] == mv.artifact_sha256


def test_checks_describe_themselves():
    r = _client("viewer").get("/api/quality/checks")
    assert r.status_code == 200, r.text
    checks = {c["name"]: c for c in r.json()}
    drift = checks["prediction_drift"]
    assert drift["default_severity"] == "WARNING"
    assert drift["description"].startswith("The scores' distribution")
    assert drift["params"]["method"]["enum"] == ["psi", "ks"]
    assert checks["row_count"]["params"]["min"]["type"] == "integer"
    assert checks["empty_dataset"]["params"] == {}
