"""Data governance review (2026-11-20): every finding, proven first, then fixed.

G1  An environment name in other letters (``PROD``) got the ``prod`` configuration but
    passed every protected-environment guard.
G2  ``POST /api/quality/run`` read any workspace file, prod's and PII columns included.
G3  A snapshot test copied prod rows, PII unmasked, into ``tests/fixtures``.
G4  A developer deleted a protected environment's quality reports.
G5  AI proposals measured prod without the permission; PII extremes reached the model.
G6  ``metadata.pii`` naming no column masked nothing, silently; downstream PII undeclared.
G7  Outputs that leave the project were never asked for an owner; ``ducta check`` was silent.
G8  Allowed reads of prod rows / PII left no audit trace; certificates did not say who.
G9  A protected run's logs, errors and diagnosis: kept visible to whoever sees the run
    (debugging prod is the job), their reads audited.

Balanced the same day so security does not cost the experience: operators may tidy prod's
quality reports, fixtures keep each value's kind, ``ducta check`` sums advice up per kind,
and reads are only tracked when auth is on (the audit needs it).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from ducta.project_store.governance import governance_problems, is_protected, known_columns
from ducta_server.dependencies import get_current_user
from ducta_server.main import create_app
from ducta_server.models.auth import User


@pytest.fixture
def project(tmp_path, monkeypatch):
    from ducta.console.templates import TemplateGenerator, TemplateType

    monkeypatch.chdir(tmp_path)
    root = tmp_path / "proj"
    TemplateGenerator(root).generate_project(TemplateType.MEDALLION_BASIC, "proj")
    catalog = root / "catalog.yaml"
    catalog.write_text(
        catalog.read_text().replace(
            "  description: Source orders (CSV, JSON or Parquet)\n",
            "  description: Source orders (CSV, JSON or Parquet)\n  metadata: {pii: [category]}\n",
        )
    )
    # An operator's earlier prod run left its bronze output on disk.
    out = root / "data/prod/bronze/etl/raw_data"
    out.mkdir(parents=True)
    pd.DataFrame(
        {"order_id": [999], "category": ["PROD-ONLY-ROW"], "amount": [1.0], "order_date": ["x"]}
    ).to_parquet(out / "part-0.parquet")
    return root


def _as(role: str) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: User(
        id=role, username=role, email=f"{role}@example.com", roles=[role]
    )
    return TestClient(app)


def _user(*perms: str):
    return SimpleNamespace(id="u", has_permission=lambda p: "*" in perms or p in perms)


# ── G1 ────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("env", ["prod", "PROD", "Prod", "production", "PRODUCTION"])
def test_every_spelling_of_prod_is_protected(env):
    assert is_protected(env, protected=["prod", "production"])


def test_sandboxes_resolve_as_the_configuration_does():
    assert is_protected("sandbox_juan", protected=["sandbox"])  # gets sandbox's block
    assert not is_protected("sandbox_pedro", protected=["sandbox_juan"])
    assert not is_protected("dev", protected=["prod"])
    assert not is_protected("", protected=["prod"])


@pytest.mark.parametrize("env", ["PROD", "Production"])
def test_a_developer_cannot_reach_prod_by_spelling_it_otherwise(project, env):
    from ducta_server.services.governance import check_can_run

    with pytest.raises(HTTPException) as e:
        check_can_run(_user("pipeline.execute"), env, project)
    assert e.value.status_code == 403
    resp = _as("developer").get(
        "/api/projects/proj/datasets/bronze.etl.raw_data/preview",
        params={"source": str(project), "env": env, "limit": 2},
    )
    assert resp.status_code == 403, resp.text


def test_sentinel_never_acts_in_prod_spelt_otherwise(tmp_path):
    from ducta.ai.agents.sentinel.policy import may_act

    settings = SimpleNamespace(
        policy=SimpleNamespace(enabled=True, environments=["dev", "PROD"], pipelines=["*"]),
        protected=["prod"],
    )
    ok, why = may_act(tmp_path, settings, "PROD", "etl")
    assert not ok and "protected" in why


# ── G2 ────────────────────────────────────────────────────────────────────────


def _run_checks(role, root, checks):
    return _as(role).post(
        "/api/quality/run",
        params={"source": str(root)},
        json={"input_path": "data/input.csv", "format": "csv", "checks": checks},
    )


def test_quality_run_takes_the_guards_of_the_data_it_reads(project):
    # data/input.csv is source_data's path in prod too.
    assert _run_checks("developer", project, {"row_count": {"min": 1}}).status_code == 403
    on_pii = {"duplicates": {"columns": ["category"], "max_duplicate_rate": 1}}
    resp = _run_checks("operator", project, on_pii)
    assert resp.status_code == 403 and "metadata.pii" in resp.json()["message"]
    assert _run_checks("operator", project, {"range": {"column": "amount"}}).status_code == 200
    assert _run_checks("admin", project, on_pii).status_code == 200


# ── G3 ────────────────────────────────────────────────────────────────────────


def test_snapshot_fixtures_take_the_rows_permission_and_hide_pii(project):
    body = {"env": "prod", "rows": 5}
    url = "/api/projects/proj/nodes/extract/tests/snapshot"
    resp = _as("developer").post(url, params={"source": str(project)}, json=body)
    assert resp.status_code == 403, resp.text
    assert not (project / "tests/fixtures").exists()

    resp = _as("admin").post(url, params={"source": str(project)}, json=body)
    assert resp.status_code == 200, resp.text
    assert resp.json()["masked"] == {"source_data": ["category"]}
    fixture = pd.read_parquet(project / "tests/fixtures/extract/source_data.parquet")
    original = pd.read_csv(project / "data/input.csv").head(5)
    assert all(str(v).startswith("category_") for v in fixture["category"])
    # The same value, the same stand-in: duplicates and joins still behave.
    assert fixture["category"].nunique() == original["category"].nunique()
    assert list(fixture["amount"]) == list(original["amount"])


def test_mask_pii_keeps_each_values_kind_so_tests_still_run():
    from ducta.runs.node_tests import mask_pii

    df = pd.DataFrame(
        {
            "Email": ["ana@corp.com", None, "ana@corp.com"],
            "name": ["Ana", "Luis", None],
            "salary": [900, 1200, 900],
            "born": pd.to_datetime(["1990-01-02", None, "1980-05-06"]),
            "n": [1, 2, 3],
        }
    )
    out, masked = mask_pii(df, ["email", "name", "salary", "born"])
    assert masked == ["Email", "name", "salary", "born"]
    assert list(out["Email"]) == ["Email_1@example.invalid", None, "Email_1@example.invalid"]
    assert list(out["name"]) == ["name_1", "name_2", None]
    assert list(out["salary"]) == [1, 2, 1] and out["salary"].dtype == df["salary"].dtype
    assert out["born"].dtype == df["born"].dtype and pd.isna(out["born"][1])
    assert "1990" not in str(out["born"][0]) and list(out["n"]) == [1, 2, 3]
    assert list(df["Email"]) == ["ana@corp.com", None, "ana@corp.com"]  # caller's frame kept


# ── G4 ────────────────────────────────────────────────────────────────────────


def test_deleting_prod_quality_reports_takes_the_write_permission(project):
    from ducta.check.engine import ValidationPhaseRunner
    from ducta.runs.context import normalize_execution_context_paths
    from ducta_server.workspace.manager import WorkspaceManager

    ctx = WorkspaceManager(project).load_context("prod")
    normalize_execution_context_paths(ctx, project)
    ValidationPhaseRunner(context=ctx, fail_fast=False).run(
        dataset_name="gold.etl.final_output",
        df=pd.DataFrame({"a": [1]}),
        config={"checks": {"row_count": {"min": 1}}},
    )
    params = {"source": str(project), "env": "prod"}
    listed = _as("developer").get(
        "/api/quality/reports/gold.etl.final_output", params={**params, "all": True}
    )
    [run_id] = listed.json()["run_ids"]
    url = f"/api/quality/reports/gold.etl.final_output/{run_id}"
    # Whoever operates prod may tidy its reports (audited); a developer may not.
    for role, status in (("developer", 403), ("operator", 204)):
        assert _as(role).delete(url, params=params).status_code == status


# ── G5 ────────────────────────────────────────────────────────────────────────


def test_ai_quality_facts_carry_no_extremes_of_pii_columns():
    from ducta.ai.proposals import QualityFacts, _column_facts, _quality_problems

    col = SimpleNamespace(
        name="Salary", kind="numeric", null_rate=0.0, distinct_count=3,
        is_key_candidate=False, minimum=10.0, maximum=99.0,
    )  # fmt: skip
    other = SimpleNamespace(**{**vars(col), "name": "amount"})
    facts = _column_facts(SimpleNamespace(columns=[col, other]), ["salary"])
    assert "min" not in facts[0] and facts[1]["min"] == 10.0

    qf = QualityFacts("p", "f", "n", "ds", "dev", None, columns=facts, pii=["salary"])
    problems = _quality_problems({"checks": {"range": {"column": "Salary", "max": 1}}}, qf)
    assert any("personal data" in p for p in problems)


def test_ai_jobs_measuring_prod_take_the_rows_permission(project):
    resp = _as("developer").post(
        "/api/projects/proj/ai/jobs",
        params={"source": str(project)},
        json={"kind": "quality", "pipeline": "etl", "node": "extract", "env": "PROD"},
    )
    assert resp.status_code == 403, resp.text
    assert "data.read.protected" in resp.json()["message"]


# ── G6 / G7 ───────────────────────────────────────────────────────────────────


def _problems(root):
    from ducta.setting.project.loader import validate_project

    return {(p.code, p.dataset or p.pipeline) for p in governance_problems(validate_project(root))}


def test_governance_warnings_cover_pii_and_outputs_that_leave(project):
    catalog = project / "catalog.yaml"
    catalog.write_text(catalog.read_text().replace("pii: [category]", "pii: [categroy]"))
    found = _problems(project)
    assert ("governance.pii_unknown_column", "source_data") in found
    # gold leaves the project (no pipeline here reads it): who owns it?
    assert ("governance.missing_owner", "gold.etl.final_output") in found
    # bronze is read within its own pipeline only: not an output to own
    assert ("governance.missing_owner", "bronze.etl.raw_data") not in found
    # built from a PII dataset, says nothing of its own
    assert ("governance.pii_downstream", "bronze.etl.raw_data") in found

    text = catalog.read_text().replace("pii: [categroy]", "pii: [category]")
    text = text.replace(
        "  description: Raw data landed by `extract` (bronze)\n",
        "  description: Raw data landed by `extract` (bronze)\n  metadata: {pii: []}\n",
    )
    catalog.write_text(text)
    found = _problems(project)
    assert not {c for c, _ in found} & {"governance.pii_unknown_column"}
    assert ("governance.pii_downstream", "bronze.etl.raw_data") not in found


def test_known_columns_read_ddl_and_contract():
    entry = SimpleNamespace(
        schema_def="id INT, `e mail` STRING, tags ARRAY<STRUCT<a: INT, b: STRING>>",
        quality=SimpleNamespace(checks={"cols": {"type": "schema", "expected_columns": ["x"]}}),
    )
    assert known_columns(entry) == ["id", "e mail", "tags", "x"]


def test_ducta_check_json_lists_governance(project):
    import os

    env = {**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)}
    r = subprocess.run(
        [sys.executable, "-m", "ducta", "check", "--output-format", "json"],
        cwd=project, capture_output=True, text=True, env=env, timeout=300,
    )  # fmt: skip
    doc = json.loads(r.stdout[r.stdout.index("{") :])
    assert r.returncode == 0 and doc["ok"] is True
    codes = {p["code"] for p in doc["governance"]}
    assert "governance.missing_owner" in codes


# ── G8 ────────────────────────────────────────────────────────────────────────


def test_allowed_sensitive_reads_are_noted_for_the_audit(project):
    from ducta_server.services.data_access import DATA_READS, check_can_read_rows, hidden_columns

    reads: list = []
    token = DATA_READS.set(reads)
    try:
        check_can_read_rows(_user("data.read.protected"), "PROD", project)
        check_can_read_rows(_user("data.read.protected"), "dev", project)
        hidden_columns(_user("data.read.pii"), project, "dev", "source_data")
    finally:
        DATA_READS.reset(token)
    assert reads == [
        {"kind": "protected_rows", "env": "PROD"},
        {"kind": "pii", "env": "dev", "dataset": "source_data", "columns": ["category"]},
    ]


def test_audit_entries_carry_the_data_reads(tmp_path):
    from ducta_server.utils.audit import write_audit_entry

    log = tmp_path / "audit.log"
    write_audit_entry(
        user_id="u1", username="ana", method="GET", path="/x", status_code=200,
        audit_log_path=log, data_reads=[{"kind": "protected_rows", "env": "prod"}],
    )  # fmt: skip
    entry = json.loads(log.read_text())
    assert entry["method"] == "GET" and entry["data_reads"][0]["env"] == "prod"


def test_certificates_say_who_started_the_run():
    from ducta.core.certificate import _started_by

    by_server = _started_by(SimpleNamespace(started_by={"via": "server", "user_id": "u1"}))
    assert by_server == {"via": "server", "user_id": "u1"}
    assert _started_by(SimpleNamespace(started_by={"via": "server", "user_id": None})) == {
        "via": "server"
    }
    assert _started_by(SimpleNamespace())["via"] == "cli"


def test_server_runs_mark_the_user_on_the_context():
    from ducta_server.execution.runner import RunSpec, mark_started_by

    ctx = SimpleNamespace()
    mark_started_by(
        ctx, RunSpec(source_path=Path("."), pipeline_name="p", env="dev", started_by="u7")
    )
    assert ctx.started_by == {"via": "server", "user_id": "u7"}


# ── G9 ────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("env", ["prod", "PROD"])
def test_protected_run_output_stays_visible_and_is_audited(project, env):
    from ducta_server.routes.execution import note_protected_run_output
    from ducta_server.services.data_access import DATA_READS

    record = SimpleNamespace(id="e1", env=env, project_id=None)
    note_protected_run_output(record, root=project)  # auth off: nothing, no error
    reads: list = []
    token = DATA_READS.set(reads)
    try:
        note_protected_run_output(record, root=project)
        note_protected_run_output(SimpleNamespace(id="e2", env="dev"), root=project)
    finally:
        DATA_READS.reset(token)
    assert reads == [{"kind": "protected_run_output", "env": env, "execution": "e1"}]


def test_ducta_check_sums_advice_up_per_kind():
    from ducta.console.commands.config_cmds import _governance_summary
    from ducta.setting.problems import Problem

    def p(code, ds, severity="info"):
        return Problem(severity=severity, code=code, message=f"m {ds}", dataset=ds)

    lines = _governance_summary(
        [p("governance.missing_owner", f"d{i}") for i in range(5)]
        + [p("governance.pii_unknown_column", "src", "warning")]
    )
    assert lines[0] == ("warning", "m src")  # a mistake: shown as it is
    assert lines[1][1].startswith("5 pipeline(s) or dataset(s) without an owner")
    assert "d0, d1, d2 and 2 more" in lines[1][1]
    assert len(lines) == 3  # plus where the details are
