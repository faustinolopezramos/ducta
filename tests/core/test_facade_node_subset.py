"""Running a subset of a pipeline's nodes: in order among themselves, nothing else."""

from __future__ import annotations

import pytest

from tests.core import fakes
from tests.core.fakes import FakeFrame, node
from tests.core.test_facade_run_result import _engine


@pytest.fixture(autouse=True)
def _clean_registry():
    fakes.reset()
    yield
    fakes.reset()


def _chain():
    nodes = {
        "a": node(fakes.register("a", fakes.passthrough("a")), outputs=["x"]),
        "b": node(fakes.register("b", fakes.passthrough("b")), inputs=["x"], outputs=["y"]),
        "c": node(
            fakes.register("c", fakes.passthrough("c")),
            inputs=["y"],
            outputs=["z"],
            dependencies=["a"],
        ),
    }
    pipelines = {
        "p": {"name": "p", "nodes": ["a", "b", "c"], "type": "batch", "requires_dates": False}
    }
    return nodes, pipelines


def test_only_the_chosen_nodes_run_in_dependency_order():
    nodes, pipelines = _chain()
    # x is already materialized: b reads it without a running.
    engine, _ = _engine(nodes, pipelines, datasets={"x": FakeFrame(name="x")})

    result = engine.run_pipeline("p", node_names=["c", "b"])

    assert result.ok
    assert [n.name for n in result.nodes] == ["b", "c"]
    # c's explicit edge to a (not running) does not block it.


def test_a_node_of_another_pipeline_is_refused():
    nodes, pipelines = _chain()
    engine, _ = _engine(nodes, pipelines)
    with pytest.raises(Exception, match="Not nodes of this pipeline"):
        engine.run_pipeline("p", node_names=["b", "elsewhere"])


def test_each_run_fingerprints_the_code_it_runs():
    """A long-lived process must not certify code it fingerprinted in an earlier run."""
    from ducta.core import code_fingerprint

    nodes, pipelines = _chain()
    engine, _ = _engine(nodes, pipelines, datasets={"x": FakeFrame(name="x")})
    code_fingerprint._CACHE[("stale", "entry")] = {"source_hash": "old"}
    engine.run_pipeline("p", node_names=["b"])
    assert ("stale", "entry") not in code_fingerprint._CACHE
