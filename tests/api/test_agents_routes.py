"""Ducta's agents over HTTP: Architect as AI jobs, Sentinel's incidents and controls."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ai" / "agents"))
from test_ai_routes import _client, _configure, _use, _wait, home  # noqa: E402,F401
from test_architect import BLUEPRINT, GOLD, SALES, SILVER  # noqa: E402

from ducta.ai.agents.sentinel.engine import Sentinel  # noqa: E402
from ducta.ai.agents.sentinel.incidents import Incidents  # noqa: E402
from ducta.ai.agents.sentinel.triage import RunEvent  # noqa: E402

POLICY = (
    "\nsentinel: {enabled: true, environments: [dev], retry_infra: {backoff_seconds: [3600]}}\n"
)
INFRA = "py4j.protocol.Py4JJavaError: Connection refused"


@pytest.fixture
def proj(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "proj"
    shutil.copytree(SALES, root)
    (root / "ducta.yaml").write_text((root / "ducta.yaml").read_text() + POLICY)
    return root


class _NoRun:
    def rerun(self, *a, **k):
        return None


def _incident(root, env="dev"):
    sentinel = Sentinel(root, _NoRun(), notify=False)
    return sentinel.handle(
        RunEvent(
            env=env,
            pipeline="bronze.sales",
            status="failed",
            run_id="r1",
            error=INFRA,
            failed_nodes=["land_orders"],
        )
    )


# ── Architect ───────────────────────────────────────────────────────────────


def test_architect_plans_then_builds_through_jobs(home, proj, monkeypatch):
    _configure(home)
    _use(monkeypatch, f"```yaml blueprint\n{BLUEPRINT}```", SILVER, GOLD)
    client = _client()
    src = {"source": str(proj)}
    r = client.post(
        "/api/projects/proj/ai/jobs",
        params=src,
        json={"kind": "architect_plan", "request": "revenue per store"},
    )
    assert r.status_code == 202, r.text
    plan = _wait(client, proj, r.json()["id"])
    assert plan["status"] == "done" and plan["ok"], plan
    r = client.post(f"/api/projects/proj/ai/drafts/{plan['draft_id']}/apply", params=src, json={})
    assert r.status_code == 409  # a blueprint is built, not applied

    r = client.post(
        "/api/projects/proj/ai/jobs",
        params=src,
        json={"kind": "architect_build", "draft_id": plan["draft_id"]},
    )
    built = _wait(client, proj, r.json()["id"])
    assert built["status"] == "done" and built["ok"], built
    r = client.post(f"/api/projects/proj/ai/drafts/{built['draft_id']}/apply", params=src, json={})
    assert r.status_code == 200, r.text
    assert (proj / "pipelines" / "gold.stores.yaml").is_file()


def test_architect_questions_come_back_in_the_job(home, proj, monkeypatch):
    _configure(home)
    _use(monkeypatch, "```yaml questions\nquestions:\n  - Which store?\n```")
    client = _client()
    r = client.post(
        "/api/projects/proj/ai/jobs",
        params={"source": str(proj)},
        json={"kind": "architect_plan", "request": "revenue"},
    )
    job = _wait(client, proj, r.json()["id"])
    assert job["status"] == "done" and job["questions"] == ["Which store?"] and not job["draft_id"]


def test_only_a_blueprint_is_built(home, proj):
    _configure(home)
    r = _client().post(
        "/api/projects/proj/ai/jobs",
        params={"source": str(proj)},
        json={"kind": "architect_build", "draft_id": "nope"},
    )
    assert r.status_code == 404


# ── Sentinel ────────────────────────────────────────────────────────────────


def test_status_and_incidents_can_be_read_by_a_viewer(home, proj):
    _incident(proj)
    client = _client("viewer")
    src = {"source": str(proj)}
    status = client.get("/api/projects/proj/sentinel/status", params=src).json()
    assert status["enabled"] and status["environments"] == ["dev"] and status["active"] == 1
    assert "prod" in status["protected"]
    found = client.get("/api/projects/proj/sentinel/incidents", params=src).json()
    assert found[0]["status"] == "remediating" and found[0]["runbook"] == "retry"
    one = client.get(f"/api/projects/proj/sentinel/incidents/{found[0]['id']}", params=src).json()
    assert one["timeline"]


def test_a_developer_cannot_manage_sentinel(home, proj):
    incident = _incident(proj)
    r = _client("developer").post(
        f"/api/projects/proj/sentinel/incidents/{incident.id}/ignore",
        params={"source": str(proj)},
        json={},
    )
    assert r.status_code == 403


def test_an_operator_resolves_an_incident_and_pauses_sentinel(home, proj):
    incident = _incident(proj)
    client = _client("operator")
    src = {"source": str(proj)}
    r = client.post(
        f"/api/projects/proj/sentinel/incidents/{incident.id}/resolve",
        params=src,
        json={"note": "fixed the db"},
    )
    assert r.status_code == 200 and r.json()["status"] == "resolved"
    assert Incidents(proj).get(incident.id).pending is None
    r = client.post(
        f"/api/projects/proj/sentinel/incidents/{incident.id}/resolve", params=src, json={}
    )
    assert r.status_code == 409
    paused = client.post(
        "/api/projects/proj/sentinel/pause", params=src, json={"note": "maintenance"}
    ).json()
    assert paused["paused"] is True
    assert (
        client.post("/api/projects/proj/sentinel/resume", params=src, json={}).json()["paused"]
        is False
    )


def test_a_retry_is_never_sent_to_a_protected_environment(home, proj):
    incident = _incident(proj, env="prod")
    r = _client("operator").post(
        f"/api/projects/proj/sentinel/incidents/{incident.id}/retry",
        params={"source": str(proj)},
        json={},
    )
    assert r.status_code == 403 and "protected" in r.json()["message"]


# ── 2026-10-15 analysis: proposals are AI jobs, people's changes take the lock ─


CODE_ERROR = (
    'Traceback (most recent call last):\n  File "pipelines/sales.py", line 9\nValueError: boom'
)


def _code_incident(root):
    return Sentinel(root, _NoRun(), notify=False).handle(
        RunEvent(
            env="dev",
            pipeline="silver.sales",
            status="failed",
            run_id="r2",
            error=CODE_ERROR,
            failed_nodes=["clean_orders"],
        )
    )


def test_a_proposal_is_an_ai_job_for_whoever_uses_ai(home, proj, monkeypatch):
    _configure(home)
    _use(monkeypatch, "**What happened** it broke.", "no blocks")
    incident = _code_incident(proj)
    src = {"source": str(proj)}
    body = {"kind": "sentinel_propose", "incident_id": incident.id}
    # An operator manages incidents but does not use the model.
    assert (
        _client("operator").post("/api/projects/proj/ai/jobs", params=src, json=body).status_code
        == 403
    )
    client = _client("developer")
    r = client.post("/api/projects/proj/ai/jobs", params=src, json=body)
    assert r.status_code == 202, r.text
    job = _wait(client, proj, r.json()["id"])
    assert job["status"] == "done" and job["incident_id"] == incident.id, job
    found = Incidents(proj).get(incident.id)
    assert found.links.get("explanation") and found.links.get("draft") == job["draft_id"]
    assert any(e["actor"] == "developer" for e in found.timeline)
    # The old synchronous route is gone.
    r = _client("operator").post(
        f"/api/projects/proj/sentinel/incidents/{incident.id}/propose", params=src, json={}
    )
    assert r.status_code == 422


def test_a_proposal_needs_an_incident(home, proj, monkeypatch):
    _configure(home)
    _use(monkeypatch)
    r = _client().post(
        "/api/projects/proj/ai/jobs",
        params={"source": str(proj)},
        json={"kind": "sentinel_propose", "incident_id": "20261015-000000-abcdef"},
    )
    assert r.status_code == 404


def test_a_retry_is_the_persons_run(home, proj, monkeypatch):
    calls = []

    class Manager:
        def execute(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr("ducta.api.execution.manager.get_execution_manager", lambda: Manager())
    incident = _incident(proj)
    client = _client("operator")
    src = {"source": str(proj)}
    r = client.post(
        f"/api/projects/proj/sentinel/incidents/{incident.id}/retry", params=src, json={}
    )
    assert r.status_code == 200, r.text
    assert calls[0]["user_id"] == "operator" and r.json()["pending"]["action"] == "running"
    client.post(f"/api/projects/proj/sentinel/incidents/{incident.id}/resolve", params=src, json={})
    r = client.post(
        f"/api/projects/proj/sentinel/incidents/{incident.id}/retry", params=src, json={}
    )
    assert r.status_code == 409 and len(calls) == 1


def test_a_persons_change_waits_for_the_engine(home, proj, monkeypatch):
    from ducta.ai.agents.sentinel import engine

    incident = _incident(proj)
    monkeypatch.setattr(engine, "LOCK_WAIT", 0.3)
    with engine.engine_lock(proj) as got:
        assert got
        r = _client("operator").post(
            f"/api/projects/proj/sentinel/incidents/{incident.id}/resolve",
            params={"source": str(proj)},
            json={},
        )
    assert r.status_code == 409 and "busy" in r.json()["message"]
    assert Incidents(proj).get(incident.id).status == "remediating"


def test_a_blueprint_draft_carries_its_design_and_a_build_names_each_module(
    home, proj, monkeypatch
):
    _configure(home)
    _use(monkeypatch, f"```yaml blueprint\n{BLUEPRINT}```", SILVER, GOLD)
    client = _client()
    src = {"source": str(proj)}
    r = client.post(
        "/api/projects/proj/ai/jobs", params=src, json={"kind": "architect_plan", "request": "x"}
    )
    plan = _wait(client, proj, r.json()["id"])
    draft = client.get(f"/api/projects/proj/ai/drafts/{plan['draft_id']}", params=src).json()
    assert draft["kind"] == "blueprint"
    assert set(draft["blueprint"]["pipelines"]) == {"silver.stores", "gold.stores"}
    assert "silver.sales.orders_by_store" in draft["blueprint"]["datasets"]
    assert draft["blueprint_yaml"].startswith("name: store_revenue")
    assert isinstance(draft["warnings"], list)

    r = client.post(
        "/api/projects/proj/ai/jobs",
        params=src,
        json={"kind": "architect_build", "draft_id": plan["draft_id"]},
    )
    built = _wait(client, proj, r.json()["id"])
    assert [(a["number"], a["files"]) for a in built["attempts"]] == [
        (1, ["pipelines/silver_stores.py"]),
        (2, ["pipelines/gold_stores.py"]),
    ]
    other = client.get(f"/api/projects/proj/ai/drafts/{built['draft_id']}", params=src).json()
    assert other["blueprint"] is None and other["warnings"] == []
