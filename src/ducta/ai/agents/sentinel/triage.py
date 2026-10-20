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

Triage: what happened to a run, and what to do about it — decided by rules.

:func:`decide` is a fixed table. The model never chooses an action: at most,
for the failures a person must fix, it explains and drafts (L2).

| What failed | Runbook | Level |
|---|---|---|
| another run held the lock (exit 7) | ``retry_later`` | L1 |
| infrastructure a re-run cannot fix (credentials, driver, disk) | ``escalate`` | L0 |
| infrastructure, outputs overwritten or merged | ``retry`` | L1 |
| infrastructure, an output appended | ``escalate`` (a re-run writes rows twice) | L0 |
| data, the pipeline reads another pipeline, nothing appended | ``wait_upstream`` | L1 |
| a quality gate | ``propose_quality`` | L2 |
| code, configuration, data, unknown | ``propose_fix`` | L2 |
| late for its SLA | ``catch_up`` (if allowed) or ``escalate`` | L1/L0 |
| unusually slow | ``suggest_review`` | L2 |
| code changed since the last success | ``rerun_stale`` (if allowed, nothing appended) or ``observe`` | L1/L0 |

A re-run covers the failed (or stale) nodes and every node downstream of
them (:func:`rerun_nodes`); "appended" is judged on all of those.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ducta.ai.context import redact

L0, L1, L2 = "L0", "L1", "L2"

#: Infrastructure failures a re-run does not fix: they need a person.
_NOT_TRANSIENT = (
    "missing credentials",
    "authentication failed",
    "password authentication",
    "access denied",
    "permission denied",
    "no space left",
    "classnotfound",
    "no suitable driver",
)


#: "lock … held" as words, near each other (not "block" … "shelled").
_LOCK_HELD = re.compile(r"\block\b[^.\n]{0,60}\bheld\b|\bheld\b[^.\n]{0,60}\block\b")


@dataclass
class RunEvent:
    """A finished run, wherever it was seen (the server, a certificate)."""

    env: str
    pipeline: str
    status: str  # success | failed | gate_blocked | skipped
    run_id: Optional[str] = None
    started_at: Optional[str] = None
    duration_seconds: Optional[float] = None
    error: str = ""
    failed_nodes: List[str] = field(default_factory=list)
    exit_code: Optional[int] = None
    #: Who started it: ``sentinel`` for its own re-runs, when known.
    actor: Optional[str] = None
    #: Per-node errors, as the server's run errors list them.
    errors: List[Dict[str, Any]] = field(default_factory=list)
    certificate: Optional[Dict[str, Any]] = None
    #: Runs that were earlier steps of this one (a re-run node by node): seen, not triaged.
    earlier_runs: List[str] = field(default_factory=list)
    #: The nodes this run ran successfully, when known (empty: not known, as if all).
    nodes_run: List[str] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return self.status in ("failed", "gate_blocked")


def event_from_certificate(env: str, cert: Dict[str, Any]) -> RunEvent:
    nodes = cert.get("nodes") or []
    failed = [n for n in nodes if str(n.get("status")) in ("failed", "gate_blocked")]
    return RunEvent(
        env=env,
        pipeline=str(cert.get("pipeline") or ""),
        status=str(cert.get("status") or ""),
        run_id=cert.get("run_id"),
        started_at=cert.get("started_at"),
        duration_seconds=cert.get("duration_seconds"),
        error=str(
            cert.get("error") or next((n.get("error") for n in failed if n.get("error")), "") or ""
        ),
        failed_nodes=[str(n.get("name")) for n in failed],
        nodes_run=[str(n.get("name")) for n in nodes if str(n.get("status")) == "success"],
        errors=[
            {"node_id": n.get("name"), "message": n.get("error"), "error_type": n.get("status")}
            for n in failed
        ],
        certificate=cert,
    )


def event_from_execution(
    record: Dict[str, Any], errors: Optional[List[Dict[str, Any]]] = None
) -> RunEvent:
    """From the server's execution record (``ExecutionResponse`` as JSON)."""
    errors = list(errors or [])
    return RunEvent(
        env=str(record.get("env") or ""),
        pipeline=str(record.get("pipeline_name") or ""),
        status=str(record.get("status") or ""),
        run_id=record.get("certificate_run_id") or record.get("id"),
        started_at=str(record.get("started_at") or "") or None,
        duration_seconds=record.get("duration_seconds"),
        error=str(record.get("error_message") or ""),
        failed_nodes=[str(e.get("node_id")) for e in errors if e.get("node_id")],
        exit_code=record.get("exit_code"),
        nodes_run=[str(n) for n in (record.get("node_names") or [record.get("node_name")]) if n],
        actor="sentinel" if record.get("user_id") == "sentinel" else record.get("user_id"),
        errors=errors,
    )


def diagnosis_of(root: Path, event: RunEvent) -> Dict[str, Any]:
    """Ducta's diagnosis of a failed run (no model), with its text masked."""
    from ducta.ai.context import redact_config
    from ducta.api.services.diagnosis import diagnose
    from ducta.api.services.run_certificates import latest_successful

    last_ok: Optional[Dict[str, Any]] = None
    try:
        last_ok = latest_successful(root, event.env).get(event.pipeline)
    except Exception:  # noqa: BLE001 — no baseline is no "what changed"
        last_ok = None
    execution = {
        "id": event.run_id,
        "status": event.status,
        "error_message": event.error,
    }
    errors = event.errors or ([{"message": event.error}] if event.error else [])
    found = diagnose(execution, errors, root, event.certificate, last_ok)
    if event.status == "gate_blocked":
        found["kind"] = "quality_gate"
    masked: Dict[str, Any] = redact_config(found)
    return masked


def write_modes(
    root: Path, env: str, pipeline: str, nodes: Optional[List[str]] = None
) -> Dict[str, str]:
    """How each output of *pipeline* (of *nodes*, when given) is written in *env*."""
    from ducta.setting.project_loader import apply_environment, read_project

    resolved = apply_environment(read_project(root), env)
    catalog = resolved.get("catalog") or {}
    spec = (resolved.get("pipelines") or {}).get(pipeline) or {}
    out: Dict[str, str] = {}
    for name, node in (spec.get("nodes") or {}).items():
        if nodes and name not in nodes:
            continue
        for ds in (node or {}).get("outputs") or []:
            entry = catalog.get(ds) if isinstance(catalog.get(ds), dict) else {}
            write = (entry or {}).get("write")
            out[str(ds)] = (
                str((write or {}).get("mode") or "overwrite")
                if isinstance(write, dict)
                else "overwrite"
            )
    return out


def _datasets(value: Any) -> List[str]:
    if isinstance(value, dict):
        return [str(v) for v in value.values() if isinstance(v, str)]
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value if isinstance(v, str)]
    return [str(value)] if isinstance(value, str) else []


def rerun_nodes(root: Path, env: str, pipeline: str, nodes: List[str]) -> List[str]:
    """What re-running *nodes* takes: them and every node of *pipeline* downstream of
    them (those did not run, or ran on what failed), in dependency order.

    Empty when *nodes* is: the whole pipeline. Otherwise the nodes are named
    even when they are all of them, so a re-run never starts upstream pipelines.
    """
    from ducta.setting.project_loader import apply_environment, read_project

    if not nodes:
        return []
    resolved = apply_environment(read_project(root), env)
    spec = (resolved.get("pipelines") or {}).get(pipeline) or {}
    graph = {
        str(name): (
            _datasets((node or {}).get("inputs")),
            _datasets((node or {}).get("outputs")),
        )
        for name, node in (spec.get("nodes") or {}).items()
    }
    chosen = {n for n in nodes if n in graph}
    grew = True
    while grew:
        written = {ds for n in chosen for ds in graph[n][1]}
        more = {n for n, (ins, _) in graph.items() if n not in chosen and written & set(ins)}
        chosen |= more
        grew = bool(more)
    if not chosen:
        return []
    # Dependency order among the chosen nodes (declared order when free).
    producer = {ds: n for n, (_, outs) in graph.items() for ds in outs}
    ordered: List[str] = []
    pending = [n for n in graph if n in chosen]
    while pending:
        ready = [
            n
            for n in pending
            if all(
                producer.get(ds) not in chosen
                or producer.get(ds) in ordered
                or producer.get(ds) == n
                for ds in graph[n][0]
            )
        ]
        step = ready[0] if ready else pending[0]  # a cycle: the validator reports it
        ordered.append(step)
        pending.remove(step)
    return ordered


def appended(root: Path, env: str, pipeline: str, nodes: List[str]) -> List[str]:
    """The outputs re-running *nodes* (all of *pipeline* when empty) would append to."""
    modes = write_modes(root, env, pipeline, nodes or None)
    return sorted(ds for ds, mode in modes.items() if mode == "append")


def upstream_of(root: Path, pipeline: str) -> List[str]:
    from ducta.setting.project_loader import read_project

    spec = (read_project(root, expand=False).pipelines or {}).get(pipeline) or {}
    return [str(p) for p in spec.get("depends_on") or []]


@dataclass
class Decision:
    runbook: str
    level: str
    reason: str
    #: For a re-run: the nodes to re-run (empty: the whole pipeline).
    nodes: List[str] = field(default_factory=list)
    upstream: List[str] = field(default_factory=list)


def decide(
    root: Path,
    event: RunEvent,
    diagnosis: Dict[str, Any],
    *,
    kind: str = "failure",
    policy: Any = None,
) -> Decision:
    """The runbook for *event* — a fixed table, see the module's docstring."""
    if kind == "sla_miss":
        if policy is not None and policy.catch_up:
            return Decision("catch_up", L1, "late for its SLA: run it now")
        return Decision("escalate", L0, "late for its SLA; catch_up is off")
    if kind == "slow":
        return Decision("suggest_review", L2, "much slower than its usual p95: review its nodes")
    if kind == "stale":
        if policy is None or not policy.rerun_stale:
            return Decision(
                "observe", L0, "its code changed since the last success; rerun_stale is off"
            )
        nodes = rerun_nodes(root, event.env, event.pipeline, list(event.failed_nodes))
        twice = appended(root, event.env, event.pipeline, nodes)
        if twice:
            return Decision(
                "observe",
                L0,
                f"its code changed since the last success, but {', '.join(twice)} is "
                "appended: a re-run would write its rows twice",
            )
        return Decision("rerun_stale", L1, "its code changed since the last success", nodes=nodes)

    text = f"{event.error} {diagnosis.get('message') or ''}".lower()
    if event.exit_code == 7 or _LOCK_HELD.search(text):
        return Decision("retry_later", L1, "another run held the lock: nothing ran")
    found = str(diagnosis.get("kind") or "unknown")
    if found == "infra" and any(p in text for p in _NOT_TRANSIENT):
        return Decision(
            "escalate",
            L0,
            "infrastructure failure that a re-run cannot fix (credentials, permissions, "
            "disk space): a person must act",
        )
    # A re-run covers the failed nodes and everything downstream of them.
    nodes = rerun_nodes(root, event.env, event.pipeline, list(event.failed_nodes))
    if found == "infra":
        twice = appended(root, event.env, event.pipeline, nodes)
        if twice:
            return Decision(
                "escalate",
                L0,
                f"infrastructure failure, but {', '.join(twice)} is appended: a re-run "
                "could write its rows twice",
            )
        return Decision(
            "retry",
            L1,
            "infrastructure failure (connection, memory) and every output it re-writes is "
            "overwritten or merged: a re-run is safe",
            nodes=nodes,
        )
    if found == "data":
        upstream = upstream_of(root, event.pipeline)
        twice = appended(root, event.env, event.pipeline, nodes) if upstream else []
        if upstream and not twice:
            return Decision(
                "wait_upstream",
                L1,
                f"the data was not what it expected; it reads {', '.join(upstream)}: re-run "
                "once that succeeds",
                nodes=nodes,
                upstream=upstream,
            )
    if found == "quality_gate":
        return Decision(
            "propose_quality",
            L2,
            "a quality gate stopped it: a person decides whether the data or the check is wrong",
        )
    return Decision(
        "propose_fix", L2, f"{diagnosis.get('title') or 'the run failed'}: a person must fix it"
    )


def summary(event: RunEvent, diagnosis: Optional[Dict[str, Any]] = None) -> str:
    """One masked line for a timeline or an alert."""
    head = (diagnosis or {}).get("title") or event.status
    message = redact(str((diagnosis or {}).get("message") or event.error or ""))[:300]
    return f"{head}: {message}" if message else str(head)
