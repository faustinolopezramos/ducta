"""What the registry endpoints tell the web UI after the ML level 2 work.

- ``/models`` gave the latest version's stage only: with v1 in Production and a
  refused retrain v2 in Staging, the UI filed the model under Staging and showed
  nothing serving.
- A promotion from the web was audit-logged as the server's OS user, with no reason,
  and a forced one could not carry one; deletions were not audit-logged at all.
- Nothing exposed the policy, a dry check of it, or the model's history.
"""

from __future__ import annotations

import pickle
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ducta.api.dependencies import get_current_user
from ducta.api.main import create_app
from ducta.api.models.auth import User
from ducta.api.routes.mlops import _registry_at, _resolve_mlops_storage
from ducta.mlrun.model_registry import ModelStage

PIPELINE = "score"


def _client() -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: User(
        id="ana", username="ana", email="ana@example.com", roles=["admin"]
    )
    return TestClient(app)


@pytest.fixture
def project(tmp_path, monkeypatch) -> Path:
    from ducta.console.templates import TemplateGenerator, TemplateType

    monkeypatch.chdir(tmp_path)  # the server's source confinement base
    root = tmp_path / "proj"
    # Its ducta.yaml carries promotion_policy {metric: val_auc, compare_to: current_production}.
    TemplateGenerator(root).generate_project(TemplateType.ML_SCORING, "proj")
    return root


@pytest.fixture
def registry(project):
    return _registry_at(_resolve_mlops_storage(project, None, "dev", PIPELINE))


def _params(project: Path) -> dict:
    return {"source": str(project), "env": "dev", "pipeline": PIPELINE}


def _register(registry, tmp_path: Path, auc: float) -> int:
    artifact = tmp_path / f"m{auc}.pkl"
    artifact.write_bytes(pickle.dumps({"auc": auc}))
    version = registry.register_model(
        name="churn-model",
        artifact_path=str(artifact),
        artifact_type="pickle",
        framework="sklearn",
        metrics={"val_auc": auc},
    )
    return int(getattr(version, "version", version))


@pytest.fixture
def refused_retrain(registry, tmp_path):
    """v1 in Production; v2, worse, refused by the policy and left in Staging."""
    from ducta.mlrun.exceptions import PromotionGateError
    from ducta.mlrun.model_registry import PromotionPolicy

    _register(registry, tmp_path, 0.9)
    registry.promote_model("churn-model", 1, ModelStage.PRODUCTION)
    _register(registry, tmp_path, 0.7)
    with pytest.raises(PromotionGateError):
        registry.promote_model(
            "churn-model", 2, ModelStage.PRODUCTION, policy=PromotionPolicy(metric="val_auc")
        )
    return registry


class TestTheModelListSaysWhatIsInProduction:
    def test_a_refused_retrain_does_not_hide_production(self, project, refused_retrain):
        [model] = _client().get("/api/mlops/models", params=_params(project)).json()
        assert model["latest_version"] == 2 and model["stage"] == "Staging"
        assert model["production_version"] == 1
        assert model["production_metrics"] == {"val_auc": 0.9}
        assert model["latest_refusal"]["reason"].startswith("val_auc=0.7")

    def test_nothing_in_production(self, project, registry, tmp_path):
        _register(registry, tmp_path, 0.8)
        [model] = _client().get("/api/mlops/models", params=_params(project)).json()
        assert model["production_version"] is None and model["latest_refusal"] is None


class TestPromotionsAreAuditedAsTheSignedInUser:
    def test_the_user_and_reason_are_recorded(self, project, registry, tmp_path):
        _register(registry, tmp_path, 0.9)
        response = _client().post(
            "/api/mlops/models/churn-model/promote",
            params=_params(project),
            json={"version": 1, "stage": "production", "reason": "first model"},
        )
        assert response.status_code == 200, response.text
        [promote] = [e for e in registry.audit_history("churn-model") if e["event"] == "PROMOTE"]
        assert promote["user"] == "ana" and promote["reason"] == "first model"

    def test_a_forced_promotion_needs_a_reason(self, project, refused_retrain):
        client = _client()
        body = {"version": 2, "stage": "production", "force": True}
        refused = client.post(
            "/api/mlops/models/churn-model/promote", params=_params(project), json=body
        )
        assert refused.status_code == 400 and "reason" in refused.text
        forced = client.post(
            "/api/mlops/models/churn-model/promote",
            params=_params(project),
            json={**body, "reason": "hotfix: v1 leaks a feature"},
        )
        assert forced.status_code == 200, forced.text
        assert forced.json()["demoted_versions"] == [1]
        [latest] = refused_retrain.audit_history("churn-model")[:1]
        assert latest["event"] == "PROMOTE" and latest["details"]["gate_bypassed"] is True
        assert latest["reason"] == "hotfix: v1 leaks a feature"


class TestDeletionsAreAudited:
    def test_a_deletion_from_the_api(self, project, registry, tmp_path):
        _register(registry, tmp_path, 0.9)
        response = _client().delete(
            "/api/mlops/models/churn-model/versions/1", params=_params(project)
        )
        assert response.status_code == 204
        [delete] = [e for e in registry.audit_history("churn-model") if e["event"] == "DELETE"]
        assert delete["user"] == "ana" and delete["details"]["stage"] == "Staging"

    def test_a_version_in_production_is_refused(self, project, refused_retrain):
        response = _client().delete(
            "/api/mlops/models/churn-model/versions/1", params=_params(project)
        )
        assert response.status_code == 400

    def test_gc_lists_what_it_removes_and_audits_it(self, project, registry, tmp_path, monkeypatch):
        from ducta.mlrun.gc import ModelGarbageCollector

        monkeypatch.setenv("DUCTA_MLOPS_MAX_VERSIONS", "1")
        # Every version is minutes old: past no retention window by default (90 days).
        monkeypatch.setattr(ModelGarbageCollector, "_is_within_retention", lambda *a: False)
        for auc in (0.5, 0.6, 0.7):
            _register(registry, tmp_path, auc)
        client = _client()
        dry = client.post("/api/mlops/gc", params=_params(project), json={"dry_run": True}).json()
        removed = sorted(v["version"] for v in dry["versions"])
        assert removed and dry["versions_removed"] == len(removed)
        real = client.post("/api/mlops/gc", params=_params(project), json={"dry_run": False})
        assert sorted(v["version"] for v in real.json()["versions"]) == removed
        deletes = [e for e in registry.audit_history("churn-model") if e["event"] == "DELETE"]
        assert {e["reason"] for e in deletes} == {"gc"} and {e["user"] for e in deletes} == {"ana"}


class TestThePolicyAndHistoryAreReadable:
    def test_status_carries_the_policy(self, project):
        status = _client().get("/api/mlops/status", params=_params(project)).json()
        assert status["promotion_policy"]["metric"] == "val_auc"
        assert status["promotion_policy"]["compare_to"] == "current_production"

    def test_the_check_promotes_nothing(self, project, refused_retrain):
        url = "/api/mlops/models/churn-model/versions/2/promotion-check"
        check = _client().get(url, params=_params(project)).json()
        assert check["passes"] is False and "val_auc" in check["reason"]
        assert check["production_version"] == 1
        assert [s["node"] for s in check["served_by"]]  # the template's scoring node
        assert (
            refused_retrain.get_model_version("churn-model", 2).metadata.stage == ModelStage.STAGING
        )

    def test_a_better_version_would_pass(self, project, refused_retrain, tmp_path):
        _register(refused_retrain, tmp_path, 0.95)
        url = "/api/mlops/models/churn-model/versions/3/promotion-check"
        check = _client().get(url, params=_params(project)).json()
        assert check == {**check, "passes": True, "reason": None}

    def test_an_unknown_version_is_404(self, project, refused_retrain):
        url = "/api/mlops/models/churn-model/versions/9/promotion-check"
        assert _client().get(url, params=_params(project)).status_code == 404

    def test_the_history_newest_first_with_the_refusal(self, project, refused_retrain):
        history = (
            _client().get("/api/mlops/models/churn-model/history", params=_params(project)).json()
        )
        events = [(e["event"], e["version"]) for e in history]
        assert events[0] == ("PROMOTE_REFUSED", 2)
        assert ("PROMOTE", 1) in events and ("REGISTER", 1) in events

    def test_a_name_that_is_a_prefix_of_another(self, project, refused_retrain, tmp_path):
        artifact = tmp_path / "other.pkl"
        artifact.write_bytes(pickle.dumps(1))
        refused_retrain.register_model(
            name="churn-model_1",
            artifact_path=str(artifact),
            artifact_type="pickle",
            framework="sklearn",
        )
        assert {e["model"] for e in refused_retrain.audit_history("churn-model")} == {"churn-model"}
