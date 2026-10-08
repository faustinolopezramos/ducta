"""The built-in scorer on a real Spark DataFrame."""

from __future__ import annotations

import sys

import pandas as pd
import pytest

from ducta.mlrun.serving import ResolvedModel, ServingModel, predict
from ducta.setting.project_schema import ModelRef

sklearn = pytest.importorskip("sklearn")


@pytest.fixture(autouse=True)
def _no_stub_modules(monkeypatch):
    # tests/gate, tests/stream and tests/setting install stub `polars`/`pyspark`
    # modules when the real ones are not installed or not yet imported; sklearn
    # and MLflow inspect whatever is in sys.modules and fail on a stub.
    for name in ("polars", "pyspark", "pyspark.sql"):
        module = sys.modules.get(name)
        if module is not None and getattr(module, "__file__", None) is None:
            monkeypatch.delitem(sys.modules, name)


def _served(model, **ref):
    return ServingModel(
        ref=ModelRef.model_validate({"name": "m", "version": 1, "features": ["x"], **ref}),
        resolved=ResolvedModel(source="ducta", name="m", version=1, uri="u", framework="sklearn"),
        model=model,
    )


@pytest.fixture
def frame():
    return pd.DataFrame({"id": list(range(20)), "x": [float(i) for i in range(20)]})


@pytest.fixture
def classifier(frame):
    from sklearn.linear_model import LogisticRegression

    return LogisticRegression().fit(frame[["x"]], (frame["x"] >= 10).astype(int))


def test_predict_keeps_every_column_and_types_the_prediction(spark, frame, classifier):
    df = spark.createDataFrame(frame.to_dict("records"))
    out = predict(df, ml_context={"model_ref": _served(classifier)})

    assert out.columns == ["id", "x", "prediction"]
    assert dict(out.dtypes)["prediction"] == "bigint"
    # collect(), not toPandas(): an Arrow-enabled session cannot run Arrow on Java 21.
    assert [r.prediction for r in out.orderBy("id").collect()] == [0] * 10 + [1] * 10


def test_scores_are_doubles(spark, frame, classifier):
    df = spark.createDataFrame(frame.to_dict("records"))
    served = _served(classifier, method="predict_proba", output_col="score")
    out = predict(df, ml_context={"model_ref": served})

    assert dict(out.dtypes)["score"] == "double"
    assert out.filter("score < 0 or score > 1").count() == 0


def test_an_unsupervised_score(spark, frame):
    from sklearn.ensemble import IsolationForest

    model = IsolationForest(random_state=0).fit(frame[["x"]])
    out = predict(
        spark.createDataFrame(frame.to_dict("records")),
        ml_context={"model_ref": _served(model, method="score_samples", output_col="normality")},
    )
    assert out.select("normality").na.drop().count() == 20


def test_a_spark_ml_pipeline_from_the_registry(spark, tmp_path):
    from pyspark.ml import Pipeline
    from pyspark.ml.classification import LogisticRegression as SparkLR
    from pyspark.ml.feature import VectorAssembler

    from ducta.mlrun.model_registry import ModelRegistry, ModelStage
    from ducta.mlrun.serving import prepare_model
    from ducta.mlrun.storage import LocalStorageBackend

    df = spark.createDataFrame([(float(i), int(i >= 10)) for i in range(20)], "x DOUBLE, y INT")
    model = Pipeline(
        stages=[VectorAssembler(inputCols=["x"], outputCol="features"), SparkLR(labelCol="y")]
    ).fit(df)
    saved = tmp_path / "spark_model"
    model.save(str(saved))

    storage = LocalStorageBackend(base_path=str(tmp_path / "mlops"), enable_circuit_breaker=False)
    registry = ModelRegistry(storage=storage, registry_path="model_registry")
    mv = registry.register_model(
        name="spark_clf",
        artifact_path=str(saved),
        artifact_type="spark-mllib",
        framework="spark-mllib",
    )
    registry.promote_model("spark_clf", mv.version, ModelStage.PRODUCTION)

    ref = ModelRef.model_validate(
        {"name": "spark_clf", "stage": "production", "method": "predict_proba", "output_col": "p"}
    )
    served = prepare_model(ref, registry=registry, mlflow_client=None, workdir=tmp_path / "w")
    out = predict(df, ml_context={"model_ref": served})

    assert out.columns == ["x", "y", "p"]
    scores = [r.p for r in out.orderBy("x").collect()]
    assert scores[0] < 0.5 < scores[-1]
    assert served.evidence()["artifact_sha256"] == mv.artifact_sha256
