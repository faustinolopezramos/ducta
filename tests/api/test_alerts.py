"""Alerts: which runs are worth one, which rules hear it, and that it really arrives."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from ducta.api.services.alerts import AlertEvent, deliver, events_for_run, matching_rules
from ducta.setting.project_schema import AlertRule


def _rule(on, pipelines=("*",), var="ALERT_URL", type_="webhook"):
    key = "url_env" if type_ == "webhook" else "webhook_env"
    return AlertRule.model_validate(
        {"when": list(on), "pipelines": list(pipelines), "channels": [{"type": type_, key: var}]}
    )


def test_which_runs_raise_which_events():
    assert events_for_run({"status": "failed", "error_message": "KeyError"}) == ["failure"]
    assert events_for_run({"status": "failed", "error_message": "Quality gate blocked"}) == [
        "quality_gate"
    ]
    assert events_for_run({"status": "gate_blocked"}) == ["quality_gate"]
    assert events_for_run({"status": "success", "duration_seconds": 100}, p95_seconds=50) == [
        "slow"
    ]
    assert events_for_run({"status": "success", "duration_seconds": 60}, p95_seconds=50) == []
    assert events_for_run({"status": "cancelled"}) == []


def test_rules_match_on_event_and_pipeline_glob():
    rules = [_rule(["failure"], ["silver.*"]), _rule(["quality_gate"])]
    event = AlertEvent(kind="failure", project="p", pipeline="silver.clean", env="prod", summary="")
    assert matching_rules(rules, event) == [rules[0]]
    other = AlertEvent(kind="failure", project="p", pipeline="gold.agg", env="prod", summary="")
    assert matching_rules(rules, other) == []


@pytest.fixture
def receiver():
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            received.append(json.loads(self.rfile.read(int(self.headers["content-length"]))))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/hook", received
    server.shutdown()


def test_one_message_per_destination_arrives(receiver, monkeypatch):
    url, received = receiver
    monkeypatch.setenv("ALERT_URL", url)
    rules = [_rule(["failure"]), _rule(["failure"], ["silver.*"])]  # both point at the same URL
    event = AlertEvent(
        kind="failure",
        project="edu",
        pipeline="silver.clean",
        env="prod",
        summary="boom",
        link="http://x/run",
    )
    results = deliver(event, rules)
    assert results == [{"channel": "webhook", "ok": True}]
    [body] = received
    assert (
        "silver.clean failed in prod" in body["text"] and "Diagnose: http://x/run" in body["text"]
    )
    assert body["pipeline"] == "silver.clean"


def test_a_missing_secret_is_reported_not_raised(monkeypatch):
    monkeypatch.delenv("NOPE", raising=False)
    event = AlertEvent(kind="failure", project="p", pipeline="x", env="e", summary="")
    [result] = deliver(event, [_rule(["failure"], var="NOPE", type_="slack")])
    assert result["ok"] is False and "NOPE" in result["error"]


def test_sla_check_alerts_once_per_late_streak(monkeypatch):
    from types import SimpleNamespace

    from ducta.api.services import alerts, metrics, run_certificates

    sent = []
    monkeypatch.setattr(alerts, "deliver", lambda event, rules: sent.append(event.pipeline) or [])
    monkeypatch.setattr(run_certificates, "certificates", lambda root, env: [])
    late = {
        "pipeline": "etl",
        "freshness": "late",
        "sla": "daily 06:00",
        "last_success_at": "2026-10-01",
    }
    monkeypatch.setattr(metrics, "project_metrics", lambda certs, slas: {"pipelines": [late]})
    project = SimpleNamespace(
        project=SimpleNamespace(alerts=[_rule(["sla_miss"])]),
        pipelines={"etl": SimpleNamespace(metadata={"sla": "daily 06:00"})},
    )
    store = SimpleNamespace(project=lambda: project, root="/x")
    seen: dict = {}
    assert alerts.check_sla("p", store, "prod", seen)["late"] == ["etl"]
    alerts.check_sla("p", store, "prod", seen)  # same streak: quiet
    assert sent == ["etl"]
    late["last_success_at"] = "2026-10-05"  # it ran, then went late again
    alerts.check_sla("p", store, "prod", seen)
    assert sent == ["etl", "etl"]
