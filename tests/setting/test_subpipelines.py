"""Subpipelines: `use: pipeline:<name>` expands into the subpipeline's nodes and datasets."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from ducta.setting.project_loader import ProjectConfigError, validate_project

SUB = """
description: Clean one table — dedupe, then drop rows without a key
params:
  name: {type: string}
  source: {type: string}
  target: {type: string}
nodes:
  "${params.name}.dedupe":
    run: src.clean:dedupe
    inputs: {df: "${params.source}"}
    outputs: ["${params.target}_dedup"]
  "${params.name}.keyed":
    run: src.clean:drop_keyless
    inputs: {df: "${params.target}_dedup"}
    outputs: ["${params.target}"]
catalog:
  "${params.target}_dedup": {format: parquet, path: "out/${params.name}_dedup"}
"""


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(text), encoding="utf-8")


@pytest.fixture
def project(tmp_path):
    _write(tmp_path, "ducta.yaml", "version: 2\nproject: t\npaths: {input: data, output: out}\n")
    _write(
        tmp_path,
        "catalog.yaml",
        """
        raw.orders: {format: parquet, path: data/orders}
        raw.customers: {format: parquet, path: data/customers}
        silver.orders: {format: parquet, path: out/orders}
        silver.customers: {format: parquet, path: out/customers}
        """,
    )
    _write(tmp_path, "templates/pipelines/clean_table.yaml", SUB)
    return tmp_path


def test_two_instances_expand_into_their_own_nodes_and_datasets(project):
    _write(
        project,
        "pipelines/silver.yaml",
        """
        nodes:
          orders:
            use: pipeline:clean_table
            with: {name: orders, source: raw.orders, target: silver.orders}
          customers:
            use: pipeline:clean_table
            with: {name: customers, source: raw.customers, target: silver.customers}
        """,
    )
    p = validate_project(project)
    nodes = p.pipelines["silver"].nodes
    assert list(nodes) == ["orders.dedupe", "orders.keyed", "customers.dedupe", "customers.keyed"]
    assert nodes["orders.keyed"].model_dump()["outputs"] == ["silver.orders"]
    assert "silver.customers_dedup" in p.catalog


def test_problems_name_the_instance_and_the_subpipeline(project):
    _write(
        project,
        "pipelines/silver.yaml",
        """
        nodes:
          orders:
            use: pipeline:clean_tabel
          other:
            use: pipeline:clean_table
            with: {name: o, source: raw.orders}
            outputs: [x]
        """,
    )
    with pytest.raises(ProjectConfigError) as e:
        validate_project(project)
    text = "\n".join(e.value.problems)
    assert "did you mean 'clean_table'" in text
    assert "takes only use and with, not outputs" in text
