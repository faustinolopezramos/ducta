"""The ML contract: a split, model version or hyperparameter written in a pipeline
file reaches the node, and a node bound to a split cannot silently ignore it.

Before: a `split:` on a node never reached `ml_context` (the pipeline's, or none, was
used); a training node that ignored its split only logged a warning — and so did
every feature node under a pipeline split, which taught people to ignore it; and the
run certificate said nothing about whether a split was applied.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from ducta.core import ml_contract
from ducta.core.errors import PipelineExecutionError
from ducta.core.ledger import ledger_for
from ducta.mlrun.split import split_dataframe
from ducta.setting.schemas import MLStage
from tests.core import fakes
from tests.core.fakes import (
    FakeContext,
    FakeFrame,
    FakeFunctionLoader,
    FakeInputLoader,
    FakeOutputManager,
    node,
)

RANDOM = {"method": "random", "test_size": 0.25, "seed": 7}
STRATIFIED = {"method": "stratified", "test_size": 0.2, "stratify_col": "y", "seed": 1}


@pytest.fixture(autouse=True)
def _clean_registry():
    fakes.reset()
    yield
    fakes.reset()


def _engine(nodes_config, pipelines_config, datasets=None, **settings):
    from ducta.core.executors.facade import PipelineExecutor

    datasets = datasets if datasets is not None else {}
    # The ML pipelines' default sanity checks read real DataFrames, not FakeFrames.
    settings = {"ml_default_sanity_checks": False, **settings}
    context = FakeContext(
        nodes_config=nodes_config, pipelines_config=pipelines_config, global_config=settings
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
    return engine, context


def _rows(n=40):
    return [{"x": i, "y": i % 2} for i in range(n)]


def _pipeline(nodes, split=None, **extra):
    cfg = {"name": "p", "nodes": list(nodes), "type": "ml", "requires_dates": False, **extra}
    if split:
        cfg["split"] = split
    return {"p": cfg}


def _seen():
    """A recorder for what a node received, and node functions that use it."""
    return {}


def _applies_split(seen, name="train"):
    def fn(frame, ml_context=None):
        seen[name] = ml_context
        df = pd.DataFrame(frame.rows)
        train, test = split_dataframe(df, ml_context.split, ml_context=ml_context)
        seen[name + ":sizes"] = (len(train), len(test))
        return FakeFrame(rows=train.to_dict("records"))

    return fn


def _ignores_split(seen, name="train"):
    def fn(frame, ml_context=None):
        seen[name] = ml_context
        return frame

    return fn


def _ml_record(context, name):
    return next(r for r in ledger_for(context).node_details if r["name"] == name).get("ml")


# ── the rules ────────────────────────────────────────────────────────────────


class TestRules:
    def test_a_node_split_overrides_the_pipeline_split(self):
        assert ml_contract.effective_split({"split": RANDOM}, STRATIFIED) == (RANDOM, "node")
        assert ml_contract.effective_split({}, STRATIFIED) == (STRATIFIED, "pipeline")
        assert ml_contract.effective_split({}, None) == (None, None)

    @pytest.mark.parametrize(
        "node_config, pipeline_split, bound",
        [
            ({"split": RANDOM}, None, True),  # its own split: always bound
            ({"ml_stage": "training"}, RANDOM, True),
            ({"ml_stage": "evaluation"}, RANDOM, True),
            ({"ml_stage": MLStage.TRAINING}, RANDOM, True),  # the validated enum
            ({"ml_stage": "feature_engineering"}, RANDOM, False),
            ({}, RANDOM, False),  # no stage: a feature node is not bound
            ({"ml_stage": "training"}, None, False),  # nothing declared
        ],
    )
    def test_who_is_bound_to_apply_a_split(self, node_config, pipeline_split, bound):
        assert ml_contract.must_apply_split(node_config, pipeline_split) is bound

    def test_the_stage_is_plain_text_even_from_the_enum(self):
        assert ml_contract.node_stage({"ml_stage": MLStage.TRAINING}) == "training"

    def test_the_message_says_where_the_split_was_declared_and_how_to_apply_it(self):
        msg = ml_contract.not_applied_message("train", STRATIFIED, "node")
        assert "declared on the node" in msg and "stratify_col=y" in msg
        assert "split_dataframe(df, ml_context.split, ml_context=ml_context)" in msg
        assert "split_enforcement: warn" in msg


# ── what reaches the node (a real Context, loaded from project files) ──────────
#
# These run on the real `Context` on purpose: the bug was in
# `Context.get_node_ml_config`, which a fake context does not have.


def _real_engine(tmp_path, nodes_yaml, pipeline_extra="", datasets=None):
    import textwrap

    from ducta.core.executors.facade import PipelineExecutor
    from ducta.setting.project_loader import load_project_v2

    root = tmp_path / "proj"
    (root / "pipelines").mkdir(parents=True)
    (root / "ducta.yaml").write_text(
        "version: 2\nproject: p\npaths: {input: d, output: o}\n"
        "settings: {ml_default_sanity_checks: false, evidence_level: 'off', "
        "preflight_enabled: false, mlops_enabled: false}\n"
    )
    (root / "catalog.yaml").write_text(
        "d: {format: parquet, path: d.parquet}\nml.x.o: {format: parquet}\n"
    )
    (root / "pipelines" / "p.yaml").write_text(
        "type: ml\nrequires_dates: false\n"
        + pipeline_extra
        + "nodes:\n"
        + textwrap.indent(textwrap.dedent(nodes_yaml), "  ")
    )
    context = load_project_v2(root, None)
    datasets = datasets if datasets is not None else {"d": FakeFrame(_rows())}
    engine = PipelineExecutor(context)
    batch = engine.batch_executor
    batch.input_loader = FakeInputLoader(datasets)
    batch.output_manager = FakeOutputManager(datasets)
    batch.node_executor.input_loader = batch.input_loader
    batch.node_executor.output_manager = batch.output_manager
    batch.node_executor._output_writer.output_manager = batch.output_manager
    batch.node_executor._function_loader = FakeFunctionLoader()
    batch.node_executor._coordinator._ml_builder = batch.node_executor._ml_builder
    return engine, context


TRAIN = """\
train:
  run: fake:t
  inputs: [d]
  outputs: [ml.x.o]
"""


class TestWhatReachesTheNode:
    def test_the_real_context_hands_over_the_node_split_and_model_version(self, tmp_path):
        _, context = _real_engine(
            tmp_path,
            TRAIN + "  split: {method: random, test_size: 0.25, seed: 7}\n"
            "  model_version: '2.0'\n",
        )
        cfg = context.get_node_ml_config("train")
        assert cfg["split"] == RANDOM and cfg["model_version"] == "2.0"

    def test_a_split_declared_on_the_node_reaches_ml_context(self, tmp_path):
        seen = _seen()
        fakes.register("t", _applies_split(seen))
        engine, _ = _real_engine(
            tmp_path,
            TRAIN + "  ml_stage: training\n  split: {method: random, test_size: 0.25, seed: 7}\n",
        )
        engine.run_pipeline("p")
        assert seen["train"].split == RANDOM
        assert seen["train:sizes"] == (30, 10)

    def test_the_node_split_wins_over_the_pipeline_split(self, tmp_path):
        seen = _seen()
        fakes.register("t", _applies_split(seen))
        engine, _ = _real_engine(
            tmp_path,
            TRAIN + "  ml_stage: training\n  split: {method: random, test_size: 0.25, seed: 7}\n",
            pipeline_extra="split: {method: stratified, test_size: 0.2, stratify_col: y, seed: 1}\n",
        )
        engine.run_pipeline("p")
        assert seen["train"].split == RANDOM

    def test_a_node_model_version_wins_over_the_pipeline_and_the_cli_over_both(self, tmp_path):
        seen = _seen()
        fakes.register("t", _ignores_split(seen))
        engine, _ = _real_engine(
            tmp_path, TRAIN + "  model_version: node-2\n", pipeline_extra="model_version: pipe-1\n"
        )
        engine.run_pipeline("p")
        assert seen["train"].model_version == "node-2"
        engine.run_pipeline("p", model_version="cli-3")
        assert seen["train"].model_version == "cli-3"

    def test_hyperparams_merge_pipeline_then_node_then_cli(self, tmp_path):
        seen = _seen()
        fakes.register("t", _ignores_split(seen))
        engine, _ = _real_engine(
            tmp_path,
            TRAIN + "  hyperparams: {depth: 4, lr: 0.1}\n",
            pipeline_extra="hyperparams: {depth: 2, trees: 50}\n",
        )
        engine.run_pipeline("p", hyperparams={"lr": 0.5})
        assert seen["train"].hyperparams == {"depth": 4, "trees": 50, "lr": 0.5}

    def test_running_one_node_gets_the_same_ml_context(self, tmp_path):
        # `ducta start -p p -n train` used to skip the per-node preparation entirely.
        seen = _seen()
        fakes.register("t", _applies_split(seen))
        engine, _ = _real_engine(
            tmp_path,
            TRAIN + "  ml_stage: training\n  split: {method: random, test_size: 0.25, seed: 7}\n"
            "  hyperparams: {depth: 4}\n",
        )
        engine.run_pipeline("p", node_name="train")
        assert seen["train"].split == RANDOM
        assert seen["train"].hyperparams == {"depth": 4}

    def test_a_split_on_a_node_of_a_batch_pipeline_still_reaches_it(self):
        seen = _seen()
        nodes = {
            "train": node(
                fakes.register("t", _applies_split(seen)), inputs=["d"], outputs=["o"], split=RANDOM
            )
        }
        pipelines = {
            "p": {"name": "p", "nodes": ["train"], "type": "batch", "requires_dates": False}
        }
        engine, _ = _engine(nodes, pipelines, {"d": FakeFrame(_rows())})
        engine.run_pipeline("p")
        assert seen["train"].split == RANDOM


# ── a split that is not applied ──────────────────────────────────────────────


class TestASplitThatIsNotApplied:
    def _ignoring_trainer(self, **node_extra):
        seen = _seen()
        nodes = {
            "train": node(
                fakes.register("t", _ignores_split(seen)), inputs=["d"], outputs=["o"], **node_extra
            )
        }
        return seen, nodes

    def test_a_training_node_that_ignores_the_pipeline_split_fails_the_run(self):
        _, nodes = self._ignoring_trainer(ml_stage="training")
        engine, context = _engine(nodes, _pipeline(["train"], split=RANDOM), {"d": FakeFrame()})
        with pytest.raises(PipelineExecutionError):
            engine.run_pipeline("p")
        record = next(r for r in ledger_for(context).node_details if r["name"] == "train")
        assert record["status"] == "failed"
        assert "never applied it" in record["error"]

    def test_its_output_is_not_written(self):
        _, nodes = self._ignoring_trainer(ml_stage="training")
        datasets = {"d": FakeFrame()}
        engine, _ = _engine(nodes, _pipeline(["train"], split=RANDOM), datasets)
        with pytest.raises(PipelineExecutionError):
            engine.run_pipeline("p")
        assert "o" not in datasets

    def test_a_node_that_ignores_its_own_split_fails_whatever_its_stage(self):
        _, nodes = self._ignoring_trainer(split=RANDOM)
        engine, _ = _engine(nodes, _pipeline(["train"]), {"d": FakeFrame()})
        with pytest.raises(PipelineExecutionError):
            engine.run_pipeline("p")

    def test_with_split_enforcement_warn_the_run_continues(self):
        _, nodes = self._ignoring_trainer(ml_stage="training")
        engine, context = _engine(
            nodes, _pipeline(["train"], split=RANDOM), {"d": FakeFrame()}, split_enforcement="warn"
        )
        engine.run_pipeline("p")
        ml = _ml_record(context, "train")
        assert ml["split_required"] is True and ml["split_applied"] is False

    def test_a_feature_node_under_a_pipeline_split_is_not_bound(self):
        seen = _seen()
        nodes = {
            "features": node(
                fakes.register("f", _ignores_split(seen, "features")),
                inputs=["d"],
                outputs=["feat"],
            ),
            "train": node(
                fakes.register("t", _applies_split(seen)),
                inputs=["feat"],
                outputs=["o"],
                ml_stage="training",
                after=["features"],
            ),
        }
        engine, context = _engine(
            nodes, _pipeline(["features", "train"], split=RANDOM), {"d": FakeFrame(_rows())}
        )
        engine.run_pipeline("p")
        assert seen["features"].split == RANDOM  # it is told, but not bound
        assert _ml_record(context, "features")["split_required"] is False
        assert _ml_record(context, "train")["split_applied"] is True


# ── the evidence ─────────────────────────────────────────────────────────────


class TestTheEvidence:
    def test_the_trace_records_what_was_declared_and_what_was_applied(self):
        seen = _seen()
        nodes = {
            "train": node(
                fakes.register("t", _applies_split(seen)),
                inputs=["d"],
                outputs=["o"],
                ml_stage="training",
                split=RANDOM,
                hyperparams={"depth": 4},
                model_version="1.2",
            )
        }
        engine, context = _engine(nodes, _pipeline(["train"]), {"d": FakeFrame(_rows())})
        engine.run_pipeline("p")
        assert _ml_record(context, "train") == {
            "stage": "training",
            "split": RANDOM,
            "split_source": "node",
            "split_required": True,
            "split_applied": True,
            "model_version": "1.2",
            "hyperparams": {"depth": 4},
        }

    def test_the_certificate_carries_it(self, tmp_path):
        seen = _seen()
        nodes = {
            "train": node(
                fakes.register("t", _applies_split(seen)),
                inputs=["d"],
                outputs=["o"],
                ml_stage="training",
            )
        }
        engine, _ = _engine(
            nodes,
            _pipeline(["train"], split=RANDOM),
            {"d": FakeFrame(_rows())},
            evidence_level="record",
            run_certificate_dir=str(tmp_path / "runs"),
        )
        result = engine.run_pipeline("p")
        cert = json.loads(open(result.certificate_path, encoding="utf-8").read())
        ml = cert["nodes"][0]["ml"]
        assert (ml["split_source"], ml["split_applied"]) == ("pipeline", True)

    def test_a_plain_batch_node_carries_no_ml_record(self):
        nodes = {
            "n": node(fakes.register("p", fakes.passthrough("p")), inputs=["d"], outputs=["o"])
        }
        pipelines = {"p": {"name": "p", "nodes": ["n"], "type": "batch", "requires_dates": False}}
        engine, context = _engine(nodes, pipelines, {"d": FakeFrame()})
        engine.run_pipeline("p")
        assert _ml_record(context, "n") is None
