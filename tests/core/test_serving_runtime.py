"""A serving node in a real run: the model it receives and the evidence it leaves."""

from __future__ import annotations

import json
import sys

import pandas as pd
import pytest

from ducta.core.ledger import ledger_for
from ducta.mlrun.model_registry import ModelRegistry, ModelStage
from ducta.mlrun.storage import LocalStorageBackend
from tests.core import fakes
from tests.core.fakes import (
    FakeContext,
    FakeFrame,
    FakeFunctionLoader,
    FakeInputLoader,
    FakeOutputManager,
    node,
)

pytest.importorskip("sklearn")
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


MODEL = {"name": "clf", "stage": "production", "trust_artifact": True}


@pytest.fixture(autouse=True)
def _clean_fakes():
    fakes.reset()
    yield
    fakes.reset()


@pytest.fixture
def registry(tmp_path):
    storage = LocalStorageBackend(base_path=str(tmp_path / "mlops"), enable_circuit_breaker=False)
    return ModelRegistry(storage=storage, registry_path="model_registry", validate_artifacts=False)


def _register_and_promote(registry, tmp_path, c):
    from sklearn.linear_model import LogisticRegression

    df = pd.DataFrame({"x": [float(i) for i in range(20)], "y": [int(i >= 10) for i in range(20)]})
    path = tmp_path / f"m{c}.joblib"
    joblib.dump(LogisticRegression(C=c).fit(df[["x"]], df["y"]), path)
    mv = registry.register_model(
        name="clf",
        artifact_path=str(path),
        artifact_type="sklearn",
        framework="sklearn",
        input_schema={"x": "double"},
        trust_artifact_source=True,
    )
    registry.promote_model("clf", mv.version, ModelStage.PRODUCTION)
    return mv


def _engine(registry, nodes, **settings):
    from ducta.core.executors.facade import PipelineExecutor

    datasets = {"d": FakeFrame([{"x": 1.0}, {"x": 15.0}])}
    pipelines = {"p": {"name": "p", "nodes": list(nodes), "type": "ml", "requires_dates": False}}
    context = FakeContext(
        nodes_config=nodes,
        pipelines_config=pipelines,
        global_config={"ml_default_sanity_checks": False, **settings},
    )
    engine = PipelineExecutor(context)
    batch = engine.batch_executor
    batch.input_loader = FakeInputLoader(datasets)
    batch.output_manager = FakeOutputManager(datasets)
    batch.node_executor.input_loader = batch.input_loader
    batch.node_executor.output_manager = batch.output_manager
    batch.node_executor._output_writer.output_manager = batch.output_manager
    batch.node_executor._function_loader = FakeFunctionLoader()
    batch.node_executor._coordinator._ml_builder = batch.node_executor._ml_builder
    batch.node_executor._ml_builder._model_registry = lambda: registry
    return engine, context


def _scorer(seen):
    def fn(frame, ml_context=None):
        seen.append(ml_context)
        df = pd.DataFrame(frame.rows)
        df["prediction"] = ml_context.model.predict(df[ml_context.model_ref.features])
        return FakeFrame(df.to_dict("records"))

    return fn


def _serving_node(name="score", *, seen):
    fn = fakes.register(name, _scorer(seen))
    return {name: node(fn, inputs=["d"], outputs=[f"o_{name}"], ml_stage="serving", model=MODEL)}


def _model_record(context, name="score"):
    record = next(r for r in ledger_for(context).node_details if r["name"] == name)
    return (record.get("ml") or {}).get("model"), record


class TestTheNodeGetsItsModel:
    def test_ml_context_carries_the_loaded_model_and_which_one_it_is(self, registry, tmp_path):
        mv = _register_and_promote(registry, tmp_path, 1.0)
        seen: list = []
        engine, context = _engine(registry, _serving_node(seen=seen))

        result = engine.run_pipeline("p")

        assert result.ok, result.errors
        ctx = seen[0]
        assert ctx.model_ref.resolved.version == mv.version
        assert [r["prediction"] for r in context_rows(engine)] == [0, 1]

    def test_two_nodes_naming_the_same_stage_get_one_version(self, registry, tmp_path):
        _register_and_promote(registry, tmp_path, 1.0)
        seen: list = []
        nodes = {**_serving_node("a", seen=seen), **_serving_node("b", seen=seen)}
        engine, _ = _engine(registry, nodes)
        engine.run_pipeline("p")
        assert seen[0].model is seen[1].model

    def test_each_run_resolves_the_stage_afresh(self, registry, tmp_path):
        _register_and_promote(registry, tmp_path, 1.0)
        seen: list = []
        engine, _ = _engine(registry, _serving_node(seen=seen))
        engine.run_pipeline("p")
        _register_and_promote(registry, tmp_path, 2.0)
        engine.run_pipeline("p")
        assert [c.model_ref.resolved.version for c in seen] == [1, 2]

    def test_a_missing_model_fails_the_node_and_says_why(self, registry, tmp_path):
        from ducta.core.errors import PipelineExecutionError

        seen: list = []
        engine, context = _engine(registry, _serving_node(seen=seen))
        with pytest.raises(PipelineExecutionError, match="model 'clf' has no stage production"):
            engine.run_pipeline("p")
        assert not seen
        _, record = _model_record(context)
        assert record["status"] == "failed"


class TestTheEvidence:
    def test_the_certificate_names_the_exact_model(self, registry, tmp_path):
        mv = _register_and_promote(registry, tmp_path, 1.0)
        seen: list = []
        engine, context = _engine(
            registry,
            _serving_node(seen=seen),
            evidence_level="record",
            run_certificate_dir=str(tmp_path / "runs"),
        )
        result = engine.run_pipeline("p")

        cert = json.loads(open(result.certificate_path, encoding="utf-8").read())
        served = cert["nodes"][0]["ml"]["model"]
        assert served == {
            "source": "ducta",
            "name": "clf",
            "version": mv.version,
            "stage_at_resolution": "production",
            "uri": mv.artifact_uri,
            "framework": "sklearn",
            "artifact_sha256": mv.artifact_sha256,
            "hash_source": "registry",
        }
        assert cert["schema_version"] == "1.6"

    def test_diff_reports_a_model_change(self, registry, tmp_path):
        from ducta.core.certificate import diff_certificates

        _register_and_promote(registry, tmp_path, 1.0)
        seen: list = []
        engine, _ = _engine(
            registry,
            _serving_node(seen=seen),
            evidence_level="record",
            run_certificate_dir=str(tmp_path / "runs"),
        )
        first = engine.run_pipeline("p").certificate_path
        _register_and_promote(registry, tmp_path, 2.0)
        second = engine.run_pipeline("p").certificate_path

        load = lambda p: json.loads(open(p, encoding="utf-8").read())  # noqa: E731
        diff = diff_certificates(load(first), load(second))

        assert diff["models"] == [
            {"node": "score", "model_a": "clf v1", "model_b": "clf v2", "match": False}
        ]
        assert not diff["models_match"] and not diff["identical"]


def context_rows(engine):
    """Rows the serving node wrote to its output."""
    return engine.batch_executor.output_manager.datasets["o_score"].rows


class TestPreflight:
    """`ducta config validate` checks a node's model before any data is read."""

    def _check(self, registry, monkeypatch, model):
        from types import SimpleNamespace

        from ducta.core import preflight
        from ducta.mlrun import config as mlrun_config

        monkeypatch.setattr(
            mlrun_config.MLOpsContext,
            "from_context",
            classmethod(lambda cls, ctx, **kw: SimpleNamespace(model_registry=registry)),
        )
        report = preflight.PreflightReport(pipeline_name="p")
        preflight._check_serving_models(report, object(), {"score": {"model": model}})
        return report

    def test_a_resolvable_model_passes(self, registry, tmp_path, monkeypatch):
        _register_and_promote(registry, tmp_path, 1.0)
        report = self._check(registry, monkeypatch, MODEL)
        assert report.ok and not report.warnings

    def test_a_model_not_registered_yet_is_a_warning(self, registry, monkeypatch):
        report = self._check(registry, monkeypatch, MODEL)
        assert report.ok
        assert "has no stage production" in report.warnings[0]

    def test_a_malformed_model_is_an_error(self, registry, monkeypatch):
        report = self._check(registry, monkeypatch, {"name": "clf", "stge": "production"})
        assert not report.ok
        assert "Node 'score': invalid model" in report.errors[0]
