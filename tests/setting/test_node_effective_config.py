"""A node's settings per environment, with where each value comes from."""

from __future__ import annotations

from pathlib import Path

import pytest

from ducta.setting.node_effective_config import effective_node_config

PROJECT = """\
version: 2
project: demo
paths: {input: d, output: d}
defaults:
  node: {retry: 1, timeout_seconds: 600}
environments:
  prod:
    pipelines.etl.nodes.etl.clean.retry: 5
"""

PIPELINE = """\
defaults:
  node: {timeout_seconds: 120}
nodes:
  etl.clean:
    run: src.m:clean
    inputs: [raw]
    outputs: [out]
    fail_fast: true
"""


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / "ducta.yaml").write_text(PROJECT)
    (tmp_path / "catalog.yaml").write_text(
        "raw: {format: csv, path: d/r}\nout: {format: csv, path: d/o}\n"
    )
    (tmp_path / "pipelines").mkdir()
    (tmp_path / "pipelines" / "etl.yaml").write_text(PIPELINE)
    return tmp_path


def test_each_value_names_its_origin(root):
    rows = {r["key"]: r for r in effective_node_config(root, "etl", "etl.clean")["rows"]}
    assert (rows["fail_fast"]["values"]["base"], rows["fail_fast"]["sources"]["base"]) == (
        True,
        "node",
    )
    assert (
        rows["timeout_seconds"]["values"]["base"],
        rows["timeout_seconds"]["sources"]["base"],
    ) == (
        120,
        "pipeline defaults",
    )
    assert rows["retry"]["sources"]["base"] == "project defaults"
    assert rows["on_missing_input"]["sources"]["base"] == "framework default"


def test_an_environment_override_is_flagged(root):
    rows = {r["key"]: r for r in effective_node_config(root, "etl", "etl.clean")["rows"]}
    assert rows["retry"]["values"] == {"base": 1, "prod": 5}
    assert rows["retry"]["overridden"] == {"prod": True}
    assert rows["timeout_seconds"]["overridden"] == {"prod": False}


def test_an_unknown_node(root):
    with pytest.raises(KeyError):
        effective_node_config(root, "etl", "nope")


TEMPLATE = """\
params: {attempts: 3}
node:
  run: src.m:clean
  retry: ${params.attempts}
  timeout_seconds: 30
"""

TEMPLATED_PIPELINE = """\
defaults:
  node: {timeout_seconds: 120, on_missing_input: skip}
nodes:
  etl.plain:
    run: src.m:plain
    inputs: [raw]
    outputs: [out]
    fail_fast: true
  etl.templated:
    use: clean
    with: {attempts: 9}
    inputs: [raw]
    outputs: [out2]
  etl.partly_templated:
    use: clean
    inputs: [out2]
    outputs: [out3]
    timeout_seconds: 5
"""

TEMPLATED_PROJECT = """\
version: 2
project: demo
paths: {input: d, output: d}
defaults:
  node: {retry: 1, timeout_seconds: 600}
environments:
  prod:
    pipelines.etl.nodes.etl.plain.retry: 5
  staging:
    pipelines.etl.nodes.etl.templated.retry: 2
"""


@pytest.fixture
def templated_root(tmp_path: Path) -> Path:
    (tmp_path / "ducta.yaml").write_text(TEMPLATED_PROJECT)
    (tmp_path / "catalog.yaml").write_text(
        "".join(f"{n}: {{format: csv, path: d/{n}}}\n" for n in ("raw", "out", "out2", "out3"))
    )
    (tmp_path / "pipelines").mkdir()
    (tmp_path / "pipelines" / "etl.yaml").write_text(TEMPLATED_PIPELINE)
    (tmp_path / "templates" / "nodes").mkdir(parents=True)
    (tmp_path / "templates" / "nodes" / "clean.yaml").write_text(TEMPLATE)
    return tmp_path


@pytest.mark.parametrize("node", ["etl.plain", "etl.templated", "etl.partly_templated"])
def test_the_table_agrees_with_what_the_loader_resolves(templated_root, node):
    """The table re-derives precedence to say where a value comes from; its values must
    still be the ones the engine runs with, in every environment."""
    from ducta.setting.node_effective_config import KEYS
    from ducta.setting.project.loader import validate_project

    table = effective_node_config(templated_root, "etl", node)
    for row in table["rows"]:
        for env in table["environments"]:
            loaded = validate_project(templated_root, None if env == "base" else env)
            actual = getattr(loaded.pipelines["etl"].nodes[node], row["key"])
            actual = None if actual in ({}, []) else actual
            assert row["values"][env] == actual, (node, env, row["key"])
    assert {r["key"] for r in table["rows"]} == set(KEYS)


def test_a_templated_node_names_its_template_as_the_origin(templated_root):
    rows = {
        r["key"]: r for r in effective_node_config(templated_root, "etl", "etl.templated")["rows"]
    }
    assert rows["retry"]["sources"]["base"] == "template clean"
    assert rows["retry"]["values"]["base"] == 9
    assert rows["retry"]["values"]["staging"] == 2
    assert rows["timeout_seconds"]["sources"]["base"] == "template clean"
    assert rows["on_missing_input"]["sources"]["base"] == "pipeline defaults"
