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

``ducta ai architect`` and ``ducta ai sentinel``: Ducta's agents from the
terminal. The commands that need no model (``architect check``/``scaffold``,
``sentinel status``/``incidents``/``show``/``triage``) also answer in JSON, for
scripts and for assistants that bring their own reasoning.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from ducta.ai.errors import AIConfigError
from ducta.console.commands.ai_cmds import AICommands, _console, _project_root
from ducta.console.core import ExitCode


def _json(parsed_args) -> bool:
    return getattr(parsed_args, "output_format", "rich") == "json"


def _print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def _read(path: str) -> str:
    try:
        return Path(path).expanduser().read_text(encoding="utf-8")
    except OSError as e:
        raise AIConfigError(f"Cannot read {path}: {e}") from e


# ── Architect ───────────────────────────────────────────────────────────────


class ArchitectCommands:
    @staticmethod
    def handle(parsed_args) -> int:
        command = getattr(parsed_args, "architect_command", "")
        return {
            "plan": ArchitectCommands.plan,
            "check": ArchitectCommands.check,
            "scaffold": ArchitectCommands.scaffold,
            "build": ArchitectCommands.build,
            "verify": ArchitectCommands.verify,
        }[command](parsed_args)

    @staticmethod
    def plan(parsed_args) -> int:
        from ducta.ai.agents.architect.design import NeedsAnswers, design

        def make(root, provider, report):
            return design(
                root,
                parsed_args.request,
                provider,
                note=parsed_args.note or "",
                max_attempts=parsed_args.attempts,
                on_attempt=report,
            )

        try:
            return AICommands._draft(parsed_args, "Designing", make)
        except NeedsAnswers as asked:
            if _json(parsed_args):
                _print_json({"questions": asked.questions})
            else:
                console = _console()
                console.print("The model needs these answered before it designs:")
                for q in asked.questions:
                    console.print(f"  • {q}")
                console.print('Run it again with [bold]--note "<your answers>"[/].')
            return ExitCode.VALIDATION_ERROR.value

    @staticmethod
    def check(parsed_args) -> int:
        from ducta.ai.agents.architect.design import check

        root = _project_root(parsed_args)
        report = check(root, _read(parsed_args.blueprint))
        if _json(parsed_args):
            _print_json(report.to_dict())
        else:
            console = _console()
            for e in report.errors:
                console.print(f"[red]error[/] {e}", highlight=False)
            for w in report.warnings:
                console.print(f"[yellow]warning[/] {w}", highlight=False)
            if report.ok:
                console.print(
                    f"[green]✓ Blueprint {report.blueprint.name} checks[/] — it would add: "  # type: ignore[union-attr]
                    + ", ".join(sorted(report.files))
                )
        return ExitCode.SUCCESS.value if report.ok else ExitCode.VALIDATION_ERROR.value

    @staticmethod
    def scaffold(parsed_args) -> int:
        """The blueprint's files with stub functions: a draft, no model involved."""
        from ducta.ai.agents.architect.build import scaffold
        from ducta.ai.builder import save_draft

        root = _project_root(parsed_args)
        draft = scaffold(root, _read(parsed_args.blueprint))
        path = save_draft(root, draft)
        console = _console()
        if _json(parsed_args):
            _print_json({**draft.to_dict(), "diff": draft.diff(root)})
        else:
            AICommands._show(console, root, draft)
            console.print(f"\nDraft [bold]{draft.id}[/] saved to {path.relative_to(root)}")
        if not draft.ok:
            return ExitCode.VALIDATION_ERROR.value
        if not getattr(parsed_args, "write", False):
            if not _json(parsed_args):
                console.print(
                    f"Write it with [bold]ducta ai apply {draft.id}[/]; then write each "
                    "function's body (they raise NotImplementedError)."
                )
            return ExitCode.SUCCESS.value
        parsed_args.force = False
        return AICommands._write(console, root, draft, parsed_args)

    @staticmethod
    def build(parsed_args) -> int:
        from ducta.ai.agents.architect.blueprint import load_blueprint
        from ducta.ai.agents.architect.build import build
        from ducta.ai.agents.architect.design import blueprint_of
        from ducta.ai.builder import load_draft

        source = parsed_args.blueprint

        def make(root, provider, report):
            if Path(source).expanduser().is_file():
                bp, problems = load_blueprint(_read(source))
                if bp is None or problems:
                    raise AIConfigError(f"{source}: {'; '.join(problems)}")
                blueprint_id = None
            else:
                draft = load_draft(root, source)
                bp, blueprint_id = blueprint_of(draft), draft.id
            return build(
                root,
                bp,
                provider,
                blueprint_id=blueprint_id,
                max_attempts=parsed_args.attempts,
                on_attempt=report,
            )

        return AICommands._draft(parsed_args, "Building", make)

    @staticmethod
    def verify(parsed_args) -> int:
        from ducta.ai.agents.architect.verify import verify

        root = _project_root(parsed_args)
        report = verify(
            root,
            parsed_args.pipelines,
            env=parsed_args.env,
            run=parsed_args.run,
            tests=parsed_args.tests,
            start_date=parsed_args.start_date,
            end_date=parsed_args.end_date,
        )
        if _json(parsed_args):
            _print_json(report.to_dict())
        else:
            console = _console()
            console.print(f"Pipelines: {', '.join(report.pipelines)}")
            for e in report.errors:
                console.print(f"[red]error[/] {e}", highlight=False)
            for w in report.warnings:
                console.print(f"[yellow]warning[/] {w}", highlight=False)
            for r in report.runs:
                mark = "[green]✓[/]" if r["ok"] else "[red]✗[/]"
                console.print(
                    f"{mark} ran {r['pipeline']} in {parsed_args.env} (exit {r['exit_code']})"
                )
                if not r["ok"]:
                    console.print(f"[dim]{r['output']}[/]", highlight=False)
            for t in report.tests:
                console.print(f"  test: {t}")
            if report.ok:
                console.print("[green]✓ Verified.[/]")
            for step in report.next_steps:
                console.print(f"  next: [bold]{step}[/]", highlight=False)
        return ExitCode.SUCCESS.value if report.ok else ExitCode.VALIDATION_ERROR.value


# ── Sentinel ────────────────────────────────────────────────────────────────


class SentinelCommands:
    @staticmethod
    def handle(parsed_args) -> int:
        command = getattr(parsed_args, "sentinel_command", "")
        return {
            "status": SentinelCommands.status,
            "incidents": SentinelCommands.incidents,
            "show": SentinelCommands.show,
            "triage": SentinelCommands.triage,
            "watch": SentinelCommands.watch,
            "pause": SentinelCommands.pause,
            "resume": SentinelCommands.resume,
            "resolve": SentinelCommands.close,
            "ignore": SentinelCommands.close,
        }[command](parsed_args)

    @staticmethod
    def status(parsed_args) -> int:
        from ducta.ai.agents.sentinel import policy as gate
        from ducta.ai.agents.sentinel.incidents import Incidents

        root = _project_root(parsed_args)
        settings = gate.Settings.of(root)
        if settings is None:
            raise AIConfigError("The project does not load: `ducta config validate` says why")
        p = settings.policy
        active = Incidents(root).list(status="active")
        data: Dict[str, Any] = {
            "enabled": p.enabled,
            "paused": gate.is_paused(root),
            "environments": list(p.environments),
            "protected": list(settings.protected),
            "pipelines": list(p.pipelines),
            "actions_today": gate.actions_today(root),
            "max_actions_per_day": p.max_actions_per_day,
            "active": len(active),
            "escalated": sum(1 for i in active if i.status == "escalated"),
        }
        if _json(parsed_args):
            _print_json(data)
            return ExitCode.SUCCESS.value
        console = _console()
        if not p.enabled:
            console.print(
                "Sentinel is [yellow]off[/] for this project: set [bold]sentinel: {enabled: true}[/] "
                "in ducta.yaml (it acts only in sentinel.environments, never in "
                f"{', '.join(settings.protected)})."
            )
        else:
            state = "[yellow]paused[/]" if data["paused"] else "[green]on[/]"
            console.print(
                f"Sentinel is {state}: acts in {', '.join(p.environments) or 'no environment'}; "
                f"observes and proposes in {', '.join(settings.protected)}."
            )
            console.print(f"Re-runs today: {data['actions_today']} of {p.max_actions_per_day}.")
        console.print(f"Active incidents: {data['active']} ({data['escalated']} need a person).")
        return ExitCode.SUCCESS.value

    @staticmethod
    def incidents(parsed_args) -> int:
        from rich.table import Table

        from ducta.ai.agents.sentinel.incidents import Incidents

        root = _project_root(parsed_args)
        found = Incidents(root).list(status=parsed_args.incident_status, env=parsed_args.env)
        if _json(parsed_args):
            _print_json([i.to_dict() for i in found])
            return ExitCode.SUCCESS.value
        if not found:
            _console().print(f"No {parsed_args.incident_status} incidents.")
            return ExitCode.SUCCESS.value
        table = Table()
        for column in ("Id", "Env", "Pipeline", "Kind", "Status", "Runbook", "Why"):
            table.add_column(column)
        for i in found:
            why = i.reason if len(i.reason) <= 70 else i.reason[:67] + "…"
            table.add_row(
                i.id, i.env, i.pipeline, i.kind, i.status, f"{i.runbook} ({i.level})", why
            )
        _console().print(table)
        return ExitCode.SUCCESS.value

    @staticmethod
    def show(parsed_args) -> int:
        from ducta.ai.agents.sentinel.incidents import Incidents

        root = _project_root(parsed_args)
        incident = Incidents(root).get(parsed_args.incident_id)
        if incident is None:
            raise AIConfigError(f"No incident {parsed_args.incident_id}")
        if _json(parsed_args):
            _print_json(incident.to_dict())
            return ExitCode.SUCCESS.value
        console = _console()
        console.print(
            f"[bold]{incident.id}[/] {incident.kind} of {incident.pipeline} in {incident.env} — "
            f"{incident.status} ({incident.runbook}, {incident.level})"
        )
        if incident.reason:
            console.print(f"  {incident.reason}", highlight=False)
        for entry in incident.timeline:
            console.print(
                f"  [dim]{entry.get('at', '')[:19]}[/] {entry.get('actor')}: {entry.get('action')} "
                f"{entry.get('detail', '')}",
                highlight=False,
            )
        if incident.links.get("draft"):
            console.print(
                f"  Fix draft: [bold]ducta ai apply {incident.links['draft']}[/] (review it first)"
            )
        if incident.links.get("explanation"):
            from ducta.ai.explain import load_explanation

            found = load_explanation(root, str(incident.links["explanation"]))
            if found is not None:
                console.print(f"\n{found.text}", highlight=False)
        return ExitCode.SUCCESS.value

    @staticmethod
    def triage(parsed_args) -> int:
        from ducta.ai.agents.sentinel import policy as gate
        from ducta.ai.agents.sentinel.triage import decide, diagnosis_of, event_from_certificate
        from ducta.api.services.run_certificates import certificates

        root = _project_root(parsed_args)
        found = next(
            (
                (env, c)
                for env, c in certificates(root, parsed_args.env)
                if c.get("run_id") == parsed_args.run_id
            ),
            None,
        )
        if found is None:
            raise AIConfigError(f"No run certificate {parsed_args.run_id}")
        env, cert = found
        event = event_from_certificate(str(env or parsed_args.env or "base"), cert)
        settings = gate.Settings.of(root)
        data: Dict[str, Any] = {
            "run_id": event.run_id,
            "env": event.env,
            "pipeline": event.pipeline,
            "status": event.status,
        }
        if event.failed:
            diagnosis = diagnosis_of(root, event)
            decision = decide(root, event, diagnosis, policy=settings.policy if settings else None)
            allowed, why = (False, "the project does not load")
            if settings is not None:
                allowed, why = gate.may_act(root, settings, event.env, event.pipeline)
            data.update(
                diagnosis=diagnosis,
                runbook=decision.runbook,
                level=decision.level,
                reason=decision.reason,
                may_act=allowed if decision.level == "L1" else None,
                why_not=why if decision.level == "L1" and not allowed else None,
            )
        if _json(parsed_args):
            _print_json(data)
            return ExitCode.SUCCESS.value
        console = _console()
        console.print(f"{event.pipeline} in {event.env}: {event.status}")
        if event.failed:
            console.print(
                f"  {data['diagnosis'].get('title')}: {str(data['diagnosis'].get('message') or '')[:300]}",
                highlight=False,
            )
            console.print(
                f"  Runbook: [bold]{data['runbook']}[/] ({data['level']}) — {data['reason']}",
                highlight=False,
            )
            if data.get("why_not"):
                console.print(f"  Sentinel would not act: {data['why_not']}", highlight=False)
        return ExitCode.SUCCESS.value

    @staticmethod
    def watch(parsed_args) -> int:
        from ducta.ai.agents.sentinel.actions import CliExecutor
        from ducta.ai.agents.sentinel.engine import project_envs, watch

        root = _project_root(parsed_args)
        envs: List[str] = parsed_args.envs or project_envs(root)
        console = _console()

        def on_pass(report: Any) -> None:
            if _json(parsed_args):
                print(json.dumps(report.to_dict(), ensure_ascii=False), flush=True)
                return
            if report.skipped:
                console.print(f"[dim]{report.skipped}[/]")
                return
            console.print(
                f"pass: {report.events} run(s) triaged, {len(report.opened)} opened, "
                f"{len(report.resolved)} resolved, {len(report.actions)} re-run(s), "
                f"{len(report.escalated)} escalated"
            )

        if not _json(parsed_args):
            console.print(
                f"Sentinel watching {', '.join(envs)} in {root}"
                + (
                    ""
                    if parsed_args.once
                    else f" every {parsed_args.interval:.0f}s (Ctrl-C to stop)"
                )
            )
        try:
            watch(
                root,
                CliExecutor(timeout=parsed_args.rerun_timeout or None),
                envs=envs,
                interval=parsed_args.interval,
                once=parsed_args.once,
                on_pass=on_pass,
            )
        except KeyboardInterrupt:
            console.print("Stopped.")
        return ExitCode.SUCCESS.value

    @staticmethod
    def pause(parsed_args) -> int:
        from ducta.ai.agents.sentinel import policy as gate

        root = _project_root(parsed_args)
        gate.pause(root, by="cli", reason=parsed_args.reason)
        _console().print("Sentinel paused: it keeps opening incidents, and re-runs nothing.")
        return ExitCode.SUCCESS.value

    @staticmethod
    def resume(parsed_args) -> int:
        from ducta.ai.agents.sentinel import policy as gate

        gate.resume(_project_root(parsed_args), by="cli")
        _console().print("Sentinel resumed.")
        return ExitCode.SUCCESS.value

    @staticmethod
    def close(parsed_args) -> int:
        from ducta.ai.agents import audit
        from ducta.ai.agents.sentinel.engine import LOCK_WAIT, engine_lock
        from ducta.ai.agents.sentinel.incidents import Incidents
        from ducta.ai.agents.store import now

        root = _project_root(parsed_args)
        to = "resolved" if parsed_args.sentinel_command == "resolve" else "ignored"
        incidents = Incidents(root)
        # Under the engine's lock, so a pass running now does not write over it.
        with engine_lock(root, wait=LOCK_WAIT) as got:
            if not got:
                raise AIConfigError("Sentinel is busy with this project; try again in a moment")
            incident = incidents.get(parsed_args.incident_id)
            if incident is None:
                raise AIConfigError(f"No incident {parsed_args.incident_id}")
            if not incident.active:
                raise AIConfigError(f"Incident {incident.id} is already {incident.status}")
            incident.status = to
            incident.pending = None
            if to == "resolved":
                incident.resolved_at = now()
            incident.note("cli", to, parsed_args.note)
            incidents.save(incident)
        audit.record(
            root,
            "sentinel",
            to,
            target={"incident": incident.id, "env": incident.env, "pipeline": incident.pipeline},
            result=to,
            reason=parsed_args.note,
            actor="cli",
        )
        _console().print(f"Incident {incident.id} {to}.")
        return ExitCode.SUCCESS.value
