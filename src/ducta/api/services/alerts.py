"""
Copyright (C) 2024-2026 Faustino Lopez Ramos

This file is part of ducta.

Licensed under the Apache License, Version 2.0 (the "License"); you may not
use this file except in compliance with the License. You may obtain a copy
of the License at

    https://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
License for the specific language governing permissions and limitations
under the License.

SPDX-License-Identifier: Apache-2.0

Alerts: the project's ``alerts:`` rules (ducta.yaml), evaluated when a run
finishes, sent where each rule says. One message per run — never one per
failed node — with a link to the run's diagnosis.

Destinations that are secrets (webhook URLs) are named by environment
variable; an unset variable is logged and skipped, never fatal to the run.
"""

from __future__ import annotations

import fnmatch
import json
import os
import smtplib
import urllib.request
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Any, Callable, Dict, List, Optional

from loguru import logger


@dataclass
class AlertEvent:
    kind: str  # failure | quality_gate | slow | sla_miss | stale
    project: str
    pipeline: str
    env: str
    summary: str
    run_id: Optional[str] = None
    link: Optional[str] = None


def events_for_run(record: Dict[str, Any], p95_seconds: Optional[float] = None) -> List[str]:
    """What a finished run is worth an alert about."""
    status = str(record.get("status") or "")
    message = str(record.get("error_message") or "")
    out: List[str] = []
    if (
        status == "gate_blocked"
        or "quality gate" in message.lower()
        or "quality checks failed" in message.lower()
    ):
        out.append("quality_gate")
    elif status == "failed":
        out.append("failure")
    duration = record.get("duration_seconds")
    if status == "success" and p95_seconds and duration and duration > 1.5 * p95_seconds:
        out.append("slow")
    return out


def matching_rules(rules: List[Any], event: AlertEvent) -> List[Any]:
    return [
        r
        for r in rules
        if event.kind in r.when and any(fnmatch.fnmatchcase(event.pipeline, g) for g in r.pipelines)
    ]


def _text(event: AlertEvent) -> str:
    title = {
        "failure": "failed",
        "quality_gate": "was stopped by a quality gate",
        "slow": "ran unusually slowly",
        "sla_miss": "missed its SLA",
        "stale": "is stale",
    }.get(event.kind, event.kind)
    lines = [f"[ducta] {event.project} / {event.pipeline} {title} in {event.env}.", event.summary]
    if event.link:
        lines.append(f"Diagnose: {event.link}")
    return "\n".join(line for line in lines if line)


Poster = Callable[[str, Dict[str, Any]], None]


def _post_json(url: str, body: Dict[str, Any]) -> None:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"content-type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 — URL from the project's own config
        resp.read()


def _send_email(to: List[str], subject: str, text: str) -> None:
    host = os.environ.get("DUCTA_SMTP_HOST")
    if not host:
        raise RuntimeError("DUCTA_SMTP_HOST is not set")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = os.environ.get("DUCTA_SMTP_FROM", "ducta@localhost")
    msg["To"] = ", ".join(to)
    msg.set_content(text)
    with smtplib.SMTP(host, int(os.environ.get("DUCTA_SMTP_PORT", "25")), timeout=10) as smtp:
        if os.environ.get("DUCTA_SMTP_USER"):
            smtp.starttls()
            smtp.login(os.environ["DUCTA_SMTP_USER"], os.environ.get("DUCTA_SMTP_PASSWORD", ""))
        smtp.send_message(msg)


def deliver(event: AlertEvent, rules: List[Any], post: Poster = _post_json) -> List[Dict[str, Any]]:
    """Send *event* through every matching rule's channels; returns what happened per channel."""
    text = _text(event)
    results: List[Dict[str, Any]] = []
    sent: set = set()
    for rule in matching_rules(rules, event):
        for channel in rule.channels:
            key = (channel.type, channel.webhook_env or channel.url_env or ",".join(channel.to))
            if key in sent:
                continue  # two rules, one destination: one message
            sent.add(key)
            try:
                if channel.type in ("slack", "teams", "webhook"):
                    var = channel.webhook_env or channel.url_env
                    url = os.environ.get(var or "")
                    if not url:
                        raise RuntimeError(f"environment variable {var} is not set")
                    body: Dict[str, Any] = {"text": text}
                    if channel.type == "webhook":
                        body = {"text": text, **{k: v for k, v in event.__dict__.items()}}
                    post(url, body)
                else:
                    _send_email(channel.to, text.splitlines()[0], text)
                results.append({"channel": channel.type, "ok": True})
            except Exception as e:  # noqa: BLE001 — an alert that fails must not fail the run
                logger.warning("Alert via {} not sent: {}", channel.type, e)
                results.append({"channel": channel.type, "ok": False, "error": str(e)})
    return results


def notify_run_finished(
    source_path: Any, project_id: Optional[str], record: Dict[str, Any]
) -> None:
    """After a run: evaluate the project's alert rules and send. Never raises."""
    try:
        from pathlib import Path

        from ducta.api.repositories.v2_store import V2ProjectStore

        store = V2ProjectStore.detect(Path(source_path))
        if store is None:
            return
        rules = store.project().project.alerts
        if not rules:
            return
        pipeline = str(record.get("pipeline_name") or "")
        env = str(record.get("env") or "")
        p95 = None
        if record.get("status") == "success" and any("slow" in r.when for r in rules):
            from ducta.api.services.metrics import project_metrics
            from ducta.api.services.run_certificates import certificates

            history = [
                c
                for _e, c in certificates(store.root, env)
                if c.get("run_id") != record.get("certificate_run_id")
            ]
            row = next(
                (p for p in project_metrics(history, {})["pipelines"] if p["pipeline"] == pipeline),
                None,
            )
            p95 = row["p95_seconds"] if row and row["runs"] >= 5 else None
        base = os.environ.get("DUCTA_PUBLIC_URL", "").rstrip("/")
        link = f"{base}/p/{project_id}/runs/{record.get('id')}" if base and project_id else None
        for kind in events_for_run(record, p95):
            deliver(
                AlertEvent(
                    kind=kind,
                    project=str(project_id or store.root.name),
                    pipeline=pipeline,
                    env=env,
                    summary=str(record.get("error_message") or "")[:500],
                    run_id=record.get("id"),
                    link=link,
                ),
                rules,
            )
    except Exception as e:  # noqa: BLE001 — alerting must never break a run's bookkeeping
        logger.warning("Alerts for run {} not evaluated: {}", record.get("id"), e)


def check_sla(
    project_id: str,
    store: Any,
    env: str,
    already: Optional[Dict[Any, Any]] = None,
) -> Dict[str, Any]:
    """Alert on the project's pipelines late for their ``metadata.sla`` in *env*.

    *already* (pipeline → the last success it was alerted for) makes repeated
    checks quiet: one alert per late streak, not one per check.
    """
    from ducta.api.services.metrics import project_metrics
    from ducta.api.services.run_certificates import certificates

    project = store.project()
    rules = project.project.alerts
    slas = {n: (p.metadata or {}).get("sla") for n, p in project.pipelines.items()}
    certs = [c for _e, c in certificates(store.root, env)]
    late = [
        p
        for p in project_metrics(certs, {k: v for k, v in slas.items() if v})["pipelines"]
        if p["freshness"] == "late"
    ]
    sent = []
    for p in late:
        key = (project_id, env, p["pipeline"])
        if already is not None and already.get(key) == p["last_success_at"]:
            continue
        event = AlertEvent(
            kind="sla_miss",
            project=project_id,
            pipeline=p["pipeline"],
            env=env,
            summary=f"SLA {p['sla']}; last success {p['last_success_at'] or 'never'}.",
        )
        sent.append({"pipeline": p["pipeline"], "results": deliver(event, rules)})
        if already is not None:
            already[key] = p["last_success_at"]
    return {"late": [p["pipeline"] for p in late], "sent": sent}


async def sla_watch(workspace: Any, env: str, interval_seconds: float) -> None:
    """Check every project's SLAs every *interval_seconds*, for as long as the API runs."""
    import asyncio
    from pathlib import Path

    from ducta.api.services.project import ProjectService

    alerted: Dict[Any, Any] = {}
    while True:
        try:
            svc = ProjectService(Path(workspace))

            def run_all() -> None:
                for item in svc.list_projects_paginated(limit=10_000).projects:
                    if getattr(item, "config_status", "ok") == "invalid":
                        continue
                    try:
                        store = svc.store(item.id)
                        if store is not None and store.project().project.alerts:
                            check_sla(item.id, store, env, alerted)
                    except Exception as e:  # noqa: BLE001 — one project must not stop the others
                        logger.warning("SLA check of {} failed: {}", item.id, e)

            await asyncio.to_thread(run_all)
        except Exception as e:  # noqa: BLE001
            logger.warning("SLA watch pass failed: {}", e)
        await asyncio.sleep(interval_seconds)
