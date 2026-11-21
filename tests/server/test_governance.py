"""Governance: protected environments take an operator, and missing owners/contracts are reported."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ducta.project_store.governance import governance_problems
from ducta_server.dependencies import get_current_user
from ducta_server.main import create_app
from ducta_server.models.auth import User

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

    from ducta_server.services.governance import check_can_run

    developer = User(id="d", username="d", email="d@x.io", roles=["developer"])
    operator = User(id="o", username="o", email="o@x.io", roles=["operator"])
    with pytest.raises(HTTPException) as e:
        check_can_run(developer, "prod", batch)
    assert e.value.status_code == 403 and "protected" in e.value.detail
    check_can_run(operator, "prod", batch)
    check_can_run(developer, "dev", batch)


def test_a_project_adds_protected_environments_but_cannot_remove_the_floor(batch, monkeypatch):
    from ducta.project_store.governance import FLOOR_ENV, protected_environments

    monkeypatch.delenv(FLOOR_ENV, raising=False)
    text = (batch / "ducta.yaml").read_text()
    (batch / "ducta.yaml").write_text(text + "\ngovernance:\n  protected_environments: [sandbox]\n")
    assert protected_environments(batch) == ["prod", "production", "sandbox"]


def test_the_floor_is_the_servers_setting(batch, monkeypatch):
    from ducta.project_store.governance import FLOOR_ENV, protected_environments

    text = (batch / "ducta.yaml").read_text()
    (batch / "ducta.yaml").write_text(text + "\ngovernance:\n  protected_environments: []\n")
    monkeypatch.setenv(FLOOR_ENV, "live, prod")
    assert protected_environments(batch) == ["live", "prod"]
    monkeypatch.setenv(FLOOR_ENV, "")
    assert protected_environments(batch) == []


def test_a_developer_cannot_unprotect_prod_by_editing_the_project(batch, monkeypatch):
    """Found 2026-11-20: `protected_environments: [nothing]` in ducta.yaml, then 202 in prod."""
    from ducta.project_store.governance import FLOOR_ENV

    monkeypatch.delenv(FLOOR_ENV, raising=False)
    monkeypatch.chdir(batch.parent)
    text = (batch / "ducta.yaml").read_text()
    (batch / "ducta.yaml").write_text(text + "\ngovernance:\n  protected_environments: [nothing]\n")
    with _client(["developer"]) as c:
        r = c.post(
            "/api/projects/batch/pipelines/silver.clean/execute",
            params={"source": str(batch)},
            json={"env": "prod", "dry_run": True},
        )
    assert r.status_code == 403, r.text


def test_sentinel_keeps_out_of_the_floor_too(batch, monkeypatch):
    from ducta.ai.agents.sentinel.policy import Settings as SentinelSettings
    from ducta.project_store.governance import FLOOR_ENV

    monkeypatch.delenv(FLOOR_ENV, raising=False)
    text = (batch / "ducta.yaml").read_text()
    (batch / "ducta.yaml").write_text(text + "\ngovernance:\n  protected_environments: []\n")
    settings = SentinelSettings.of(batch)
    assert settings is not None and "prod" in settings.protected


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
    from ducta.setting.project.loader import validate_project

    problems = governance_problems(validate_project(batch))
    codes = {p.code for p in problems}
    assert "governance.missing_owner" in codes
    assert all(p.severity == "info" for p in problems)
    text = (batch / "ducta.yaml").read_text()
    (batch / "ducta.yaml").write_text(
        text + "\ngovernance:\n  warnings: {missing_owner: false, missing_contract: false}\n"
    )
    assert governance_problems(validate_project(batch)) == []


def test_sweep_route_refuses_a_developer_in_prod(tmp_path, monkeypatch):
    """`/sweep` launches real runs: it takes the same protected-environment check as `/execute`."""
    from ducta.console.templates import TemplateGenerator, TemplateType

    monkeypatch.chdir(tmp_path)
    root = tmp_path / "proj"
    TemplateGenerator(root).generate_project(TemplateType.MEDALLION_BASIC, "proj")
    body = {"env": "prod", "sweep": {"alpha": [1, 2]}}
    url = "/api/projects/proj/pipelines/etl/sweep"
    with _client(["developer"]) as c:
        r = c.post(url, params={"source": str(root)}, json=body)
        assert r.status_code == 403, r.text
        assert "protected" in r.text
        # A role with the permission passes the check (whatever the pipeline then does).
    with _client(["operator"]) as c:
        r = c.post(url, params={"source": str(root)}, json=body)
        assert r.status_code != 403, r.text
