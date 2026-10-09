"""Governance: protected environments take an operator, and missing owners/contracts are reported."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ducta.api.dependencies import get_current_user
from ducta.api.main import create_app
from ducta.api.models.auth import User
from ducta.api.services.governance import governance_problems

DEMOS = Path.home() / "Desktop" / "demo_ducta" / "projects"


@pytest.fixture
def batch(tmp_path):
    if not (DEMOS / "batch").is_dir():
        pytest.skip("demo_ducta projects not on this machine")
    root = tmp_path / "batch"
    shutil.copytree(
        DEMOS / "batch",
        root,
        ignore=shutil.ignore_patterns("data", ".ducta", "logs", "models", "lib", ".env"),
    )
    return root


def _client(roles) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: User(
        id="u", username="u", email="u@example.com", roles=roles
    )
    return TestClient(app)


def test_only_an_operator_or_admin_runs_in_prod(batch):
    from fastapi import HTTPException

    from ducta.api.services.governance import check_can_run

    developer = User(id="d", username="d", email="d@x.io", roles=["developer"])
    operator = User(id="o", username="o", email="o@x.io", roles=["operator"])
    with pytest.raises(HTTPException) as e:
        check_can_run(developer, "prod", batch)
    assert e.value.status_code == 403 and "protected" in e.value.detail
    check_can_run(operator, "prod", batch)
    check_can_run(developer, "dev", batch)


def test_protected_environments_are_the_projects_choice(batch):
    from ducta.api.services.governance import protected_environments

    text = (batch / "ducta.yaml").read_text()
    (batch / "ducta.yaml").write_text(text + "\ngovernance:\n  protected_environments: [sandbox]\n")
    assert protected_environments(batch) == ["sandbox"]


def test_execute_route_refuses_a_developer_in_prod(batch, monkeypatch):
    monkeypatch.chdir(batch.parent)
    with _client(["developer"]) as c:
        r = c.post(
            "/api/projects/batch/pipelines/silver.clean/execute",
            params={"source": str(batch)},
            json={"env": "prod", "dry_run": True},
        )
        assert r.status_code == 403, r.text
        g = c.get("/api/projects/batch/governance", params={"source": str(batch)}).json()
    assert g["protected_environments"] == ["prod", "production"]
    assert g["can_run_protected"] is False


def test_governance_warnings_and_turning_them_off(batch):
    from ducta.setting.project_loader import validate_project

    problems = governance_problems(validate_project(batch))
    codes = {p.code for p in problems}
    assert "governance.missing_owner" in codes
    assert all(p.severity == "info" for p in problems)
    text = (batch / "ducta.yaml").read_text()
    (batch / "ducta.yaml").write_text(
        text + "\ngovernance:\n  warnings: {missing_owner: false, missing_contract: false}\n"
    )
    assert governance_problems(validate_project(batch)) == []
