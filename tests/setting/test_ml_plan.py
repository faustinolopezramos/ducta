"""`ducta config show --ml`: what each ML node will be given, before anything runs."""

from __future__ import annotations

import textwrap

import pytest

from ducta.setting.project_inspect import ml_plan
from ducta.setting.project_loader import ProjectConfigError

PROJECT = "version: 2\nproject: p\npaths: {input: d, output: o}\n"
CATALOG = "d: {format: csv, path: d.csv}\nml.x.f: {format: parquet}\nml.x.m: {format: parquet}\n"


def _root(tmp_path, pipeline, settings=""):
    root = tmp_path / "p"
    (root / "pipelines").mkdir(parents=True)
    (root / "ducta.yaml").write_text(PROJECT + settings)
    (root / "catalog.yaml").write_text(CATALOG)
    (root / "pipelines" / "churn.yaml").write_text(textwrap.dedent(pipeline))
    return root


ML = """\
type: ml
requires_dates: false
model_version: "1.0"
hyperparams: {trees: 50, depth: 2}
split: {method: random, test_size: 0.2, seed: 1}
nodes:
  features:
    run: src.m:f
    inputs: [d]
    outputs: [ml.x.f]
  train:
    run: src.m:t
    ml_stage: training
    hyperparams: {depth: 6}
    inputs: [ml.x.f]
    outputs: [ml.x.m]
"""


def test_each_node_shows_its_split_where_it_came_from_and_whether_it_must_apply_it(tmp_path):
    plan = ml_plan(_root(tmp_path, ML), None)["churn"]
    assert plan["nodes"]["train"]["split_from"] == "pipeline"
    assert plan["nodes"]["train"]["must_apply_split"] is True
    assert plan["nodes"]["features"]["must_apply_split"] is False
    assert plan["nodes"]["features"]["ml_stage"] == "none"


def test_hyperparams_are_shown_merged_pipeline_then_node(tmp_path):
    assert ml_plan(_root(tmp_path, ML), None)["churn"]["nodes"]["train"]["hyperparams"] == {
        "trees": 50,
        "depth": 6,
    }


def test_a_node_split_and_model_version_win_over_the_pipeline(tmp_path):
    pipeline = ML.replace(
        "    ml_stage: training\n",
        "    ml_stage: training\n    model_version: '2.0'\n"
        "    split: {method: stratified, test_size: 0.3, stratify_col: y}\n",
    )
    node = ml_plan(_root(tmp_path, pipeline), None)["churn"]["nodes"]["train"]
    assert node["split_from"] == "node" and node["split"]["method"] == "stratified"
    assert node["model_version"] == "2.0"


def test_the_enforcement_in_force_is_shown(tmp_path):
    root = _root(tmp_path, ML, settings="settings: {split_enforcement: warn}\n")
    assert ml_plan(root, None)["churn"]["split_enforcement"] == "warn"


def test_a_batch_pipeline_without_ml_is_left_out(tmp_path):
    batch = "requires_dates: false\nnodes:\n  n:\n    run: src.m:f\n    inputs: [d]\n    outputs: [ml.x.f]\n"
    assert ml_plan(_root(tmp_path, batch), None) == {}


def test_an_unknown_pipeline_is_an_error(tmp_path):
    with pytest.raises(ProjectConfigError, match="no pipeline 'nope'"):
        ml_plan(_root(tmp_path, ML), None, "nope")


def test_a_serving_node_shows_the_model_it_declares(tmp_path):
    serving = """\
    type: ml
    requires_dates: false
    nodes:
      score:
        ml_stage: serving
        model: {name: churn, stage: production, features: [x]}
        inputs: [d]
        outputs: [ml.x.m]
    """
    item = ml_plan(_root(tmp_path, serving), None)["churn"]["nodes"]["score"]
    assert item["ml_stage"] == "serving"
    assert item["run"] == "built-in scorer"
    assert {k: item["model"][k] for k in ("name", "stage", "features")} == {
        "name": "churn",
        "stage": "production",
        "features": ["x"],
    }
