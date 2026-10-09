"""Extract a node into a template: the project means the same afterwards."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

pytest.importorskip("ruamel.yaml")

from ducta.api.exceptions import ValidationError  # noqa: E402
from ducta.api.repositories.v2_store import V2ProjectStore  # noqa: E402

DEMOS = Path.home() / "Desktop" / "demo_ducta" / "projects"


@pytest.fixture
def store(tmp_path):
    if not (DEMOS / "batch").is_dir():
        pytest.skip("demo_ducta projects not on this machine")
    root = tmp_path / "batch"
    shutil.copytree(
        DEMOS / "batch",
        root,
        ignore=shutil.ignore_patterns("data", ".ducta", "logs", "models", "lib", ".env"),
    )
    return V2ProjectStore.detect(root)


def _a_transform(store):
    for pipeline, p in store.project().pipelines.items():
        for name, node in p.nodes.items():
            if getattr(node, "kind", None) == "transform" and node.run:
                return pipeline, name, node
    pytest.skip("no transform node")


def test_extract_keeps_the_compiled_node(store):
    pipeline, name, node = _a_transform(store)
    before = node.model_dump()
    path = store.extract_node_template(pipeline, name, "my_step", params=["run"])
    assert path.is_file() and "${params.run}" in path.read_text()
    after = store.project().pipelines[pipeline].nodes[name].model_dump()
    assert after == before
    written = store.pipeline_path(pipeline).read_text()
    assert "use: my_step" in written and "with:" in written


def test_a_bad_param_changes_nothing(store):
    pipeline, name, _node = _a_transform(store)
    path = store.pipeline_path(pipeline)
    before = path.read_text()
    with pytest.raises(ValidationError):
        store.extract_node_template(pipeline, name, "my_step", params=["inputs"])
    assert path.read_text() == before
    assert not (store.root / "templates" / "nodes").exists()


def test_extract_subpipeline_keeps_the_compiled_pipeline(store):
    before = {n: v.model_dump() for n, v in store.project().pipelines["silver.clean"].nodes.items()}
    path = store.extract_subpipeline("silver.clean", list(before), "silver_steps")
    assert path.is_file()
    written = store.pipeline_path("silver.clean").read_text()
    assert "use: pipeline:silver_steps" in written
    after = {n: v.model_dump() for n, v in store.project().pipelines["silver.clean"].nodes.items()}
    assert after == before


def test_extract_subpipeline_refuses_unknown_nodes(store):
    path = store.pipeline_path("silver.clean")
    text = path.read_text()
    with pytest.raises(ValidationError):
        store.extract_subpipeline("silver.clean", ["nope"], "x")
    assert path.read_text() == text
