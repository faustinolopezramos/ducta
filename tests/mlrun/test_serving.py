"""Serving: resolving, verifying, loading and applying a registered model."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

from ducta.mlrun.model_registry import ModelRegistry, ModelStage
from ducta.mlrun.serving import (
    ModelCache,
    ServingError,
    artifact_digest,
    predict,
    prepare_model,
    resolve_model,
    score,
)
from ducta.mlrun.storage import LocalStorageBackend
from ducta.setting.project_schema import ModelRef

sklearn = pytest.importorskip("sklearn")
joblib = pytest.importorskip("joblib")


@pytest.fixture(autouse=True)
def _no_stub_modules(monkeypatch):
    # tests/gate, tests/stream and tests/setting install stub `polars`/`pyspark`
    # modules when the real ones are not installed or not yet imported; sklearn
    # and MLflow inspect whatever is in sys.modules and fail on a stub.
    for name in ("polars", "pyspark", "pyspark.sql"):
        module = sys.modules.get(name)
        if module is not None and getattr(module, "__file__", None) is None:
            monkeypatch.delitem(sys.modules, name)


def _frame(n=40):
    return pd.DataFrame(
        {"x": [float(i) for i in range(n)], "y": [int(i >= n // 2) for i in range(n)]}
    )


@pytest.fixture
def registry(tmp_path):
    storage = LocalStorageBackend(base_path=str(tmp_path / "mlops"), enable_circuit_breaker=False)
    return ModelRegistry(storage=storage, registry_path="model_registry", validate_artifacts=False)


def _register(registry, tmp_path, *, c=1.0, name="clf", input_schema=None):
    from sklearn.linear_model import LogisticRegression

    df = _frame()
    model = LogisticRegression(C=c).fit(df[["x"]], df["y"])
    path = tmp_path / f"{name}-{c}.joblib"
    joblib.dump(model, path)
    return registry.register_model(
        name=name,
        artifact_path=str(path),
        artifact_type="sklearn",
        framework="sklearn",
        input_schema=input_schema if input_schema is not None else {"x": "double"},
        trust_artifact_source=True,
    )


def _ref(**kw):
    base = {"name": "clf", "stage": "production", "trust_artifact": True}
    return ModelRef.model_validate({**base, **kw})


class TestResolution:
    def test_a_stage_is_pinned_to_the_version_in_it(self, registry, tmp_path):
        _register(registry, tmp_path, c=1.0)
        v2 = _register(registry, tmp_path, c=2.0)
        registry.promote_model("clf", v2.version, ModelStage.PRODUCTION)

        resolved = resolve_model(_ref(), registry=registry)

        assert (resolved.version, resolved.stage_at_resolution) == (2, "production")
        assert resolved.framework == "sklearn"

    def test_an_exact_version(self, registry, tmp_path):
        _register(registry, tmp_path, c=1.0)
        _register(registry, tmp_path, c=2.0)
        resolved = resolve_model(_ref(stage=None, version=1), registry=registry)
        assert resolved.version == 1

    def test_an_empty_stage_says_what_to_do(self, registry, tmp_path):
        _register(registry, tmp_path)
        with pytest.raises(ServingError, match="no stage production.*promote"):
            resolve_model(_ref(), registry=registry)

    def test_no_registry(self):
        with pytest.raises(ServingError, match="no model registry"):
            resolve_model(_ref(), registry=None)


class TestVerificationAndLoading:
    def test_registration_records_the_artifact_hash(self, registry, tmp_path):
        mv = _register(registry, tmp_path)
        assert mv.artifact_sha256 == artifact_digest(tmp_path / "clf-1.0.joblib")
        reread = registry.get_model_version("clf", mv.version)
        assert reread.artifact_sha256 == mv.artifact_sha256

    def test_a_pickle_is_not_loaded_without_trust(self, registry, tmp_path):
        mv = _register(registry, tmp_path)
        registry.promote_model("clf", mv.version, ModelStage.PRODUCTION)
        with pytest.raises(ServingError, match="trust_artifact: true"):
            prepare_model(
                _ref(trust_artifact=False), registry=registry, mlflow_client=None, workdir=tmp_path
            )

    def test_an_artifact_changed_after_registration_is_refused(self, registry, tmp_path):
        mv = _register(registry, tmp_path)
        registry.promote_model("clf", mv.version, ModelStage.PRODUCTION)
        stored = Path(registry.storage.base_path) / mv.artifact_uri
        stored.write_bytes(stored.read_bytes() + b"tampered")
        with pytest.raises(ServingError, match="does not match the one recorded"):
            prepare_model(_ref(), registry=registry, mlflow_client=None, workdir=tmp_path)

    def test_evidence_names_the_exact_model(self, registry, tmp_path):
        mv = _register(registry, tmp_path)
        registry.promote_model("clf", mv.version, ModelStage.PRODUCTION)
        served = prepare_model(_ref(), registry=registry, mlflow_client=None, workdir=tmp_path)
        assert served.evidence() == {
            "source": "ducta",
            "name": "clf",
            "version": 1,
            "stage_at_resolution": "production",
            "uri": mv.artifact_uri,
            "framework": "sklearn",
            "artifact_sha256": mv.artifact_sha256,
            "hash_source": "registry",
        }


class TestTheCachePinsOneVersionPerRun:
    def test_a_promotion_mid_run_does_not_change_the_model(self, registry, tmp_path):
        v1 = _register(registry, tmp_path, c=1.0)
        registry.promote_model("clf", v1.version, ModelStage.PRODUCTION)
        cache = ModelCache(lambda: registry, lambda: None)

        first = cache.get(_ref().model_dump())
        v2 = _register(registry, tmp_path, c=2.0)
        registry.promote_model("clf", v2.version, ModelStage.PRODUCTION)
        second = cache.get(_ref().model_dump())

        assert first.resolved.version == second.resolved.version == 1

    def test_other_scoring_options_share_the_loaded_model(self, registry, tmp_path):
        v1 = _register(registry, tmp_path)
        registry.promote_model("clf", v1.version, ModelStage.PRODUCTION)
        cache = ModelCache(lambda: registry, lambda: None)
        a = cache.get(_ref())
        b = cache.get(_ref(output_col="p", method="predict_proba"))
        assert a.model is b.model and b.ref.output_col == "p"


class TestScoring:
    @pytest.fixture
    def served(self, registry, tmp_path):
        mv = _register(registry, tmp_path)
        registry.promote_model("clf", mv.version, ModelStage.PRODUCTION)

        def _make(**kw):
            return prepare_model(
                _ref(**kw), registry=registry, mlflow_client=None, workdir=tmp_path
            )

        return _make

    def test_predict_adds_the_output_column(self, served):
        out = score(_frame(), served())
        assert list(out.columns) == ["x", "y", "prediction"]
        assert out["prediction"].tolist() == _frame()["y"].tolist()

    def test_predict_proba_keeps_the_positive_class(self, served):
        out = score(_frame(), served(method="predict_proba", output_col="p"))
        assert out["p"].between(0, 1).all()
        assert out["p"].iloc[-1] > 0.5 > out["p"].iloc[0]

    def test_a_missing_feature_column_is_named(self, served):
        with pytest.raises(ServingError, match=r"missing the model's feature columns: \['x'\]"):
            score(pd.DataFrame({"z": [1.0]}), served())

    def test_a_method_the_model_lacks_lists_the_ones_it_has(self, served):
        with pytest.raises(ServingError, match="no score_samples.*predict, predict_proba"):
            score(_frame(), served(method="score_samples"))

    def test_features_default_to_the_registered_input_schema(self, registry, tmp_path):
        mv = _register(registry, tmp_path, name="noschema", input_schema={})
        registry.promote_model("noschema", mv.version, ModelStage.PRODUCTION)
        served = prepare_model(
            _ref(name="noschema"), registry=registry, mlflow_client=None, workdir=tmp_path
        )
        with pytest.raises(ServingError, match="list its columns in model.features"):
            score(_frame(), served)

    def test_the_builtin_function_reads_one_input(self, served):
        ctx = {"model_ref": served()}
        assert "prediction" in predict(_frame(), ml_context=ctx).columns
        with pytest.raises(ServingError, match="exactly one input, got 2"):
            predict(_frame(), _frame(), ml_context=ctx)


class TestMLflowSource:
    def test_an_alias_is_pinned_and_scored(self, tmp_path, monkeypatch):
        mlflow = pytest.importorskip("mlflow")
        from sklearn.linear_model import LogisticRegression

        from ducta.mlrun.serving import mlflow_client_from_context

        # With a database store MLflow puts artifacts under the working directory.
        monkeypatch.chdir(tmp_path)
        uri = f"sqlite:///{tmp_path / 'mlflow.db'}"

        class _Ctx:
            global_config = {"mlflow": {"tracking_uri": uri}}

        client = mlflow_client_from_context(_Ctx())
        df = _frame()
        with mlflow.start_run():
            mlflow.sklearn.log_model(
                LogisticRegression().fit(df[["x"]], df["y"]),
                name="model",
                registered_model_name="clf",
                input_example=df[["x"]].head(2),
            )
        client.set_registered_model_alias("clf", "champion", "1")

        ref = ModelRef.model_validate(
            {"source": "mlflow", "uri": "models:/clf@champion", "features": ["x"]}
        )
        served = prepare_model(ref, registry=None, mlflow_client=client, workdir=tmp_path / "w")

        assert served.evidence()["uri"] == "models:/clf/1"
        assert served.evidence()["stage_at_resolution"] == "@champion"
        assert served.artifact_sha256.startswith("sha256:")
        assert score(df, served)["prediction"].tolist() == df["y"].tolist()

    def test_a_stage_name_in_the_uri_is_explained(self):
        class _Client:
            pass

        ref = ModelRef.model_validate({"source": "mlflow", "uri": "models:/clf/Production"})
        with pytest.raises(ServingError, match="no longer resolves stages"):
            resolve_model(ref, mlflow_client=_Client())


class TestWhenArrowScoringIsUsed:
    """mapInPandas needs Arrow; Spark 3.x's Arrow cannot run on Java 21+."""

    def _df(self, java, spark_version):
        from types import SimpleNamespace

        if java is None:  # Spark Connect: no local JVM handle

            class _NoJVM:
                @property
                def _jvm(self):
                    raise AttributeError("no JVM")

            sc = _NoJVM()
        else:
            system = SimpleNamespace(getProperty=lambda _key: java)
            sc = SimpleNamespace(
                _jvm=SimpleNamespace(java=SimpleNamespace(lang=SimpleNamespace(System=system)))
            )
        return SimpleNamespace(sparkSession=SimpleNamespace(sparkContext=sc, version=spark_version))

    @pytest.mark.parametrize(
        "java, spark, arrow",
        [
            ("1.8", "3.5.1", True),
            ("17", "3.5.1", True),
            ("21", "3.5.9", False),
            ("21", "4.0.0", True),
            (None, "3.5.1", True),
        ],
    )
    def test_arrow_only_where_it_runs(self, java, spark, arrow):
        from ducta.mlrun.serving import _arrow_udfs_work

        assert _arrow_udfs_work(self._df(java, spark)) is arrow


def test_a_joblib_sklearn_model_registers_with_validation(tmp_path):
    """Regression: the sklearn validator used pickle.load, which cannot read joblib."""
    from sklearn.linear_model import LogisticRegression

    storage = LocalStorageBackend(base_path=str(tmp_path / "mlops"), enable_circuit_breaker=False)
    validating = ModelRegistry(storage=storage, registry_path="model_registry")
    path = tmp_path / "m.joblib"
    joblib.dump(LogisticRegression().fit(_frame()[["x"]], _frame()["y"]), path)

    mv = validating.register_model(
        name="clf",
        artifact_path=str(path),
        artifact_type="sklearn",
        framework="sklearn",
        trust_artifact_source=True,
    )
    assert mv.version == 1
