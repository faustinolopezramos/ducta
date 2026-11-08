"""``decompile`` turns the engine documents back into a project, and nothing changes.

The web app stores an edited engine document through ``decompile`` and keeps the result
only if the project compiles back to the same thing (``V2ProjectStore.verify``). This
checks that round trip on every template and on the windowed-load settings, without the
API: compile → decompile → write the tree as files → compile again.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from ducta.console.templates.generator import ConfigFormat, TemplateGenerator, TemplateType
from ducta.setting.project.decompile import _first_difference, canonical, decompile
from ducta.setting.project.loader import compile_project, validate_project

KINDS = ["medallion_basic", "streaming_basic", "ml_basic", "ml_scoring", "hybrid_basic"]


def _write_tree(tree: dict, root: Path) -> None:
    """The project tree as format-2 files: ducta.yaml, catalog.yaml, pipelines/<name>.yaml."""
    project = {k: v for k, v in tree.items() if k not in ("catalog", "pipelines")}
    (root / "ducta.yaml").write_text(yaml.safe_dump(project, sort_keys=False))
    (root / "catalog.yaml").write_text(yaml.safe_dump(tree["catalog"], sort_keys=False))
    (root / "pipelines").mkdir(exist_ok=True)
    for name, pipeline in tree["pipelines"].items():
        (root / "pipelines" / f"{name}.yaml").write_text(yaml.safe_dump(pipeline, sort_keys=False))


def _round_trip(source: Path, tmp_path: Path, env=None):
    before = compile_project(validate_project(source, env))
    problems: list = []
    tree = decompile(before, "p", problems, [])
    assert problems == []

    # The node code stays; every configuration file is replaced by the decompiled tree.
    copy = tmp_path / "copy"
    shutil.copytree(source, copy, ignore=shutil.ignore_patterns("*.yaml", "*.yml", "catalog"))
    _write_tree(tree, copy)
    after = compile_project(validate_project(copy, env))
    return before, after


@pytest.mark.parametrize("kind", KINDS)
def test_every_template_survives_the_round_trip(tmp_path, kind):
    root = tmp_path / "p"
    TemplateGenerator(root, ConfigFormat.YAML).generate_project(TemplateType(kind), "p")
    before, after = _round_trip(root, tmp_path)
    assert _first_difference(canonical(before), canonical(after)) is None


WINDOWED_PROJECT = """\
version: 2
project: p
paths: {input: data, output: out}
"""

WINDOWED_CATALOG = """\
raw.sales.events:
  format: csv
  path: data/events.csv
  incremental: {column: day}
silver.sales.daily:
  format: parquet
  write: {mode: overwrite, partition: [day], partition_overwrite: dynamic}
bronze.crm.orders:
  format: delta
  write: {mode: overwrite, overwrite_strategy: replaceWhere, partition_col: order_day}
"""

WINDOWED_PIPELINE = """\
requires_dates: true
nodes:
  keep:
    run: pipelines.daily:keep
    inputs: [raw.sales.events]
    outputs: [silver.sales.daily]
  pull:
    kind: ingest
    ingest:
      source: crm
      table: orders
      columns: [id, order_day]
      where: "status = 'paid'"
      incremental: {column: order_day}
    outputs: [bronze.crm.orders]
"""


def test_windowed_loads_survive_the_round_trip(tmp_path):
    root = tmp_path / "p"
    (root / "pipelines").mkdir(parents=True)
    (root / "ducta.yaml").write_text(WINDOWED_PROJECT)
    (root / "catalog.yaml").write_text(WINDOWED_CATALOG)
    (root / "pipelines" / "daily.yaml").write_text(WINDOWED_PIPELINE)
    (root / "pipelines" / "daily.py").write_text("def keep(df, params=None):\n    return df\n")

    before, after = _round_trip(root, tmp_path)

    assert _first_difference(canonical(before), canonical(after)) is None
    out = after["output_config"]["silver.sales.daily"]
    assert out["partition_overwrite"] == "dynamic"
    assert after["nodes_config"]["pull"]["incremental"] == {"column": "order_day"}
