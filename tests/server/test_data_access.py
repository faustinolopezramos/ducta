"""Who sees a dataset's rows, and which values (2026-11-20 security review).

Rows of a protected environment (prod) take ``data.read.protected`` (operator, admin);
the columns a dataset lists in ``metadata.pii`` are masked for whoever lacks
``data.read.pii`` (developer, admin), and a check naming one is refused for them.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ducta_server.dependencies import get_current_user
from ducta_server.main import create_app
from ducta_server.models.auth import User
from ducta_server.services.data_access import MASK, mask_rows, names_in


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
    return root


def _as(role: str) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: User(
        id=role, username=role, email=f"{role}@example.com", roles=[role]
    )
    return TestClient(app)


def _preview(role, root, env):
    return _as(role).get(
        "/api/projects/proj/datasets/source_data/preview",
        params={"source": str(root), "env": env, "limit": 5},
    )


@pytest.mark.parametrize("role, status", [("viewer", 403), ("developer", 403),
                                          ("operator", 200), ("admin", 200)])  # fmt: skip
def test_prod_rows_take_their_own_permission(project, role, status):
    resp = _preview(role, project, "prod")
    assert resp.status_code == status, resp.text
    if status == 403:
        assert "data.read.protected" in resp.json()["message"]


@pytest.mark.parametrize("role, masked", [("viewer", True), ("operator", True),
                                          ("developer", False), ("admin", False)])  # fmt: skip
def test_pii_columns_are_masked_without_the_permission(project, role, masked):
    resp = _preview(role, project, "dev")
    assert resp.status_code == 200, resp.text
    rows = resp.json()["rows"]
    assert rows
    assert all((r["category"] == MASK) is masked for r in rows)
    assert all(r["amount"] != MASK for r in rows)  # other columns as they are


def _failing(role, root, params, env="dev"):
    return _as(role).post(
        "/api/projects/proj/quality/failing-rows",
        params={"source": str(root)},
        json={"dataset": "source_data", "env": env, "check": "business_rules", "params": params},
    )


def test_failing_rows_mask_pii_and_refuse_rules_that_name_it(project):
    ok = _failing("viewer", project, {"rule_type": "sql", "rules": ["amount < 0"]})
    assert ok.status_code == 200, ok.text
    assert all(r["category"] == MASK for r in ok.json()["rows"])
    # A rule on a PII column would tell its values one count at a time.
    probe = _failing("viewer", project, {"rule_type": "sql", "rules": ["category LIKE 'a%'"]})
    assert probe.status_code == 403 and "metadata.pii" in probe.json()["message"]
    assert (
        _failing("developer", project, {"rule_type": "sql", "rules": ["category LIKE 'a%'"]})
    ).status_code == 200
    assert _failing("viewer", project, {"rules": ["amount < 0"]}, env="prod").status_code == 403


def test_trying_checks_on_a_pii_column_is_refused_without_the_permission(project):
    body = {"dataset": "source_data", "env": "dev",
            "checks": {"null_rate": {"columns": ["category"], "max_null_rate": 0}}}  # fmt: skip
    resp = _as("operator").post(
        "/api/projects/proj/quality/try", params={"source": str(project)}, json=body
    )
    assert resp.status_code == 403, resp.text
    resp = _as("operator").post(
        "/api/projects/proj/quality/try",
        params={"source": str(project)},
        json={**body, "env": "prod", "checks": {"null_rate": {"columns": ["amount"]}}},
    )
    assert resp.status_code == 200, resp.text  # operators read prod; amount is not PII


def test_masking_keeps_nulls_and_matches_names_case_insensitively():
    rows = [{"Email": "a@b.c", "n": 1}, {"Email": None, "n": 2}]
    assert mask_rows(rows, {"email"}) == [{"Email": MASK, "n": 1}, {"Email": None, "n": 2}]
    assert mask_rows(rows, set()) is rows


def test_names_in_finds_every_word_of_a_config():
    assert {"email", "amount", "max"} <= names_in(
        {"rules": ["lower(email) = 'x'"], "range": {"column": "amount", "max": 1}}
    )
