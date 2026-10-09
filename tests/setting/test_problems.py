"""Structured problems parsed from the loader's and the preflight's strings."""

from __future__ import annotations

from pathlib import Path

import pytest

from ducta.setting.problems import parse_problem, parse_problems
from ducta.setting.project_loader import ProjectConfigError, validate_project

PROJECT = """\
version: 2
project: demo
paths: {input: data, output: out}
"""

CATALOG = """\
raw_orders: {format: csv}
silver.orders: {format: parquet}
"""


def _project(tmp_path: Path, pipeline: str) -> Path:
    (tmp_path / "ducta.yaml").write_text(PROJECT)
    (tmp_path / "catalog.yaml").write_text(CATALOG)
    (tmp_path / "pipelines").mkdir()
    (tmp_path / "pipelines" / "etl.clean.yaml").write_text(pipeline)
    return tmp_path


def _problems(root: Path) -> list[str]:
    with pytest.raises(ProjectConfigError) as exc:
        validate_project(root)
    return exc.value.problems


def test_unknown_key_names_file_line_pipeline_node_and_fix(tmp_path: Path) -> None:
    root = _project(
        tmp_path,
        "nodes:\n  etl.clean_orders:\n    run: src.etl:clean\n    descripton: x\n"
        "    inputs: {raw: raw_orders}\n    outputs: [silver.orders]\n",
    )
    [raw] = _problems(root)
    p = parse_problem(raw)
    assert p.file == "pipelines/etl.clean.yaml"
    assert p.line == 4
    assert p.code == "unknown_key"
    assert p.pipeline == "etl.clean"
    assert p.node == "etl.clean_orders"
    assert p.fix is not None and p.fix.replace == ["descripton", "description"]
    # The CLI string is untouched.
    assert str(p) == raw


def test_unknown_dataset_names_node_dataset_and_suggestion(tmp_path: Path) -> None:
    root = _project(
        tmp_path,
        "nodes:\n  etl.clean_orders:\n    run: src.etl:clean\n"
        "    inputs: {raw: raw_ordrs}\n    outputs: [silver.orders]\n",
    )
    problems = [parse_problem(p) for p in _problems(root)]
    p = next(p for p in problems if p.code == "unknown_dataset")
    assert p.node == "etl.clean_orders"
    assert p.dataset == "raw_ordrs"
    assert p.file == "pipelines/etl.clean.yaml"
    assert p.fix is not None and p.fix.replace == ["raw_ordrs", "raw_orders"]


def test_duplicate_writer() -> None:
    p = parse_problem("pipelines/a.yaml:7 'silver.x' is written by both 'a.one' and 'a.two'")
    assert p.code == "duplicate_writer"
    assert p.dataset == "silver.x"
    assert (p.file, p.line) == ("pipelines/a.yaml", 7)


def test_preflight_strings_without_location() -> None:
    [err, warn] = parse_problems(
        ["Node 'silver.clean': cannot load function — No module named 'src.x'"],
        ["Node 'gold.agg': could not check model 'm' — boom"],
        source="preflight",
    )
    assert (err.severity, err.code, err.node, err.file) == (
        "error",
        "function_not_found",
        "silver.clean",
        None,
    )
    assert (warn.severity, warn.node, warn.source) == ("warning", "gold.agg", "preflight")


def test_unparseable_text_keeps_the_message() -> None:
    p = parse_problem("something odd happened")
    assert p.message == "Something odd happened"
    assert p.code == "config"
    assert p.to_dict()["file"] is None
    assert "raw" not in p.to_dict()
