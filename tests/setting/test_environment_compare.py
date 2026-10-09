"""Effective configuration per environment, side by side."""

from __future__ import annotations

from pathlib import Path

from ducta.setting.environment_compare import compare_environments

PROJECT = """\
version: 2
project: demo
paths: {input: data, output: out}
settings:
  max_parallel_nodes: 4
  log_level: INFO
environments:
  dev:
    settings: {log_level: DEBUG}
  prod:
    settings: {max_parallel_nodes: 8}
    paths: {output: s3://lake/prod}
    catalog.raw.format: parquet
"""


def _project(tmp_path: Path) -> Path:
    (tmp_path / "ducta.yaml").write_text(PROJECT)
    (tmp_path / "catalog.yaml").write_text("raw: {format: csv}\nother: {format: csv}\n")
    (tmp_path / "pipelines").mkdir()
    (tmp_path / "pipelines" / "p.yaml").write_text(
        "nodes:\n  n:\n    run: src.m:f\n    inputs: [raw]\n    outputs: [other]\n"
    )
    return tmp_path


def test_rows_say_what_each_environment_changes(tmp_path):
    result = compare_environments(_project(tmp_path))
    assert result["environments"] == ["base", "dev", "prod"]
    rows = {r["key"]: r for r in result["rows"]}

    assert rows["settings.log_level"]["values"] == {"base": "INFO", "dev": "DEBUG", "prod": "INFO"}
    assert rows["settings.log_level"]["overridden"] == {"dev": True, "prod": False}
    assert rows["paths.output"]["values"]["prod"] == "s3://lake/prod"
    # paths and settings are listed even when no environment changes them …
    assert rows["paths.input"]["differs"] is False
    # … the catalog only where an environment does.
    assert rows["catalog.raw.format"]["values"] == {"base": "csv", "dev": "csv", "prod": "parquet"}
    assert "catalog.other.format" not in rows
