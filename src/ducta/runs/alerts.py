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
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import smtplib
import urllib.request
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Any, Callable, Dict, List, Optional

from loguru import logger


@dataclass
class AlertEvent:
    kind: str  # failure | quality_gate | slow | sla_miss | sentinel | stream_*
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
        "sentinel": "— a Ducta Sentinel incident",
        "stream_failed": "has a stream node that failed",
        "stream_stalled": "has a stream node that stalled",
        "stream_quarantine": "quarantined data",
    }.get(event.kind, event.kind)
    lines = [f"[ducta] {event.project} / {event.pipeline} {title} in {event.env}.", event.summary]
    if event.link:
        lines.append(f"Diagnose: {event.link}")
    return "\n".join(line for line in lines if line)


Poster = Callable[[str, Dict[str, Any]], None]


def post_json(url: str, body: Dict[str, Any]) -> None:
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


def _webhook_url(var: Optional[str]) -> str:
    """The http(s) URL held by the environment variable *var*."""
    from ducta.server_secrets import is_server_secret

    if not var:
        raise RuntimeError("the channel names no environment variable")
    if is_server_secret(var):
        raise RuntimeError(f"{var} is one of the server's own secrets, not a webhook URL")
    url = os.environ.get(var)
    if not url:
        raise RuntimeError(f"environment variable {var} is not set")
    if not re.match(r"^https?://", url.strip(), re.IGNORECASE):
        raise RuntimeError(f"the value of {var} is not an http(s) URL")
    return url.strip()


def deliver(event: AlertEvent, rules: List[Any], post: Poster = post_json) -> List[Dict[str, Any]]:
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
                    url = _webhook_url(channel.webhook_env or channel.url_env)
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
