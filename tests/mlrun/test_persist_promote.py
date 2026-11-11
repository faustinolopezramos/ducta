"""``persist_model(promote=...)``: a node promotes only through the project's policy.

The ml_scoring template promoted in node code with ``registry.promote_model`` and no
policy, so every training run that cleared its own hand-written threshold went to
production; ``settings.mlops.promotion_policy`` was never consulted.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("sklearn")

from ducta.core.ml_context import MLNodeContext  # noqa: E402
from ducta.mlrun.model_registry import ModelRegistry, ModelStage, PromotionPolicy  # noqa: E402
from ducta.mlrun.persistence import persist_model  # noqa: E402
from ducta.mlrun.storage import LocalStorageBackend  # noqa: E402


@pytest.fixture(autouse=True)
def _no_stub_modules(monkeypatch):
    # tests/gate, tests/stream and tests/setting install stub `polars`/`pyspark`
    # modules; sklearn inspects whatever is in sys.modules and fails on a stub.
    import sys

    for name in ("polars", "pyspark", "pyspark.sql"):
        module = sys.modules.get(name)
        if module is not None and getattr(module, "__file__", None) is None:
            monkeypatch.delitem(sys.modules, name)


@pytest.fixture
def registry(tmp_path):
    storage = LocalStorageBackend(base_path=str(tmp_path / "mlops"), enable_circuit_breaker=False)
    return ModelRegistry(storage=storage, registry_path="model_registry", validate_artifacts=False)


def _model():
    from sklearn.linear_model import LogisticRegression

    return LogisticRegression().fit([[0.0], [1.0], [2.0], [3.0]], [0, 0, 1, 1])


def _ctx(registry, policy=None, run_id="r1"):
    mlops = SimpleNamespace(model_registry=registry, promotion_policy=policy)
    return MLNodeContext(mlops_context=mlops, mlops_run_id=run_id)


POLICY = PromotionPolicy(metric="val_auc", compare_to="current_production")


def _stage(registry, version):
    return registry.get_model_version("churn", version).metadata.stage


class TestPromotionGoesThroughThePolicy:
    def test_the_first_model_is_promoted(self, registry):
        result = persist_model(
            _model(),
            _ctx(registry, POLICY),
            "churn",
            metrics={"val_auc": 0.8},
            promote="production",
        )
        assert result["promoted_to"] == "Production"
        assert _stage(registry, result["version"]) == ModelStage.PRODUCTION

    def test_a_worse_candidate_stays_in_staging_and_the_node_does_not_fail(self, registry):
        first = persist_model(
            _model(),
            _ctx(registry, POLICY),
            "churn",
            metrics={"val_auc": 0.9},
            promote="production",
        )
        second = persist_model(
            _model(),
            _ctx(registry, POLICY),
            "churn",
            metrics={"val_auc": 0.7},
            promote="production",
        )
        assert second["promoted_to"] is None and second["promotion_refused"]
        assert _stage(registry, first["version"]) == ModelStage.PRODUCTION
        assert _stage(registry, second["version"]) == ModelStage.STAGING

    def test_a_better_candidate_replaces_production(self, registry):
        first = persist_model(
            _model(),
            _ctx(registry, POLICY),
            "churn",
            metrics={"val_auc": 0.7},
            promote="production",
        )
        second = persist_model(
            _model(),
            _ctx(registry, POLICY),
            "churn",
            metrics={"val_auc": 0.9},
            promote="production",
        )
        assert second["promoted_to"] == "Production"
        assert _stage(registry, first["version"]) == ModelStage.ARCHIVED

    def test_an_unknown_stage_is_an_error(self, registry):
        with pytest.raises(ValueError, match="promote must be one of"):
            persist_model(_model(), _ctx(registry), "churn", promote="live")

    def test_without_promote_nothing_is_promoted(self, registry):
        result = persist_model(_model(), _ctx(registry, POLICY), "churn", metrics={"val_auc": 0.9})
        assert "promoted_to" not in result
        assert _stage(registry, result["version"]) == ModelStage.STAGING


class TestTheNodeRecordsWhatItRegistered:
    """The training certificate did not say which version the run produced."""

    def test_each_registration_is_noted_on_the_ml_context(self, registry):
        ctx = _ctx(registry, POLICY)
        persist_model(_model(), ctx, "churn", metrics={"val_auc": 0.9}, promote="production")
        [entry] = ctx.registered_models
        assert entry["name"] == "churn" and entry["version"] == 1
        assert entry["promoted_to"] == "Production" and entry["sha256"]


class TestThePolicyIsValidatedAtLoad:
    def test_a_misspelled_key_is_an_error(self):
        from pydantic import ValidationError

        from ducta.setting.project.schema import PromotionPolicySpec

        with pytest.raises(ValidationError, match="min_detla"):
            PromotionPolicySpec.model_validate({"metric": "val_auc", "min_detla": 0.01})
        with pytest.raises(ValidationError):
            PromotionPolicySpec.model_validate({"metric": "val_auc", "compare_to": "nowhere"})

    def test_the_mlops_context_carries_it(self):
        from ducta.mlrun.config import _promotion_policy_of

        context = SimpleNamespace(
            global_config={"mlops": {"promotion_policy": {"metric": "val_auc", "min_delta": 0.01}}}
        )
        policy = _promotion_policy_of(context)
        assert policy.metric == "val_auc" and policy.min_delta == 0.01
        assert _promotion_policy_of(SimpleNamespace(global_config={})) is None


def test_a_sweep_or_search_trial_is_registered_but_not_promoted(registry):
    """Each trial promoting meant every worse trial failed; the best is promoted afterwards."""
    ctx = _ctx(registry, POLICY)
    ctx.sweep_id = "sweep-1"
    result = persist_model(_model(), ctx, "churn", metrics={"val_auc": 0.9}, promote="production")
    assert result["promoted_to"] is None and result["promotion_skipped"] == "trial of sweep-1"
    assert "promotion_refused" not in result
    assert _stage(registry, result["version"]) == ModelStage.STAGING


def test_a_misspelled_stage_registers_nothing(registry):
    """It was checked after registering: the node failed and left a version behind."""
    with pytest.raises(ValueError, match="promote must be one of"):
        persist_model(_model(), _ctx(registry), "churn", promote="live")
    from ducta.mlrun.exceptions import ModelNotFoundError

    with pytest.raises(ModelNotFoundError):
        registry.list_model_versions("churn")


class TestOneReaderOfThePolicy:
    def test_none_when_there_is_none(self):
        from ducta.mlrun.model_registry import PromotionPolicy

        assert PromotionPolicy.from_settings(None) is None
        assert PromotionPolicy.from_settings({"mlops_path": "m"}) is None

    @pytest.mark.parametrize("raw", ["val_auc", {"min_delta": 0.1}, {"metric": ""}])
    def test_an_unusable_one_is_an_error(self, raw):
        from ducta.mlrun.model_registry import PromotionPolicy

        with pytest.raises(ValueError, match="promotion_policy"):
            PromotionPolicy.from_settings({"promotion_policy": raw})

    def test_a_valid_one(self):
        from ducta.mlrun.model_registry import PromotionPolicy

        policy = PromotionPolicy.from_settings({"promotion_policy": {"metric": "val_auc"}})
        assert policy is not None and policy.metric == "val_auc"
