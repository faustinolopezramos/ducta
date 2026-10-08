"""Output checks that compare against another dataset get that dataset in a real run.

Regression: the runner never passed ``context_datasets`` to output checks, so
``referential_integrity``/``dataset_completeness`` with a ``reference_dataset``
always failed with "Reference dataset ... not available" inside a pipeline.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ducta.core.ledger import ledger_for
from tests.core import fakes
from tests.core.fakes import (
    FakeContext,
    FakeFunctionLoader,
    FakeInputLoader,
    FakeOutputManager,
    node,
)


@pytest.fixture(autouse=True)
def _clean_fakes():
    fakes.reset()
    yield
    fakes.reset()


def _scores(seed, loc=0.3, n=500):
    rng = np.random.default_rng(seed)
    return pd.DataFrame({"id": range(n), "score": np.clip(rng.normal(loc, 0.1, n), 0, 1)})


def _run(checks, datasets, tmp_path):
    from ducta.core.executors.facade import PipelineExecutor

    fn = fakes.register("score", lambda frame: frame)
    nodes = {
        "score": node(
            fn,
            inputs=["d"],
            outputs=["o"],
            data_quality={"checks": checks, "quality_gate": {"behavior": "warn_only"}},
        )
    }
    pipelines = {"p": {"name": "p", "nodes": ["score"], "type": "batch", "requires_dates": False}}
    context = FakeContext(
        nodes_config=nodes, pipelines_config=pipelines, global_config={"output_path": str(tmp_path)}
    )
    engine = PipelineExecutor(context)
    batch = engine.batch_executor
    batch.input_loader = FakeInputLoader(datasets)
    batch.output_manager = FakeOutputManager(datasets)
    batch.node_executor.input_loader = batch.input_loader
    batch.node_executor.output_manager = batch.output_manager
    batch.node_executor._output_writer.output_manager = batch.output_manager
    batch.node_executor._function_loader = FakeFunctionLoader()
    engine.run_pipeline("p")
    (quality,) = [q for q in ledger_for(context).quality_results if q["node"] == "score"]
    return quality, batch.input_loader.loaded


def test_a_reference_the_node_did_not_read_is_loaded(tmp_path):
    quality, loaded = _run(
        {"prediction_drift": {"column": "score", "reference": "val"}},
        {"d": _scores(1), "val": _scores(2)},
        tmp_path,
    )
    assert quality["passed"] and quality["warnings"] == 0
    assert loaded == ["d", "val"]


def test_a_shifted_score_is_caught_against_the_loaded_reference(tmp_path):
    quality, _ = _run(
        {"prediction_drift": {"column": "score", "reference": "val"}},
        {"d": _scores(1, loc=0.7), "val": _scores(2)},
        tmp_path,
    )
    assert quality["warnings"] == 1


def test_a_reference_the_node_read_is_reused(tmp_path):
    quality, loaded = _run(
        {
            "referential_integrity": {
                "column": "id",
                "reference_dataset": "d",
                "reference_column": "id",
            }
        },
        {"d": _scores(1)},
        tmp_path,
    )
    assert quality["passed"] and quality["errors"] == 0
    assert loaded == ["d"]
