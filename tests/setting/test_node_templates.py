"""Node templates: ``use`` + ``with`` expand before validation (ADR 0001 §3)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from ducta.setting.project_loader import ProjectConfigError, validate_project
from ducta.setting.project_schema import json_schema


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text), encoding="utf-8")


@pytest.fixture
def project(tmp_path):
    _write(tmp_path, "ducta.yaml", "version: 2\nproject: t\npaths: {input: data, output: out}\n")
    _write(
        tmp_path,
        "catalog.yaml",
        """
        raw.students: {format: parquet, path: data/s.parquet}
        silver.students: {format: parquet, path: out/s}
        """,
    )
    _write(
        tmp_path,
        "templates/nodes/dedupe_by_key.yaml",
        """
        description: Drop duplicate rows by key
        params:
          key: {type: string}
          keep: {type: string, default: last}
          outputs: {default: [silver.students]}
        node:
          run: src.dedupe:dedupe
          description: "Dedupe by ${params.key}, keeping the ${params.keep}"
          outputs: "${params.outputs}"
        """,
    )
    return tmp_path


def _pipeline(root: Path, node: str) -> None:
    _write(root, "pipelines/clean.yaml", "nodes:\n" + textwrap.indent(textwrap.dedent(node), "  "))


def test_use_expands_with_params_and_instance_wins(project):
    _pipeline(
        project,
        """
        dedupe:
          use: dedupe_by_key
          with: {key: student_id}
          inputs: {df: raw.students}
          run_in_process: true
        """,
    )
    node = validate_project(project).pipelines["clean"].nodes["dedupe"]
    dumped = node.model_dump()
    assert dumped["run"] == "src.dedupe:dedupe"
    assert dumped["description"] == "Dedupe by student_id, keeping the last"
    assert dumped["outputs"] == ["silver.students"]  # a list default keeps its type
    assert dumped["run_in_process"] is True  # set on the instance


def test_problems_point_at_the_instance(project):
    _pipeline(
        project,
        """
        dedupe:
          use: dedupe_by_kye
          inputs: {df: raw.students}
        other:
          use: dedupe_by_key
          with: {kee: x}
        """,
    )
    with pytest.raises(ProjectConfigError) as e:
        validate_project(project)
    text = "\n".join(e.value.problems)
    assert "pipelines/clean.yaml:" in text
    assert "did you mean 'dedupe_by_key'" in text
    assert "has no parameter 'kee'" in text
    assert "needs the parameter 'key'" in text


def test_the_editor_schema_accepts_use():
    nodes = json_schema()["$defs"]["pipeline"]["properties"]["nodes"]["additionalProperties"]
    assert nodes["if"]["required"] == ["use"]
    assert "node_template" in json_schema()["$defs"]


def test_effective_config_names_the_template(project):
    from ducta.setting.node_effective_config import effective_node_config

    _write(
        project,
        "templates/nodes/slow.yaml",
        "params: {t: 60}\nnode: {run: src.x:y, timeout_seconds: '${params.t}'}\n",
    )
    _pipeline(
        project,
        """
        step:
          use: slow
          with: {t: 90}
          inputs: {df: raw.students}
          outputs: [silver.students]
        """,
    )
    rows = {r["key"]: r for r in effective_node_config(project, "clean", "step")["rows"]}
    assert rows["timeout_seconds"]["values"]["base"] == 90
    assert rows["timeout_seconds"]["sources"]["base"] == "template slow"
