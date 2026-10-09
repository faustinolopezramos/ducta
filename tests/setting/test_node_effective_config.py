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
