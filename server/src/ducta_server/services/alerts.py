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

Alerts the server sends on its own: after a run it executed, on a stream event,
and from its SLA watch. The rules and the delivery are in :mod:`ducta.runs.alerts`.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from loguru import logger

from ducta.runs.alerts import AlertEvent, Poster, deliver, events_for_run, post_json


def notify_run_finished(
    source_path: Any, project_id: Optional[str], record: Dict[str, Any]
) -> None:
    """After a run: evaluate the project's alert rules and send. Never raises."""
    try:
        from pathlib import Path

        from ducta.project_store.store import V2ProjectStore

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
            from ducta.runs.certificates import certificates
            from ducta.runs.metrics import project_metrics

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


#: Live stream events an ``alerts:`` rule can name in ``when``.
STREAM_EVENT_KINDS = ("stream_failed", "stream_stalled", "stream_quarantine")


def _stream_summary(event: Dict[str, Any]) -> str:
    node = event.get("node") or "?"
    if event.get("kind") == "stream_quarantine":
        rows, batches = event.get("rows") or 0, event.get("batches") or 0
        return f"Node '{node}': {rows} row(s) quarantined in {batches} batch(es)."
    return f"Node '{node}': {str(event.get('error') or 'no error detail')[:500]}"


def notify_stream_event(
    source_path: Any,
    project_id: Optional[str],
    env: str,
    event: Dict[str, Any],
    post: Poster = post_json,
) -> List[Dict[str, Any]]:
    """A stream's live event, through the project's rules that name its kind. Never raises."""
    if event.get("kind") not in STREAM_EVENT_KINDS:
        return []  # finished / recovered: the run's own end-of-run alerts cover those
    try:
        from pathlib import Path

        from ducta.project_store.store import V2ProjectStore

        store = V2ProjectStore.detect(Path(source_path))
        if store is None:
            return []
        rules = store.project().project.alerts
        if not rules:
            return []
        return deliver(
            AlertEvent(
                kind=str(event["kind"]),
                project=str(project_id or store.root.name),
                pipeline=str(event.get("pipeline") or ""),
                env=env,
                summary=_stream_summary(event),
                run_id=event.get("run_id"),
            ),
            rules,
            post=post,
        )
    except Exception as e:  # noqa: BLE001 - alerting must never break a stream
        logger.warning("Stream alert '{}' not evaluated: {}", event.get("kind"), e)
        return []


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
    from ducta.runs.certificates import certificates
    from ducta.runs.metrics import project_metrics

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

    from ducta_server.services.project import ProjectService

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
