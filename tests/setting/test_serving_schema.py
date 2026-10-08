"""``model:`` on a node — what the pipeline file accepts, and what reaches the engine."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ducta.setting.project_decompile import _decompile_node
from ducta.setting.project_loader import compile_project, validate_project
from ducta.setting.project_schema import BUILTIN_SCORER, ModelRef, TransformNode


def _node(**kw):
    return TransformNode.model_validate({"inputs": ["d"], "outputs": ["o"], **kw})


class TestModelRef:
    def test_a_ducta_model_by_stage(self):
        ref = ModelRef.model_validate({"name": "churn", "stage": "Production"})
        assert (ref.source, ref.stage, ref.version) == ("ducta", "production", None)
        assert (ref.output_col, ref.method, ref.trust_artifact) == ("prediction", "predict", False)

    @pytest.mark.parametrize(
        "raw, message",
        [
            ({"name": "m"}, "exactly one of stage"),
            ({"name": "m", "stage": "production", "version": 2}, "exactly one of stage"),
            ({"stage": "production"}, "name is required"),
            ({"name": "m", "stage": "prodution"}, "did you mean 'production'"),
            ({"name": "m", "version": 0}, "greater than or equal to 1"),
            ({"name": "m", "stage": "production", "uri": "models:/m/1"}, "uri applies to"),
            ({"source": "mlflow", "uri": "runs:/abc/model"}, "models:/<name>@<alias>"),
            ({"source": "mlflow", "uri": "models:/m/1", "stage": "production"}, "apply to source"),
            ({"name": "m", "stage": "production", "method": "transform"}, "method"),
            ({"name": "m", "stage": "production", "stge": "x"}, "stge"),
        ],
    )
    def test_mistakes_are_named(self, raw, message):
        with pytest.raises(ValidationError, match=message):
            ModelRef.model_validate(raw)

    def test_an_mlflow_model_by_alias(self):
        ref = ModelRef.model_validate({"source": "mlflow", "uri": "models:/churn@champion"})
        assert ref.uri == "models:/churn@champion"


class TestServingNode:
    MODEL = {"name": "churn", "stage": "production"}

    def test_serving_needs_a_model(self):
        with pytest.raises(ValidationError, match="ml_stage: serving needs model"):
            _node(run="m:f", ml_stage="serving")

    def test_a_model_needs_a_stage_that_scores(self):
        with pytest.raises(ValidationError, match="serving or evaluation, not 'training'"):
            _node(run="m:f", ml_stage="training", model=self.MODEL)
        with pytest.raises(ValidationError, match="set ml_stage"):
            _node(run="m:f", model=self.MODEL)

    def test_only_serving_may_omit_run(self):
        assert _node(ml_stage="serving", model=self.MODEL).run is None
        with pytest.raises(ValidationError, match="run is required"):
            _node()
        with pytest.raises(ValidationError, match="run is required"):
            _node(ml_stage="evaluation", model=self.MODEL)


class TestCompiled:
    def _compile(self, tmp_path, node_yaml):
        (tmp_path / "pipelines").mkdir()
        (tmp_path / "ducta.yaml").write_text(
            "version: 2\nproject: p\npaths: {input: d, output: o}\n"
        )
        (tmp_path / "catalog.yaml").write_text(
            "raw: {format: parquet, path: raw.parquet}\nml.p.scores: {format: parquet}\n"
        )
        (tmp_path / "pipelines" / "score.yaml").write_text(
            "type: ml\nrequires_dates: false\nnodes:\n  score:\n" + node_yaml
        )
        return compile_project(validate_project(tmp_path, None))["nodes_config"]["score"]

    def test_a_node_without_run_runs_the_builtin_scorer(self, tmp_path):
        node = self._compile(
            tmp_path,
            "    ml_stage: serving\n"
            "    model: {name: churn, stage: production, features: [x], trust_artifact: true}\n"
            "    inputs: [raw]\n    outputs: [ml.p.scores]\n",
        )
        assert f"{node['module']}:{node['function']}" == BUILTIN_SCORER
        assert node["model"] == {
            "name": "churn",
            "stage": "production",
            "features": ["x"],
            "trust_artifact": True,
        }

    def test_decompiling_keeps_the_model(self, tmp_path):
        node = self._compile(
            tmp_path,
            "    run: score:fn\n    ml_stage: serving\n"
            "    model: {name: churn, version: 3}\n"
            "    inputs: [raw]\n    outputs: [ml.p.scores]\n",
        )
        problems: list = []
        out = _decompile_node("score", {**node, "type": "ml"}, {}, problems)
        assert not problems
        assert out["model"] == {"name": "churn", "version": 3}
        TransformNode.model_validate(out)


def test_a_stream_node_carries_its_model_to_the_engine(tmp_path):
    (tmp_path / "pipelines").mkdir()
    (tmp_path / "ducta.yaml").write_text("version: 2\nproject: p\npaths: {input: d, output: o}\n")
    (tmp_path / "catalog.yaml").write_text("{}\n")
    (tmp_path / "pipelines" / "live.yaml").write_text(
        "type: streaming\nrequires_dates: false\nnodes:\n  score:\n    kind: stream\n"
        "    stream:\n"
        "      input: {format: rate}\n"
        "      output: {format: memory}\n"
        "      model: {name: churn, stage: production, output_type: long}\n"
    )
    node = compile_project(validate_project(tmp_path, None))["nodes_config"]["score"]
    assert node["model"] == {"name": "churn", "stage": "production", "output_type": "long"}
