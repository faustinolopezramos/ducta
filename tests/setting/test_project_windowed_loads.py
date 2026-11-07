"""Windowed loads in a project: ``write.partition_overwrite`` and ``ingest.incremental``."""

from __future__ import annotations

from pathlib import Path

import pytest

from ducta.setting.project.loader import ProjectConfigError, compile_project, validate_project

PROJECT = """\
version: 2
project: demo
paths: {input: data, output: out}
"""

CATALOG = """\
raw.sales.events:
  format: csv
  path: data/events.csv
  incremental: {column: day}
silver.sales.daily:
  format: parquet
  write: {mode: overwrite, partition: [day], partition_overwrite: dynamic}
bronze.crm.orders:
  format: parquet
"""

PIPELINE = """\
description: daily
requires_dates: true
nodes:
  keep:
    run: pipelines.daily:keep
    inputs: [raw.sales.events]
    outputs: [silver.sales.daily]
  pull:
    kind: ingest
    ingest: {source: crm, table: orders, incremental: {column: order_ts}}
    outputs: [bronze.crm.orders]
"""


def _project(tmp_path: Path, catalog: str = CATALOG, pipeline: str = PIPELINE) -> Path:
    (tmp_path / "pipelines").mkdir(exist_ok=True)
    (tmp_path / "ducta.yaml").write_text(PROJECT)
    (tmp_path / "catalog.yaml").write_text(catalog)
    (tmp_path / "pipelines" / "daily.yaml").write_text(pipeline)
    return tmp_path


def _compile(root: Path):
    return compile_project(validate_project(root))


def test_partition_overwrite_reaches_the_writer_config(tmp_path):
    docs = _compile(_project(tmp_path))
    out = docs["output_config"]["silver.sales.daily"]
    assert (out["write_mode"], out["partition"], out["partition_overwrite"]) == (
        "overwrite",
        ["day"],
        "dynamic",
    )
    assert "partition_overwrite" not in docs["input_config"].get("silver.sales.daily", {})


def test_the_ingest_window_reaches_the_node(tmp_path):
    nodes = _compile(_project(tmp_path))["nodes_config"]
    assert nodes["pull"]["incremental"] == {"column": "order_ts"}


@pytest.mark.parametrize(
    "write, message",
    [
        ("{partition_overwrite: dynamic}", "needs write.partition"),
        (
            "{mode: append, partition: [day], partition_overwrite: dynamic}",
            "needs mode 'overwrite'",
        ),
        (
            "{partition: [day], partition_overwrite: dynamic, overwrite_strategy: replaceWhere, partition_col: day}",
            "replaceWhere",
        ),
        ("{partition: [day], partition_overwrite: sometimes}", "partition_overwrite"),
    ],
)
def test_a_contradictory_partition_overwrite_is_an_error(tmp_path, write, message):
    catalog = CATALOG.replace(
        "{mode: overwrite, partition: [day], partition_overwrite: dynamic}", write
    )
    with pytest.raises(ProjectConfigError, match=message):
        validate_project(_project(tmp_path, catalog=catalog))


def test_an_ingest_window_needs_a_column(tmp_path):
    pipeline = PIPELINE.replace("incremental: {column: order_ts}", "incremental: {}")
    with pytest.raises(ProjectConfigError):
        validate_project(_project(tmp_path, pipeline=pipeline))
