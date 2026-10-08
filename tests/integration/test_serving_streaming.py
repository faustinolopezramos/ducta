"""A streaming node with ``model:``: what its transform receives, and the built-in scorer."""

from __future__ import annotations

import sys
import threading
from unittest.mock import MagicMock

import pandas as pd
import pytest

from ducta.mlrun import serving as serving_mod
from ducta.mlrun.serving import ResolvedModel, ServingError, ServingModel
from ducta.setting.project_schema import ModelRef
from ducta.stream.query_manager import StreamingQueryManager

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


def _served(model=None, **ref):
    return ServingModel(
        ref=ModelRef.model_validate({"name": "m", "version": 2, "features": ["value"], **ref}),
        resolved=ResolvedModel(source="ducta", name="m", version=2, uri="u", framework="sklearn"),
        model=model if model is not None else object(),
    )


def _manager():
    manager = StreamingQueryManager.__new__(StreamingQueryManager)
    manager._active_queries = {}
    manager._active_queries_lock = threading.Lock()
    return manager


class TestTheTransformGetsTheModel:
    def test_with_params(self):
        seen = {}

        def transform(df, params, ml_context=None):
            seen.update(params=params, ctx=ml_context)
            return df

        served = _served()
        ctx = {"model": served.model, "model_ref": served}
        _manager()._call_transform_function(transform, "df", {"k": 1}, ctx)
        assert seen == {"params": {"k": 1}, "ctx": ctx}

    def test_keyword_only(self):
        def transform(df, *, ml_context):
            return ml_context

        assert _manager()._call_transform_function(transform, "df", None, {"m": 1}) == {"m": 1}

    def test_a_transform_without_the_parameter_still_runs(self):
        assert _manager()._call_transform_function(lambda df: df, "df", None, {"m": 1}) == "df"

    def test_the_context_carries_the_model(self, monkeypatch):
        seen = {}
        manager = _manager()

        def transform(df, ml_context=None):
            seen["ctx"] = ml_context
            return df

        monkeypatch.setattr(manager, "_get_transform_function", lambda cfg: transform)
        monkeypatch.setattr("ducta.stream.query_manager.looks_like_dataframe", lambda df: True)
        served = _served()
        manager._apply_transformations(MagicMock(), {"function": {"key": "t"}}, served)

        assert seen["ctx"].model is served.model and seen["ctx"].model_ref is served


class TestWithoutATransform:
    def test_the_builtin_scorer_runs(self, monkeypatch):
        monkeypatch.setattr(serving_mod, "score", lambda df, s: ("scored", df, s))
        served = _served()
        assert _manager()._apply_transformations("df", {}, served) == ("scored", "df", served)

    def test_without_a_model_the_input_passes_through(self):
        assert _manager()._apply_transformations("df", {}) == "df"


def test_the_status_names_each_querys_model():
    manager = _manager()
    evidence = _served().evidence()
    manager._active_queries = {
        "p:e1:score": {"execution_id": "e1", "node_name": "score", "model": evidence},
        "p:e1:raw": {"execution_id": "e1", "node_name": "raw", "model": None},
        "p:e2:score": {"execution_id": "e2", "node_name": "score", "model": evidence},
    }
    assert manager.served_models("e1") == {"score": evidence}


def test_scoring_a_real_stream(spark, tmp_path):
    """mapInPandas on a stream where Arrow runs; a clear error where it cannot."""
    from sklearn.linear_model import LogisticRegression

    train = pd.DataFrame({"value": [float(i) for i in range(20)]})
    model = LogisticRegression().fit(train, (train["value"] >= 10).astype(int))
    stream = spark.readStream.format("rate").option("rowsPerSecond", 5).load()
    served = _served(model, method="predict", output_type="long")

    if not serving_mod._arrow_udfs_work(stream):
        with pytest.raises(ServingError, match="needs Arrow"):
            serving_mod.score(stream, served)
        return

    scored = serving_mod.score(stream.withColumn("value", stream["value"].cast("double")), served)
    assert scored.isStreaming
    query = (
        scored.writeStream.format("memory")
        .queryName("serving_test")
        .option("checkpointLocation", str(tmp_path / "ckpt"))
        .trigger(availableNow=True)
        .start()
    )
    query.awaitTermination(60)
    assert dict(spark.table("serving_test").dtypes)["prediction"] == "bigint"
