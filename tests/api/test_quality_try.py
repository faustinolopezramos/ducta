"""Trying a draft of checks on a dataset's data, and reading a node's quality block."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ducta.api.dependencies import get_current_user
from ducta.api.main import create_app
from ducta.api.models.auth import User

DEMOS = Path.home() / "Desktop" / "demo_ducta" / "projects"
DATASET = "silver.education.student_cleaned"


@pytest.fixture
def setup(tmp_path, monkeypatch):
    src = DEMOS / "batch"
    if not (src / "data" / "dev" / "silver").is_dir():
        pytest.skip("demo_ducta batch with dev data not on this machine")
    root = tmp_path / "batch"
    shutil.copytree(
        src, root, ignore=shutil.ignore_patterns(".ducta", "logs", "models", "lib", ".env")
    )
    monkeypatch.chdir(tmp_path)
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: User(
        id="a", username="a", email="a@example.com", roles=["admin"]
    )
    return TestClient(app), {"source": str(root)}, root


def test_try_checks_reports_per_check_without_saving(setup):
    c, params, root = setup
    before = {p for p in root.rglob("*") if "quality" in p.parts}
    r = c.post(
        "/api/projects/batch/quality/try",
        params=params,
        json={
            "dataset": DATASET,
            "env": "dev",
            "checks": {
                "range": {"column": "age", "min": 15, "max": 18},
                "null_rate": {"columns": ["G3"], "threshold": 0.0},
                "business_rules": {"rule_type": "sql", "rules": ["age <= 18"]},
            },
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    by = {x["check_name"]: x for x in body["results"]}
    assert by["range"]["passed"] is False  # ages up to 22 in the demo data
    assert by["null_rate"]["passed"] is True
    # SQL rules are evaluated here too (sqlglot), so they get a real verdict.
    assert by["business_rules"]["passed"] is False  # the same over-18 rows, as a SQL rule
    assert "evaluated here" in by["business_rules"]["message"]
    assert body["passed"] is False and body["sampled_rows"] > 0
    assert {p for p in root.rglob("*") if "quality" in p.parts} == before  # no report written


def test_node_quality_block_as_written(setup):
    c, params, _root = setup
    r = c.get(
        "/api/projects/batch/pipelines/silver.clean/nodes/silver.clean_student/quality",
        params=params,
    ).json()
    assert "null_rate" in r["quality"]["checks"] and r["outputs"] == [DATASET]
