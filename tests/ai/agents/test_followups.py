"""Sentinel after the 2026-10-19 review: a run settles an incident only if it ran the
nodes that failed; the audit log is counted from its end; no incident is forgotten."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from test_sentinel import (  # noqa: E402,F401
    FakeExecutor,
    _failed,
    certs,  # noqa: E402,F401
    sales,
)

from ducta.ai.agents import audit  # noqa: E402
from ducta.ai.agents.sentinel.engine import Sentinel  # noqa: E402
from ducta.ai.agents.sentinel.incidents import Incidents  # noqa: E402
from ducta.ai.agents.sentinel.triage import (  # noqa: E402
    RunEvent,
    decide,
    event_from_certificate,
    event_from_execution,
)


def _success(nodes, run_id="ok1", actor=None):
    return RunEvent(
        env="dev",
        pipeline="bronze.sales",
        status="success",
        run_id=run_id,
        nodes_run=nodes,
        actor=actor,
    )


def _open_incident(sales):
    # An error a re-run cannot fix, so it stays escalated and open.
    sentinel = Sentinel(sales, FakeExecutor(), notify=False)
    incident = sentinel.handle(
        _failed(error="FATAL: password authentication failed", node="land_orders")
    )
    assert incident.active and incident.nodes == ["land_orders"]
    return sentinel, incident


def test_a_run_of_another_node_does_not_resolve_the_incident(sales):
    sentinel, incident = _open_incident(sales)
    sentinel.handle(_success(["other_node"]))
    now = Incidents(sales).get(incident.id)
    assert now.active
    assert any(t["action"] == "partial" for t in now.timeline)


def test_a_run_that_ran_the_failed_node_resolves_it(sales):
    sentinel, incident = _open_incident(sales)
    sentinel.handle(_success(["land_orders", "other_node"]))
    assert Incidents(sales).get(incident.id).status == "resolved"


def test_a_run_that_does_not_say_which_nodes_counts_as_whole(sales):
    sentinel, incident = _open_incident(sales)
    sentinel.handle(_success([]))
    assert Incidents(sales).get(incident.id).status == "resolved"


def test_the_events_carry_the_nodes_they_ran():
    cert = {
        "run_id": "r",
        "pipeline": "p",
        "status": "success",
        "nodes": [{"name": "a", "status": "success"}, {"name": "b", "status": "skipped"}],
    }
    assert event_from_certificate("dev", cert).nodes_run == ["a"]
    assert event_from_execution({"node_names": ["a", "b"]}).nodes_run == ["a", "b"]
    assert event_from_execution({"node_name": "a"}).nodes_run == ["a"]
    assert event_from_execution({}).nodes_run == []


def test_a_blocked_or_shelled_message_is_not_a_held_lock(sales):
    event = _failed(error="the shelled-out step was blocked by a firewall")
    assert decide(sales, event, {"kind": "code"}).runbook != "retry_later"
    held = _failed(error="could not take the run lock: lock held by pid 42")
    assert decide(sales, held, {"kind": "unknown"}).runbook == "retry_later"


def test_the_day_is_counted_from_the_end_of_the_log(sales):
    path = audit.audit_path(sales, "sentinel")
    path.parent.mkdir(parents=True, exist_ok=True)
    old = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    new = datetime.now(timezone.utc).isoformat()
    lines = [json.dumps({"at": old, "action": "rerun", "result": "started"})] * 500
    lines += [json.dumps({"at": new, "action": "rerun", "result": "started"})] * 3
    lines += [json.dumps({"at": new, "action": "open", "result": "opened"})]
    path.write_text("\n".join(lines) + "\n")
    assert audit.count_since(sales, "sentinel", 24, action="rerun", result="started") == 3
    # A small block forces lines to straddle block boundaries.
    got = [e for e in audit._newest_first(path, block=64)]
    assert len(got) == 504 and got[0]["action"] == "open"


def test_every_incident_is_listed_however_many_there_are(sales):
    incidents = Incidents(sales)
    first, _ = incidents.open("dev", "bronze.sales", "failure")
    first.id = "20200101-000000-aaaaaa"
    incidents.save(first)
    for i in range(1005):
        other = type(first).from_dict(
            {**first.to_dict(), "id": f"2026{i:04d}-000000-bbbbbb", "status": "resolved"}
        )
        incidents.save(other)
    assert "20200101-000000-aaaaaa" in [i.id for i in incidents.list(status="active")]
