"""Ducta Sentinel: triage by rules, safe re-runs outside protected environments,
proposals for the rest — and never twice, never in prod, never over budget."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from ducta.ai.agents import audit
from ducta.ai.agents.sentinel import policy as gate
from ducta.ai.agents.sentinel.engine import Sentinel, engine_lock
from ducta.ai.agents.sentinel.incidents import Incidents
from ducta.ai.agents.sentinel.triage import RunEvent, decide
from ducta.api.services import run_certificates

sys.path.insert(0, str(Path(__file__).parents[1]))
from test_builder import FakeProvider  # noqa: E402

SALES = (
    Path(__file__).parents[3]
    / "src"
    / "ducta"
    / "skills"
    / "ducta"
    / "assets"
    / "examples"
    / "sales"
)
POLICY = """
sentinel:
  enabled: true
  environments: [dev]
  retry_infra: {max_attempts: 2, backoff_seconds: [0]}
  max_actions_per_day: 10
"""
INFRA = "py4j.protocol.Py4JJavaError: Connection refused (Connection refused)"


class FakeExecutor:
    def __init__(self, *outcomes: str):
        self.outcomes = list(outcomes)
        self.calls: List[Dict[str, Any]] = []

    def rerun(self, root, env, pipeline, nodes, reuse_upstream) -> Optional[RunEvent]:
        self.calls.append(
            {"env": env, "pipeline": pipeline, "nodes": nodes, "reuse": reuse_upstream}
        )
        status = self.outcomes.pop(0) if self.outcomes else "success"
        return RunEvent(
            env=env,
            pipeline=pipeline,
            status=status,
            run_id=f"rerun-{len(self.calls)}",
            error="" if status == "success" else INFRA,
            failed_nodes=[] if status == "success" else ["land_orders"],
            actor="sentinel",
        )


@pytest.fixture
def certs(monkeypatch):
    found: List[tuple] = []
    monkeypatch.setattr(
        run_certificates,
        "certificates",
        lambda root, env: iter([(e, c) for e, c in found if env is None or e == env]),
    )
    return found


@pytest.fixture
def sales(tmp_path, certs):
    root = tmp_path / "sales"
    shutil.copytree(SALES, root)
    (root / "ducta.yaml").write_text((root / "ducta.yaml").read_text() + POLICY)
    return root


def _failed(env="dev", pipeline="bronze.sales", error=INFRA, node="land_orders", run_id="r1"):
    return RunEvent(
        env=env, pipeline=pipeline, status="failed", run_id=run_id, error=error, failed_nodes=[node]
    )


def _cert(
    run_id, pipeline="bronze.sales", status="success", started="2026-10-15T10:00:00+00:00", **kw
):
    return {
        "run_id": run_id,
        "pipeline": pipeline,
        "status": status,
        "started_at": started,
        "duration_seconds": kw.pop("duration", 10.0),
        "error": kw.pop("error", None),
        "nodes": kw.pop("nodes", []),
        **kw,
    }


# ── the decision table ──────────────────────────────────────────────────────


def test_an_infrastructure_failure_with_overwritten_outputs_is_retried(sales):
    decision = decide(sales, _failed(), {"kind": "infra"})
    assert (decision.runbook, decision.level) == ("retry", "L1")


@pytest.mark.parametrize(
    "error",
    [
        "ERROR: Missing credentials for shop_db. Set environment variables",
        "java.lang.ClassNotFoundException: org.postgresql.Driver",
        "FATAL: password authentication failed for user etl",
    ],
)
def test_an_infrastructure_failure_a_rerun_cannot_fix_is_escalated(sales, error):
    decision = decide(sales, _failed(error=error), {"kind": "infra"})
    assert decision.runbook == "escalate" and "cannot fix" in decision.reason


def test_an_appended_output_is_never_retried(sales):
    catalog = sales / "catalog.yaml"
    catalog.write_text(
        catalog.read_text().replace(
            "  description: Orders as copied from the shop database\n",
            "  description: Orders as copied from the shop database\n  write: {mode: append}\n",
        )
    )
    decision = decide(sales, _failed(), {"kind": "infra"})
    assert decision.runbook == "escalate" and "twice" in decision.reason


@pytest.mark.parametrize(
    "kind, runbook",
    [("quality_gate", "propose_quality"), ("code", "propose_fix"), ("config", "propose_fix")],
)
def test_what_a_person_must_fix_is_proposed(sales, kind, runbook):
    assert decide(sales, _failed(), {"kind": kind}).runbook == runbook


def test_a_data_failure_downstream_waits_for_its_upstream(sales):
    decision = decide(
        sales, _failed(pipeline="silver.sales", node="clean_orders"), {"kind": "data"}
    )
    assert decision.runbook == "wait_upstream" and decision.upstream == ["bronze.sales"]


# ── L1: re-runs, only where allowed ─────────────────────────────────────────


def test_a_failure_in_dev_is_rerun_and_resolved(sales):
    executor = FakeExecutor("success")
    sentinel = Sentinel(sales, executor, notify=False)
    incident = sentinel.handle(_failed())
    assert incident.status == "remediating" and incident.pending["action"] == "rerun"
    sentinel.tick()
    assert executor.calls == [
        {"env": "dev", "pipeline": "bronze.sales", "nodes": ["land_orders"], "reuse": True}
    ]
    assert Incidents(sales).get(incident.id).status == "resolved"
    actions = [e["action"] for e in audit.entries(sales, "sentinel")]
    assert actions == ["open", "rerun", "rerun_result", "resolve"]


def test_prod_is_never_touched(sales):
    executor = FakeExecutor()
    sentinel = Sentinel(sales, executor, notify=False)
    incident = sentinel.handle(_failed(env="prod"))
    sentinel.tick()
    assert executor.calls == []
    assert incident.status == "escalated" and "protected" in incident.reason


def test_retries_stop_at_the_limit(sales):
    executor = FakeExecutor("failed", "failed", "failed")
    sentinel = Sentinel(sales, executor, notify=False)
    incident = sentinel.handle(_failed())
    for _ in range(4):
        sentinel.tick()
    final = Incidents(sales).get(incident.id)
    assert len(executor.calls) == 2
    assert final.status == "escalated" and "still failing after 2" in final.reason


def test_a_paused_sentinel_does_not_act(sales):
    gate.pause(sales, by="ops", reason="maintenance")
    incident = Sentinel(sales, FakeExecutor(), notify=False).handle(_failed())
    assert incident.status == "escalated" and "paused" in incident.reason
    gate.resume(sales)
    assert not gate.is_paused(sales)


def test_the_daily_budget_is_kept(sales):
    (sales / "ducta.yaml").write_text(
        (sales / "ducta.yaml")
        .read_text()
        .replace("max_actions_per_day: 10", "max_actions_per_day: 1")
    )
    executor = FakeExecutor("success", "success")
    sentinel = Sentinel(sales, executor, notify=False)
    sentinel.handle(_failed())
    sentinel.tick()
    second = sentinel.handle(_failed(pipeline="silver.sales", node="clean_orders", run_id="r2"))
    assert second.status == "escalated" and "budget" in second.reason
    assert len(executor.calls) == 1


def test_nothing_happens_when_the_project_did_not_enable_it(tmp_path, certs):
    root = tmp_path / "sales"
    shutil.copytree(SALES, root)
    assert Sentinel(root, FakeExecutor(), notify=False).handle(_failed()) is None
    assert Incidents(root).list() == []


def test_a_downstream_run_waits_then_reruns_when_its_upstream_succeeds(sales):
    executor = FakeExecutor("success")
    sentinel = Sentinel(sales, executor, notify=False)
    data_error = "AnalysisException: Path does not exist: data/dev/bronze/sales/orders"
    incident = sentinel.handle(
        _failed(pipeline="silver.sales", node="clean_orders", error=data_error)
    )
    assert incident.pending["action"] == "wait_upstream"
    sentinel.tick()
    assert executor.calls == []
    sentinel.handle(RunEvent(env="dev", pipeline="bronze.sales", status="success", run_id="up"))
    sentinel.tick()
    assert executor.calls and executor.calls[0]["pipeline"] == "silver.sales"
    assert Incidents(sales).get(incident.id).status == "resolved"


def test_a_repeated_failure_is_one_incident(sales):
    sentinel = Sentinel(sales, FakeExecutor(), notify=False)
    first = sentinel.handle(_failed(error="Traceback ... ValueError: boom", run_id="a"))
    again = sentinel.handle(_failed(error="Traceback ... ValueError: boom", run_id="b"))
    assert first.id == again.id and again.failures == 2
    assert len(Incidents(sales).list(status="active")) == 1


# ── L2: proposals ───────────────────────────────────────────────────────────


def test_a_code_failure_is_explained_and_a_fix_is_drafted_never_applied(sales):
    provider = FakeProvider("**What happened** it broke.", "no blocks")
    sentinel = Sentinel(sales, FakeExecutor(), notify=False, provider=provider)
    error = (
        'Traceback (most recent call last):\n  File "pipelines/sales.py", line 9\nValueError: boom'
    )
    handled = sentinel.handle(_failed(pipeline="silver.sales", node="clean_orders", error=error))
    assert handled.status == "escalated" and handled.runbook == "propose_fix"
    assert not handled.links and provider.calls == []  # not under the engine's lock
    sentinel._after_pass()
    incident = Incidents(sales).get(handled.id)
    assert incident.status == "escalated" and incident.runbook == "propose_fix"
    assert incident.links.get("explanation") and incident.links.get("draft")
    assert (sales / ".ducta" / "ai" / "drafts" / f"{incident.links['draft']}.json").is_file()
    assert "raise" not in (sales / "pipelines" / "sales.py").read_text()  # nothing written


# ── scanning, locking, the server ───────────────────────────────────────────


def test_a_first_scan_takes_history_as_seen(sales, certs):
    certs.append(("dev", _cert("old", status="failed", error=INFRA)))
    sentinel = Sentinel(sales, FakeExecutor(), notify=False)
    sentinel.scan("dev")
    assert Incidents(sales).list() == []
    certs.append(
        ("dev", _cert("new", status="failed", error=INFRA, started="2026-10-15T11:00:00+00:00"))
    )
    sentinel.scan("dev")
    sentinel.scan("dev")
    assert len(Incidents(sales).list()) == 1


def test_a_late_pipeline_opens_an_sla_incident(sales, certs):
    path = sales / "pipelines" / "bronze.sales.yaml"
    path.write_text(
        path.read_text().replace(
            "requires_dates: false", "requires_dates: false\nmetadata: {sla: 1h}"
        )
    )
    certs.append(("dev", _cert("old", started="2020-01-01T00:00:00+00:00")))
    sentinel = Sentinel(sales, FakeExecutor(), notify=False)
    sentinel.scan("dev")
    found = Incidents(sales).list(status="active")
    assert [(i.kind, i.status) for i in found] == [("sla_miss", "escalated")]


def test_one_pass_at_a_time(sales):
    with engine_lock(sales) as got:
        assert got
        report = Sentinel(sales, FakeExecutor(), notify=False).run_once(["dev"])
    assert report.skipped


def test_the_server_hook_queues_a_rerun_as_sentinel(sales, monkeypatch):
    from ducta.ai.agents.sentinel import server

    calls = []

    class Manager:
        def execute(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr("ducta.api.execution.manager.get_execution_manager", lambda: Manager())
    monkeypatch.setattr(
        "ducta.api.routes.execution.run_errors",
        lambda _id: [{"node_id": "land_orders", "message": INFRA}],
    )
    record = {
        "id": "e1",
        "pipeline_name": "bronze.sales",
        "env": "dev",
        "status": "failed",
        "error_message": INFRA,
    }
    server.on_run_finished(sales, "sales", record)
    assert calls and calls[0]["user_id"] == "sentinel" and calls[0]["node_names"] == ["land_orders"]


def test_the_cli_executor_reads_the_runs_certificate(sales, certs, monkeypatch):
    from ducta.ai.agents import runs
    from ducta.ai.agents.sentinel.actions import CliExecutor

    def fake_run(root, env, pipeline, **kw):
        certs.append(("dev", _cert("cli-1", started="2999-01-01T00:00:00+00:00")))
        return runs.RunOutcome(0, "ok")

    monkeypatch.setattr(runs, "run_pipeline", fake_run)
    event = CliExecutor().rerun(sales, "dev", "bronze.sales", [], False)
    assert (event.run_id, event.status, event.actor) == ("cli-1", "success", "sentinel")


# ── what the 2026-10-15 analysis found ──────────────────────────────────────


def _hourly(n, status="success"):
    from datetime import datetime, timedelta, timezone

    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [
        (
            "dev",
            _cert(
                f"h{i:05d}",
                status=status,
                started=(start + timedelta(hours=i)).isoformat(),
                ended_at=(start + timedelta(hours=i, minutes=5)).isoformat(),
                error=None if status == "success" else INFRA,
            ),
        )
        for i in range(n)
    ]


def test_a_long_history_is_never_triaged_again(sales, certs):
    # More runs than any list of ids would hold: old runs stay below the mark.
    certs.extend(_hourly(2100, status="failed"))
    sentinel = Sentinel(sales, FakeExecutor(), notify=False)
    for _ in range(3):
        sentinel.report.events = 0
        sentinel.scan("dev")
        assert sentinel.report.events == 0
    assert Incidents(sales).list() == []
    certs.append(
        ("dev", _cert("next", status="failed", error=INFRA, started="2026-04-01T00:00:00+00:00"))
    )
    sentinel.scan("dev")
    assert len(Incidents(sales).list()) == 1


def test_a_certificate_written_after_a_newer_one_is_still_triaged(sales, certs):
    certs.append(
        (
            "dev",
            _cert("a", started="2026-10-15T10:00:00+00:00", ended_at="2026-10-15T10:30:00+00:00"),
        )
    )
    sentinel = Sentinel(sales, FakeExecutor(), notify=False)
    sentinel.scan("dev")
    # A long run ended before "a" was seen, but its certificate arrives later.
    certs.append(
        (
            "dev",
            _cert(
                "slow",
                status="failed",
                error=INFRA,
                started="2026-10-15T08:00:00+00:00",
                ended_at="2026-10-15T10:29:00+00:00",
            ),
        )
    )
    sentinel.scan("dev")
    assert len(Incidents(sales).list()) == 1


def test_the_hook_before_the_first_scan_does_not_make_history_new(sales, certs):
    certs.extend(_hourly(5, status="failed"))
    sentinel = Sentinel(sales, FakeExecutor(), notify=False)
    sentinel.handle(RunEvent(env="dev", pipeline="bronze.sales", status="success", run_id="x"))
    sentinel.scan("dev")
    assert Incidents(sales).list() == []


def test_a_retry_covers_the_failed_node_and_everything_downstream(sales):
    decision = decide(
        sales, _failed(pipeline="silver.sales", node="clean_orders"), {"kind": "infra"}
    )
    assert decision.runbook == "retry"
    assert decision.nodes == ["clean_orders", "daily_revenue"]


def test_an_appended_output_downstream_blocks_the_retry(sales):
    catalog = sales / "catalog.yaml"
    catalog.write_text(
        catalog.read_text().replace(
            "write: {mode: overwrite, partition: [order_date]}",
            "write: {mode: append, partition: [order_date]}",
        )
    )
    decision = decide(
        sales, _failed(pipeline="silver.sales", node="clean_orders"), {"kind": "infra"}
    )
    assert decision.runbook == "escalate" and "gold.sales.daily_revenue" in decision.reason


def test_a_stale_node_with_an_appended_output_is_not_rerun(sales):
    from ducta.setting.project_schema import SentinelPolicy

    catalog = sales / "catalog.yaml"
    catalog.write_text(
        catalog.read_text().replace(
            "write: {mode: overwrite, partition: [order_date]}",
            "write: {mode: append, partition: [order_date]}",
        )
    )
    policy = SentinelPolicy(enabled=True, rerun_stale=True)
    event = RunEvent(
        env="dev", pipeline="silver.sales", status="stale", failed_nodes=["daily_revenue"]
    )
    decision = decide(sales, event, {}, kind="stale", policy=policy)
    assert decision.runbook == "observe" and "twice" in decision.reason
    event.failed_nodes = ["clean_orders"]
    catalog.write_text(catalog.read_text().replace("mode: append", "mode: overwrite"))
    decision = decide(sales, event, {}, kind="stale", policy=policy)
    assert decision.runbook == "rerun_stale" and decision.nodes == ["clean_orders", "daily_revenue"]


def test_the_cli_executor_reruns_several_nodes_one_by_one(sales, certs, monkeypatch):
    from ducta.ai.agents import runs
    from ducta.ai.agents.sentinel.actions import CliExecutor

    ran = []

    def fake_run(root, env, pipeline, nodes=(), **kw):
        ran.append(list(nodes))
        n = len(ran)
        status = "success" if n == 1 else "failed"
        certs.append(
            (
                "dev",
                _cert(
                    f"step-{n}",
                    pipeline="silver.sales",
                    status=status,
                    started=f"2999-01-01T00:00:0{n}+00:00",
                ),
            )
        )
        return runs.RunOutcome(0 if status == "success" else 1, "")

    monkeypatch.setattr(runs, "run_pipeline", fake_run)
    sentinel = Sentinel(sales, FakeExecutor(), notify=False)
    sentinel.scan("dev")  # first look, before the re-run
    event = CliExecutor().rerun(
        sales, "dev", "silver.sales", ["clean_orders", "daily_revenue"], True
    )
    assert ran == [["clean_orders"], ["daily_revenue"]]
    assert (
        event.run_id == "step-2" and event.status == "failed" and event.earlier_runs == ["step-1"]
    )
    # The earlier step is seen once the outcome is handled: never triaged as a run of its
    # own (its success would resolve the incident the failed step just opened).
    sentinel.handle(event)
    sentinel.scan("dev")
    assert not any(i.status == "resolved" for i in Incidents(sales).list())


def test_the_engine_lock_is_free_while_a_rerun_runs(sales):
    free = []

    class Probe(FakeExecutor):
        def rerun(self, root, *a):
            with engine_lock(root) as got:
                free.append(got)
            return super().rerun(root, *a)

    sentinel = Sentinel(sales, Probe("success"), notify=False)
    sentinel.on_run_finished(_failed())
    sentinel.run_once(["dev"])
    assert free == [True]
    assert Incidents(sales).list()[0].status == "resolved"


def test_a_proposal_does_not_undo_what_happened_meanwhile(sales):
    from ducta.ai.agents.sentinel.propose import propose_for

    error = (
        'Traceback (most recent call last):\n  File "pipelines/sales.py", line 9\nValueError: boom'
    )
    handled = Sentinel(sales, FakeExecutor(), notify=False).handle(
        _failed(pipeline="silver.sales", node="clean_orders", error=error)
    )

    class ResolvesMeanwhile(FakeProvider):
        def complete(self, system, messages):
            found = Incidents(sales).get(handled.id)
            if found.status != "resolved":
                found.status = "resolved"  # a person, while the model answers
                Incidents(sales).save(found)
            return super().complete(system, messages)

    linked = propose_for(
        sales,
        handled.id,
        provider=ResolvesMeanwhile("**What happened** it broke.", "no blocks"),
        requested_by="ana",
    )
    incident = Incidents(sales).get(handled.id)
    assert incident.status == "resolved"
    assert incident.links.get("explanation") == linked["explanation"] and linked["draft"]
    assert any(e["actor"] == "ana" for e in incident.timeline)


def test_a_failed_rerun_of_a_stale_pipeline_escalates_it(sales):
    incidents = Incidents(sales)
    stale, _ = incidents.open("dev", "bronze.sales", "stale")
    stale.status, stale.pending = (
        "remediating",
        {"action": "running", "since": "2026-10-15T00:00:00+00:00"},
    )
    incidents.save(stale)
    Sentinel(sales, FakeExecutor(), notify=False).handle(_failed(error="ValueError: boom"))
    assert incidents.get(stale.id).status == "escalated"


def test_a_rerun_whose_outcome_never_arrives_is_escalated(sales):
    incidents = Incidents(sales)
    incident, _ = incidents.open("dev", "bronze.sales", "failure")
    incident.status, incident.pending = (
        "remediating",
        {"action": "running", "since": "2020-01-01T00:00:00+00:00"},
    )
    incidents.save(incident)
    Sentinel(sales, FakeExecutor(), notify=False).tick()
    found = incidents.get(incident.id)
    assert found.status == "escalated" and "never arrived" in found.reason


# ── a remote model proposes only when the project says so ───────────────────


def _remote(*answers):
    from ducta.ai.config import AIConfig

    provider = FakeProvider(*answers)
    provider.config = AIConfig(provider="anthropic", model="claude-opus-5-5")
    return provider


def _code_failure(sales, provider):
    error = (
        'Traceback (most recent call last):\n  File "pipelines/sales.py", line 9\nValueError: boom'
    )
    sentinel = Sentinel(sales, FakeExecutor(), notify=False, provider=provider)
    handled = sentinel.handle(_failed(pipeline="silver.sales", node="clean_orders", error=error))
    sentinel._after_pass()
    return Incidents(sales).get(handled.id)


def test_a_remote_model_is_not_sent_code_unasked(sales):
    provider = _remote("**What happened** it broke.", "no blocks")
    incident = _code_failure(sales, provider)
    assert provider.calls == [] and not incident.links
    assert any("sentinel.propose.remote" in e.get("detail", "") for e in incident.timeline)


def test_a_remote_model_proposes_when_the_project_allows_it(sales):
    (sales / "ducta.yaml").write_text(
        (sales / "ducta.yaml")
        .read_text()
        .replace(
            "  max_actions_per_day: 10\n", "  max_actions_per_day: 10\n  propose: {remote: true}\n"
        )
    )
    incident = _code_failure(sales, _remote("**What happened** it broke.", "no blocks"))
    assert incident.links.get("explanation") and incident.links.get("draft")


def test_a_person_may_ask_a_remote_model(sales):
    from ducta.ai.agents.sentinel.propose import propose_for

    incident = _code_failure(sales, _remote())
    linked = propose_for(
        sales,
        incident.id,
        provider=_remote("**What happened** it broke.", "no blocks"),
        requested_by="ana",
    )
    assert linked["explanation"] and linked["draft"]
