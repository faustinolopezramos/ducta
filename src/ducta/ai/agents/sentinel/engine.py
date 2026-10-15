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

Ducta Sentinel: the same engine inside the API server and as a daemon.

* :meth:`Sentinel.handle` — a finished run: resolve the pipeline's incidents
  when it succeeded; when it failed, open or update one, diagnose it, and let
  :func:`triage.decide` choose the runbook. An L1 action is *scheduled*
  (after its backoff), only when :func:`policy.may_act` allows it; anything
  else escalates to a person, with a proposal (L2) when the model is there.
* :meth:`Sentinel.tick` — run the scheduled actions that are due, asking the
  policy again at that moment.
* :meth:`Sentinel.scan` — what the server's hook does not see: certificates
  of runs started elsewhere, pipelines late for their SLA, slow runs, and
  (when ``rerun_stale``) nodes whose code changed.

One engine pass at a time per project (a file lock), so the server and a
daemon never act twice on the same incident. The lock covers deciding and
recording, never a re-run or a model call (:meth:`Sentinel._after_pass`).
"""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Tuple

from loguru import logger

from ducta.ai.agents import audit
from ducta.ai.agents.sentinel import policy as gate
from ducta.ai.agents.sentinel.actions import SENTINEL_USER, Executor
from ducta.ai.agents.sentinel.incidents import Incident, Incidents
from ducta.ai.agents.sentinel.triage import (
    L1,
    L2,
    Decision,
    RunEvent,
    decide,
    diagnosis_of,
    event_from_certificate,
    summary,
)
from ducta.ai.agents.store import agent_dir, now, read_json, write_json

AGENT = "sentinel"
#: Runs that ended this long before the newest one seen are history: never
#: triaged again. Within it, run ids are remembered, so a certificate written a
#: little after a newer one is still triaged, and once.
_GRACE = timedelta(hours=6)
#: Run ids of unknown end remembered at most (the server's hook may not know it).
_UNDATED = 2000
#: A successful run this much slower than the pipeline's p95 is "slow".
_SLOW = 1.5
#: How long a person's change, a re-run's outcome or a proposal waits for the lock.
LOCK_WAIT = 60.0
#: A re-run whose outcome has not arrived after this long is given up on.
_RUNNING_FOR = timedelta(hours=24)


def _at(value: Optional[str]) -> Optional[datetime]:
    try:
        found = datetime.fromisoformat(str(value)) if value else None
    except ValueError:
        return None
    if found is not None and found.tzinfo is None:
        found = found.replace(tzinfo=timezone.utc)
    return found


def _ended(cert: Dict[str, Any]) -> Optional[datetime]:
    """When a run ended (its start, for a certificate without an end)."""
    return _at(cert.get("ended_at")) or _at(cert.get("started_at"))


def _due(value: Optional[str]) -> bool:
    at = _at(value)
    return at is not None and at <= datetime.now(timezone.utc)


def _later(seconds: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat(timespec="seconds")


@contextmanager
def engine_lock(root: Path, wait: float = 0.0) -> Iterator[bool]:
    """Hold the project's engine lock; yields whether it was taken.

    Every change to Sentinel's incidents happens under it — the engine's
    passes, and a person's resolve, ignore, retry or proposal — so none
    overwrites another. *wait* seconds are spent trying (none: take it if free).
    The lock is never held across a re-run or a model call: those take minutes.
    """
    from ducta.core.locking import try_lock_fd, unlock_fd

    path = agent_dir(root, AGENT) / "engine.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        got = try_lock_fd(fd)
        deadline = time.monotonic() + wait
        while not got and time.monotonic() < deadline:
            time.sleep(0.2)
            got = try_lock_fd(fd)
        try:
            yield got
        finally:
            if got:
                unlock_fd(fd)
    finally:
        os.close(fd)


@dataclass
class PassReport:
    """What one pass did — for the CLI and the server's log."""

    events: int = 0
    opened: List[str] = field(default_factory=list)
    resolved: List[str] = field(default_factory=list)
    actions: List[str] = field(default_factory=list)
    escalated: List[str] = field(default_factory=list)
    skipped: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "events": self.events,
            "opened": self.opened,
            "resolved": self.resolved,
            "actions": self.actions,
            "escalated": self.escalated,
            "skipped": self.skipped,
        }


class Sentinel:
    def __init__(
        self,
        root: Path,
        executor: Executor,
        *,
        project_id: Optional[str] = None,
        provider: Any = None,
        notify: bool = True,
        run_later: Optional[Callable[[Callable[[], Any]], Any]] = None,
    ):
        self.root = Path(root).resolve()
        self.executor = executor
        self.project_id = project_id
        self.provider = provider
        self.notify = notify
        #: Where proposals (model calls, minutes) run: inline by default; the
        #: server hands them to a thread of their own.
        self.run_later = run_later
        self.incidents = Incidents(self.root)
        self.report = PassReport()
        #: Taken under the lock, done after it: re-runs to start, proposals to make.
        self._due: List[Tuple[str, str, str, List[str], bool]] = []
        self._wanted: List[Tuple[str, RunEvent]] = []

    # ── settings and memory ────────────────────────────────────────────────

    def settings(self) -> Optional[gate.Settings]:
        found = gate.Settings.of(self.root)
        return found if found is not None and found.policy.enabled else None

    def _cursor_path(self, env: str) -> Path:
        safe = "".join(c for c in env if c.isalnum() or c in "-_") or "base"
        return agent_dir(self.root, AGENT) / f"cursor-{safe}.json"

    def _cursor(self, env: str) -> Optional[Dict[str, Any]]:
        """``{"after": iso | None, "seen": {run_id: ended iso | ""}}``, or ``None`` before the first look.

        A cursor of the earlier shape (a bare list of ids) counts as no
        cursor: the next scan takes history as seen again rather than
        re-triaging what fell out of that list.
        """
        data = read_json(self._cursor_path(env))
        if not isinstance(data, dict) or not isinstance(data.get("seen"), dict):
            return None
        seen = {str(k): str(v or "") for k, v in data["seen"].items()}
        return {"after": data.get("after"), "seen": seen, "scanned": bool(data.get("scanned"))}

    def _mark_seen(
        self,
        env: str,
        runs: Sequence[Any],
        cursor: Optional[Dict[str, Any]] = None,
        *,
        scanned: bool = False,
    ) -> None:
        """Remember *runs* — run ids, or ``(run_id, ended)`` pairs — and move the mark on.

        Only ids that ended within ``_GRACE`` of the newest run are kept: older
        runs are below the mark and never looked at again. *scanned* records
        that a scan took the environment's history in (the hook alone does not).
        """
        cursor = cursor or self._cursor(env) or {"after": None, "seen": {}}
        seen: Dict[str, str] = dict(cursor["seen"])
        newest = _at(cursor.get("after"))
        for run in runs:
            run_id, ended = run if isinstance(run, tuple) else (run, None)
            if not run_id:
                continue
            when = _at(ended) if isinstance(ended, str) else ended
            seen[str(run_id)] = when.isoformat() if when else seen.get(str(run_id), "")
            if when and (newest is None or when > newest):
                newest = when
        if newest is not None:
            floor = newest - _GRACE
            seen = {k: v for k, v in seen.items() if not v or (_at(v) or newest) >= floor}
        undated = [k for k, v in seen.items() if not v]
        for k in undated[:-_UNDATED] if len(undated) > _UNDATED else []:
            seen.pop(k)
        write_json(
            self._cursor_path(env),
            {
                "after": newest.isoformat() if newest else None,
                "seen": seen,
                "scanned": scanned or bool(cursor.get("scanned")),
                "updated_at": now(),
            },
        )

    def _save(self, incident: Incident) -> None:
        self.incidents.save(incident)

    def _audit(self, action: str, incident: Incident, result: str, reason: str = "") -> None:
        audit.record(
            self.root,
            AGENT,
            action,
            target={"incident": incident.id, "env": incident.env, "pipeline": incident.pipeline},
            result=result,
            reason=reason,
        )

    def _alert(self, incident: Incident, what: str) -> None:
        if not self.notify:
            return
        try:
            from ducta.api.services.alerts import AlertEvent, deliver
            from ducta.setting.project_loader import validate_project

            rules = validate_project(self.root).project.alerts
            if not any("sentinel" in r.when for r in rules):
                return
            deliver(
                AlertEvent(
                    kind="sentinel",
                    project=str(self.project_id or self.root.name),
                    pipeline=incident.pipeline,
                    env=incident.env,
                    summary=f"Sentinel {what}: {incident.reason}"[:500],
                    run_id=incident.last_run_id,
                ),
                rules,
            )
        except Exception as e:  # noqa: BLE001 — an alert never stops the engine
            logger.warning("Sentinel alert for {} not sent: {}", incident.id, e)

    # ── decisions ──────────────────────────────────────────────────────────

    def _escalate(self, incident: Incident, reason: str) -> None:
        was = incident.status
        incident.status = "escalated"
        incident.pending = None
        incident.reason = reason
        incident.note(AGENT, "escalate", reason)
        if was != "escalated":
            self.report.escalated.append(incident.id)
            self._audit("escalate", incident, "escalated", reason)
            self._alert(incident, "needs a person")

    def _schedule(self, incident: Incident, decision: Decision, settings: gate.Settings) -> None:
        policy = settings.policy
        if decision.runbook == "wait_upstream":
            minutes = policy.wait_for_upstream.max_wait_minutes
            incident.pending = {
                "action": "wait_upstream",
                "upstream": decision.upstream,
                "until": _later(minutes * 60),
                "nodes": decision.nodes,
            }
            incident.status = "remediating"
            incident.note(
                AGENT,
                "wait",
                f"re-run once {', '.join(decision.upstream)} succeeds (at most {minutes} min)",
            )
            return
        delay = gate.backoff(policy, incident.attempts)
        incident.pending = {
            "action": "rerun",
            "at": _later(delay),
            "nodes": decision.nodes,
            "reuse_upstream": bool(decision.nodes),
        }
        incident.status = "remediating"
        incident.note(AGENT, "schedule", f"re-run in {delay}s ({decision.runbook})")

    def _act_on(
        self, incident: Incident, event: RunEvent, decision: Decision, settings: gate.Settings
    ) -> None:
        incident.runbook, incident.level, incident.reason = (
            decision.runbook,
            decision.level,
            decision.reason,
        )
        if decision.level == L1:
            allowed, why = gate.may_act(self.root, settings, incident.env, incident.pipeline)
            limit = settings.policy.retry_infra.max_attempts
            if not allowed:
                incident.level = "L0"
                self._escalate(incident, f"{decision.reason} — not acting: {why}")
            elif incident.attempts >= limit and decision.runbook != "catch_up":
                self._escalate(
                    incident,
                    f"still failing after {incident.attempts} re-run(s) (retry_infra.max_attempts: {limit})",
                )
            else:
                self._schedule(incident, decision, settings)
            return
        self._escalate(incident, decision.reason)
        if decision.level == L2 and not incident.links:
            # A model call takes minutes: made after the pass, outside the lock.
            self._wanted.append((incident.id, event))

    # ── a finished run ─────────────────────────────────────────────────────

    def handle(self, event: RunEvent) -> Optional[Incident]:
        """Triage one finished run; the incident it touched, if any."""
        settings = self.settings()
        if settings is None or not event.pipeline:
            return None
        self.report.events += 1
        ended = _ended(event.certificate) if event.certificate else None
        self._mark_seen(event.env, [(event.run_id, ended), *event.earlier_runs])
        if event.actor == SENTINEL_USER:
            audit.record(
                self.root,
                AGENT,
                "rerun_result",
                target={"env": event.env, "pipeline": event.pipeline, "run": event.run_id},
                result=event.status,
            )
        if event.status == "success":
            self._succeeded(event, settings)
            return None
        if not event.failed:
            return None
        diagnosis = diagnosis_of(self.root, event)
        incident, new = self.incidents.open(event.env, event.pipeline, "failure")
        incident.failures += 1
        incident.last_run_id = event.run_id
        incident.diagnosis = diagnosis
        incident.note(
            AGENT if event.actor == SENTINEL_USER else "run",
            "failed",
            summary(event, diagnosis),
            run=event.run_id,
        )
        if new:
            self.report.opened.append(incident.id)
            self._audit("open", incident, "opened", summary(event, diagnosis))
        self._act_on(
            incident, event, decide(self.root, event, diagnosis, policy=settings.policy), settings
        )
        self._save(incident)
        # A late or stale pipeline's re-run that failed: that incident is not
        # being remediated any more — the failure's own incident says why.
        for other in self.incidents.active(event.env, event.pipeline):
            if other.id != incident.id and (other.pending or {}).get("action") == "running":
                self._escalate(other, f"its re-run failed: see incident {incident.id}")
                self._save(other)
        return incident

    def _succeeded(self, event: RunEvent, settings: gate.Settings) -> None:
        for incident in self.incidents.active(event.env, event.pipeline):
            if incident.kind not in ("failure", "stale", "slow", "sla_miss"):
                continue
            was_escalated = incident.status == "escalated"
            incident.status = "resolved"
            incident.resolved_at = now()
            incident.pending = None
            by = "a re-run by Sentinel" if event.actor == SENTINEL_USER else "a successful run"
            incident.note(AGENT, "resolve", f"{by} ({event.run_id or 'run'})")
            self._audit("resolve", incident, "resolved", by)
            self.report.resolved.append(incident.id)
            self._save(incident)
            if was_escalated:
                self._alert(incident, "saw it recover")
        # Runs that waited for this pipeline's data: their time has come.
        for incident in self.incidents.list(status="active", env=event.env):
            pending = incident.pending or {}
            if pending.get("action") == "wait_upstream" and event.pipeline in pending.get(
                "upstream", []
            ):
                incident.pending = {
                    "action": "rerun",
                    "at": now(),
                    "nodes": pending.get("nodes") or [],
                    "reuse_upstream": bool(pending.get("nodes")),
                }
                incident.note(AGENT, "upstream", f"{event.pipeline} succeeded: re-run now")
                self._save(incident)

    # ── scheduled actions ──────────────────────────────────────────────────

    def tick(self) -> None:
        """Run the scheduled actions that are due: :meth:`_take_due`, then :meth:`_after_pass`."""
        self._take_due()
        self._after_pass()

    def _take_due(self) -> None:
        """Take the scheduled actions that are due (the policy is asked again now).

        Each is recorded as started (``pending: running``) and saved here, under
        the lock; the re-run itself starts in :meth:`_after_pass`, outside it.
        """
        settings = self.settings()
        if settings is None:
            return
        for incident in self.incidents.list(status="active"):
            pending = incident.pending
            if not pending:
                continue
            if pending.get("action") == "running":
                since = _at(pending.get("since"))
                if since and datetime.now(timezone.utc) - since > _RUNNING_FOR:
                    self._escalate(incident, "the re-run's outcome never arrived")
                    self._save(incident)
                continue
            if pending.get("action") == "wait_upstream":
                if _due(pending.get("until")):
                    self._escalate(incident, "the upstream did not succeed in time")
                    self._save(incident)
                continue
            if pending.get("action") != "rerun" or not _due(pending.get("at")):
                continue
            allowed, why = gate.may_act(self.root, settings, incident.env, incident.pipeline)
            if not allowed:
                self._escalate(incident, f"the scheduled re-run did not happen: {why}")
                self._save(incident)
                continue
            nodes = list(pending.get("nodes") or [])
            incident.attempts += 1
            incident.pending = {"action": "running", "since": now(), "nodes": nodes}
            incident.note(
                AGENT,
                "rerun",
                f"re-run {incident.attempts}" + (f" of {', '.join(nodes)}" if nodes else ""),
            )
            self._audit("rerun", incident, "started", incident.runbook)
            self.report.actions.append(f"rerun {incident.env}/{incident.pipeline}")
            self._save(incident)  # before running: a crash must not run it twice
            self._due.append(
                (
                    incident.id,
                    incident.env,
                    incident.pipeline,
                    nodes,
                    bool(pending.get("reuse_upstream")),
                )
            )

    def _after_pass(self) -> None:
        """Start the re-runs and make the proposals the pass took on — without the lock.

        What comes back (a re-run's outcome, a re-run that could not start) is
        recorded under the lock again.
        """
        while self._due:
            incident_id, env, pipeline, nodes, reuse = self._due.pop(0)
            try:
                outcome = self.executor.rerun(self.root, env, pipeline, nodes, reuse)
            except Exception as e:  # noqa: BLE001 — a re-run that cannot start is escalated
                with engine_lock(self.root, wait=LOCK_WAIT):
                    fresh = self.incidents.get(incident_id)
                    if fresh is not None and fresh.active:
                        self._escalate(fresh, f"the re-run could not start: {e}")
                        self._save(fresh)
                continue
            if outcome is not None:
                with engine_lock(self.root, wait=LOCK_WAIT) as got:
                    if got:
                        self.handle(outcome)
                    # else: the next scan triages it from its certificate
        wanted, self._wanted = self._wanted, []
        for incident_id, event in wanted:
            from ducta.ai.agents.sentinel.propose import propose_for

            def make(incident_id: str = incident_id, event: RunEvent = event) -> None:
                try:
                    propose_for(self.root, incident_id, event, provider=self.provider)
                except Exception as e:  # noqa: BLE001 — a proposal never stops the engine
                    logger.warning("Sentinel proposal for {} failed: {}", incident_id, e)

            if self.run_later is not None:
                self.run_later(make)
            else:
                make()

    # ── what the hook does not see ─────────────────────────────────────────

    def scan(self, env: str) -> None:
        """Triage the runs of *env* not seen yet, and its late and slow pipelines."""
        settings = self.settings()
        if settings is None:
            return
        from ducta.api.services.run_certificates import certificates

        epoch = datetime.min.replace(tzinfo=timezone.utc)
        certs = sorted(
            (c for _e, c in certificates(self.root, env)),
            key=lambda c: _ended(c) or epoch,
        )
        cursor = self._cursor(env)
        if cursor is None or not cursor["scanned"]:
            # First look at this environment: history is not an incident.
            self._mark_seen(
                env, [(c.get("run_id"), _ended(c)) for c in certs], cursor, scanned=True
            )
        else:
            after = _at(cursor.get("after"))
            floor = after - _GRACE if after else None
            known = set(cursor["seen"])
            for cert in certs:
                ended = _ended(cert)
                if cert.get("run_id") in known or (floor and ended and ended < floor):
                    continue
                event = event_from_certificate(env, cert)
                self.handle(event)
                if event.status == "success":
                    self._check_slow(env, cert, certs, settings)
        self._check_sla(env, certs, settings)
        if settings.policy.rerun_stale:
            self._check_stale(env, settings)

    def _check_sla(self, env: str, certs: List[Dict[str, Any]], settings: gate.Settings) -> None:
        from ducta.api.services.metrics import project_metrics
        from ducta.setting.project_loader import validate_project

        project = validate_project(self.root)
        slas = {n: (p.metadata or {}).get("sla") for n, p in project.pipelines.items()}
        slas = {k: v for k, v in slas.items() if v}
        if not slas:
            return
        for row in project_metrics(certs, slas)["pipelines"]:
            pipeline = row["pipeline"]
            active = self.incidents.active(env, pipeline, "sla_miss")
            if row["freshness"] != "late":
                continue
            if active:
                continue
            incident, _ = self.incidents.open(env, pipeline, "sla_miss")
            incident.note(
                AGENT, "late", f"SLA {row['sla']}; last success {row['last_success_at'] or 'never'}"
            )
            self.report.opened.append(incident.id)
            self._audit("open", incident, "opened", "late for its SLA")
            event = RunEvent(env=env, pipeline=pipeline, status="late")
            self._act_on(
                incident,
                event,
                decide(self.root, event, {}, kind="sla_miss", policy=settings.policy),
                settings,
            )
            self._save(incident)

    def _check_slow(
        self, env: str, cert: Dict[str, Any], certs: List[Dict[str, Any]], settings: gate.Settings
    ) -> None:
        from ducta.api.services.metrics import project_metrics

        pipeline = str(cert.get("pipeline") or "")
        history = [
            c
            for c in certs
            if c.get("run_id") != cert.get("run_id") and c.get("pipeline") == pipeline
        ]
        row = next(
            (p for p in project_metrics(history, {})["pipelines"] if p["pipeline"] == pipeline),
            None,
        )
        p95 = row["p95_seconds"] if row and row["runs"] >= 5 else None
        duration = cert.get("duration_seconds")
        if not p95 or not duration or float(duration) <= _SLOW * float(p95):
            return
        if self.incidents.active(env, pipeline, "slow"):
            return
        incident, _ = self.incidents.open(env, pipeline, "slow")
        incident.last_run_id = cert.get("run_id")
        incident.note(AGENT, "slow", f"{float(duration):.0f}s against a p95 of {float(p95):.0f}s")
        self.report.opened.append(incident.id)
        self._audit("open", incident, "opened", "slow run")
        event = event_from_certificate(env, cert)
        self._act_on(
            incident,
            event,
            decide(self.root, event, {}, kind="slow", policy=settings.policy),
            settings,
        )
        self._save(incident)

    def _check_stale(self, env: str, settings: gate.Settings) -> None:
        from ducta.api.repositories.v2_store import V2ProjectStore
        from ducta.api.services.run_certificates import latest_successful
        from ducta.api.services.staleness import node_freshness

        store = V2ProjectStore.detect(self.root)
        if store is None:
            return
        stale: Dict[str, List[str]] = {}
        for item in node_freshness(store, latest_successful(self.root, env)).values():
            if item.state == "stale" and item.pipeline:
                stale.setdefault(item.pipeline, []).append(item.node)
        for pipeline, nodes in stale.items():
            if self.incidents.active(env, pipeline, "stale"):
                continue
            incident, _ = self.incidents.open(env, pipeline, "stale")
            incident.note(
                AGENT, "stale", f"code changed since the last success: {', '.join(sorted(nodes))}"
            )
            self.report.opened.append(incident.id)
            self._audit("open", incident, "opened", "stale nodes")
            event = RunEvent(env=env, pipeline=pipeline, status="stale", failed_nodes=sorted(nodes))
            self._act_on(
                incident,
                event,
                decide(self.root, event, {}, kind="stale", policy=settings.policy),
                settings,
            )
            self._save(incident)

    # ── passes ─────────────────────────────────────────────────────────────

    def run_once(self, envs: Sequence[str]) -> PassReport:
        """One pass: scan each environment, then run what is due. Skipped if another pass holds the lock."""
        self.report = PassReport()
        with engine_lock(self.root) as got:
            if not got:
                self.report.skipped = "another Sentinel pass is running on this project"
                return self.report
            for env in envs:
                try:
                    self.scan(env)
                except Exception as e:  # noqa: BLE001 — one environment must not stop the others
                    logger.warning("Sentinel scan of {} failed: {}", env, e)
            self._take_due()
        self._after_pass()
        return self.report

    def on_run_finished(self, event: RunEvent) -> PassReport:
        """The server's hook: triage this run, then run what is due.

        It waits for a pass in progress (passes are short: they never hold
        the lock across a re-run or a model call) rather than drop the run.
        """
        self.report = PassReport()
        with engine_lock(self.root, wait=LOCK_WAIT) as got:
            if not got:
                self.report.skipped = "another Sentinel pass is running on this project"
                return self.report
            self.handle(event)
            self._take_due()
        self._after_pass()
        return self.report


def project_envs(root: Path) -> List[str]:
    """The environments a project declares (``base`` when none)."""
    from ducta.setting.project_loader import ProjectConfigError, validate_project

    try:
        declared = list(validate_project(root).project.environments)
    except ProjectConfigError:
        declared = []
    return declared or ["base"]


def watch(
    root: Path,
    executor: Executor,
    *,
    envs: Optional[Sequence[str]] = None,
    interval: float = 60.0,
    once: bool = False,
    on_pass: Optional[Any] = None,
    provider: Any = None,
) -> PassReport:
    """The daemon: a pass every *interval* seconds (one, with *once*).

    Its re-runs and proposals happen between passes, outside the lock, so the
    server keeps triaging the project's runs meanwhile.
    """
    sentinel = Sentinel(root, executor, provider=provider)
    while True:
        report = sentinel.run_once(list(envs or project_envs(root)))
        if on_pass:
            on_pass(report)
        if once:
            return report
        time.sleep(interval)


__all__ = ["L2", "PassReport", "Sentinel", "engine_lock", "project_envs", "watch"]
