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

``ducta ai``: choose a model, check it answers, and draft pipelines with it.
"""

from __future__ import annotations

import getpass
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable, List, Optional

from loguru import logger  # type: ignore

from ducta.ai.errors import AIConfigError, AIError
from ducta.console.core import ExitCode


def _console():
    from rich.console import Console

    return Console()


def _project_root(parsed_args) -> Path:
    from ducta.setting.project_context import find_nearest_project

    # At or above, as every other command finds its project: from a project's
    # subfolder this used to fail with "No Ducta project".
    start = Path(getattr(parsed_args, "base_path", None) or Path.cwd())
    root = find_nearest_project(start)
    if root is None:
        raise AIConfigError(
            f"No Ducta project (ducta.yaml) at or above {start}: run this inside a project, "
            "or pass --base-path"
        )
    return root


def _confirm(question: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        logger.error("Not a terminal: pass --yes to confirm")
        return False
    return input(f"{question} [y/N] ").strip().lower() in ("y", "yes", "s", "si", "sí")


class AICommands:
    """Entry point for ``ducta ai``."""

    @staticmethod
    def handle(parsed_args) -> int:
        command = str(getattr(parsed_args, "ai_command", ""))
        handler = {
            "setup": AICommands.setup,
            "login": AICommands.login,
            "logout": AICommands.logout,
            "doctor": AICommands.doctor,
            "new": AICommands.new,
            "fix": AICommands.fix,
            "extend": AICommands.extend,
            "revise": AICommands.revise,
            "quality": AICommands.quality,
            "document": AICommands.document,
            "explain": AICommands.explain,
            "review": AICommands.review,
            "drafts": AICommands.drafts,
            "apply": AICommands.apply,
        }.get(command)
        if command in ("architect", "sentinel"):
            from ducta.console.commands.agent_cmds import ArchitectCommands, SentinelCommands

            handler = (
                ArchitectCommands.handle if command == "architect" else SentinelCommands.handle
            )
        if handler is None:
            logger.error("Unknown ai command: {}", command)
            return ExitCode.GENERAL_ERROR.value
        try:
            return handler(parsed_args)
        except AIError as e:
            logger.error("{}", e.message)
            return e.exit_code

    # ── configuration ────────────────────────────────────────────────────────

    @staticmethod
    def setup(parsed_args) -> int:
        from ducta.ai.config import save_config, update_config
        from ducta.ai.providers import make_provider

        # Only what was passed changes; timeouts, attempts and the rest are kept.
        changes = {
            key: getattr(parsed_args, key, None)
            for key in ("model", "base_url", "api_key_env", "effort")
            if getattr(parsed_args, key, None)
        }
        config = update_config(parsed_args.provider, changes)
        console = _console()
        if not config.model and config.is_local:
            # A local server knows what it has: take the first model it serves.
            try:
                models = make_provider(config).list_models()
            except AIError as e:
                raise type(e)(f"{e.message} Pass --model to set one without asking.") from e
            if not models:
                raise AIConfigError(
                    f"{config.label} serves no models yet (e.g. `ollama pull qwen2.5-coder`)"
                )
            config.model = pick_model(models)
            others = f"{len(models) - 1} other(s) available; " if len(models) > 1 else ""
            console.print(f"Model: [cyan]{config.model}[/] ({others}--model to choose)")
            if not _CODE_MODEL.search(config.model):
                console.print(
                    "  [yellow]![/] A code model of 7B or more drafts far better "
                    "(e.g. `ollama pull qwen2.5-coder:7b`)."
                )
        path = save_config(config)
        console.print(f"[green]✓[/] {config.label} saved to {path}")
        if config.is_local:
            console.print("  Requests stay on this machine.")
        else:
            from ducta.ai.secrets import env_key_allowed

            usable = config.api_key_env and env_key_allowed(config)
            env = f"set {config.api_key_env} or " if usable else ""
            console.print(f"  API key: {env}run [bold]ducta ai login[/].")
        console.print("  Check it with [bold]ducta ai doctor[/].")
        return ExitCode.SUCCESS.value

    @staticmethod
    def login(parsed_args) -> int:
        from ducta.ai.config import PRESETS
        from ducta.ai.secrets import keychain_user, store_key

        provider, base_url = _key_target(parsed_args)
        if not sys.stdin.isatty():
            raise AIConfigError("`ducta ai login` asks for the key; run it in a terminal")
        key = getpass.getpass(f"API key for {PRESETS[provider].label} (hidden): ")
        store_key(provider, key, base_url)
        _console().print(
            f"[green]✓[/] Key kept in the system keychain for "
            f"'{keychain_user(provider, base_url)}'."
        )
        return ExitCode.SUCCESS.value

    @staticmethod
    def logout(parsed_args) -> int:
        from ducta.ai.secrets import delete_key

        provider, base_url = _key_target(parsed_args)
        removed = delete_key(provider, base_url)
        _console().print(
            f"[green]✓[/] Key for '{provider}' removed from the keychain."
            if removed
            else f"No key for '{provider}' was in the keychain."
        )
        return ExitCode.SUCCESS.value

    @staticmethod
    def doctor(parsed_args) -> int:
        from rich.table import Table

        from ducta.ai.config import config_path, load_config
        from ducta.ai.providers import make_provider
        from ducta.ai.secrets import keychain_available, resolve_key

        console = _console()
        config = load_config()
        key = resolve_key(config)
        table = Table(show_header=False, box=None)
        table.add_row("Config", str(config_path()))
        table.add_row("Provider", config.label)
        table.add_row("Endpoint", config.endpoint)
        table.add_row("Model", config.model or "[yellow](not set)[/]")
        table.add_row(
            "Privacy",
            "local — nothing leaves this machine"
            if config.is_local
            else f"remote — project configuration and code are sent to {config.endpoint}",
        )
        table.add_row("API key", f"{key.masked} ({key.source})" if key.value else "none")
        table.add_row("Keychain", "available" if keychain_available() else "not available")
        console.print(table)

        provider = make_provider(config)
        with console.status("Contacting the provider…"):
            models = provider.list_models()
        console.print(f"[green]✓[/] Connected — {len(models)} model(s) available.")
        if config.model and models and config.model not in models:
            console.print(
                f"[yellow]![/] '{config.model}' is not among them: "
                + ", ".join(models[:15])
                + (" …" if len(models) > 15 else "")
            )
            return ExitCode.CONFIGURATION_ERROR.value
        if not config.model:
            console.print("Models: " + ", ".join(models[:30]))
        return ExitCode.SUCCESS.value

    # ── drafting ─────────────────────────────────────────────────────────────

    @staticmethod
    def new(parsed_args) -> int:
        from ducta.ai.builder import generate

        return AICommands._draft(
            parsed_args,
            "Drafting",
            lambda root, provider, report: generate(
                root,
                parsed_args.request,
                provider,
                max_attempts=getattr(parsed_args, "attempts", None),
                on_attempt=report,
            ),
        )

    @staticmethod
    def fix(parsed_args) -> int:
        from ducta.ai.builder import fix

        error = ""
        if getattr(parsed_args, "error_file", None):
            try:
                error = Path(parsed_args.error_file).read_text(encoding="utf-8")
            except OSError as e:
                raise AIConfigError(f"Cannot read {parsed_args.error_file}: {e}") from e
        return AICommands._draft(
            parsed_args,
            f"Fixing {parsed_args.pipeline}",
            lambda root, provider, report: fix(
                root,
                parsed_args.pipeline,
                provider,
                note=getattr(parsed_args, "note", None) or "",
                error=error,
                max_attempts=getattr(parsed_args, "attempts", None),
                on_attempt=report,
            ),
        )

    @staticmethod
    def extend(parsed_args) -> int:
        from ducta.ai.extend import extend

        return AICommands._draft(
            parsed_args,
            f"Adding nodes to {parsed_args.pipeline}",
            lambda root, provider, report: extend(
                root,
                parsed_args.pipeline,
                parsed_args.request,
                provider,
                max_attempts=getattr(parsed_args, "attempts", None),
                on_attempt=report,
            ),
        )

    @staticmethod
    def revise(parsed_args) -> int:
        from ducta.ai.builder import load_draft, revise

        root = _project_root(parsed_args)
        previous = load_draft(root, parsed_args.draft_id)
        return AICommands._draft(
            parsed_args,
            f"Revising {previous.id}",
            lambda root, provider, report: revise(
                root,
                previous,
                parsed_args.note,
                provider,
                max_attempts=getattr(parsed_args, "attempts", None),
                on_attempt=report,
            ),
        )

    @staticmethod
    def quality(parsed_args) -> int:
        from ducta.ai.proposals import propose_quality

        return AICommands._draft(
            parsed_args,
            f"Proposing checks for {parsed_args.pipeline}.{parsed_args.node}",
            lambda root, provider, report: propose_quality(
                root,
                parsed_args.pipeline,
                parsed_args.node,
                provider,
                env=parsed_args.env,
                note=getattr(parsed_args, "note", None) or "",
                max_attempts=getattr(parsed_args, "attempts", None),
                on_attempt=report,
            ),
        )

    @staticmethod
    def document(parsed_args) -> int:
        from ducta.ai.proposals import propose_docs

        return AICommands._draft(
            parsed_args,
            "Documenting the project",
            lambda root, provider, report: propose_docs(
                root,
                provider,
                env=parsed_args.env,
                note=getattr(parsed_args, "note", None) or "",
                max_attempts=getattr(parsed_args, "attempts", None),
                on_attempt=report,
            ),
        )

    @staticmethod
    def explain(parsed_args) -> int:
        from rich.markdown import Markdown

        from ducta.ai.config import load_config
        from ducta.ai.explain import explain_failure
        from ducta.ai.providers import make_provider
        from ducta.api.services.diagnosis import diagnose

        source = parsed_args.error_file
        try:
            error = (
                sys.stdin.read()
                if source == "-"
                else Path(source).read_text(encoding="utf-8", errors="replace")
            )
        except OSError as e:
            raise AIConfigError(f"Cannot read {source}: {e}") from e
        if not error.strip():
            raise AIConfigError(f"{source} is empty: pass the error or traceback a run failed with")
        root = _project_root(parsed_args)
        last = next((line for line in reversed(error.strip().splitlines()) if line.strip()), "")
        diagnosis = diagnose(
            {"error_message": last}, [{"message": last, "traceback": error}], root, None, None
        )
        config = load_config()
        config.require_model()
        provider = make_provider(config)
        as_json = getattr(parsed_args, "output_format", "rich") == "json"
        console = _console()
        if not as_json:
            where = (
                "locally"
                if config.is_local
                else f"at {config.endpoint} (the error and code around it are sent)"
            )
            console.print(f"Explaining with [cyan]{config.model}[/] {where}…")
        with console.status("Waiting for the model…") if not as_json else _null():
            explanation = explain_failure(
                root, diagnosis, error, provider, note=getattr(parsed_args, "note", None) or ""
            )
        if as_json:
            print(
                json.dumps({"diagnosis": diagnosis, **explanation.to_dict()}, indent=2, default=str)
            )
        else:
            console.print()
            console.print(Markdown(explanation.text))
            console.print(
                f"\n[dim]{diagnosis['title']} — explained by {explanation.model}. Nothing was changed.[/]"
            )
        return ExitCode.SUCCESS.value

    @staticmethod
    def review(parsed_args) -> int:
        from ducta.ai.review import SEVERITIES, review_node, save_review

        root = _project_root(parsed_args)
        provider = None
        as_json = getattr(parsed_args, "output_format", "rich") == "json"
        console = _console()
        if not getattr(parsed_args, "no_ai", False):
            from ducta.ai.config import load_config
            from ducta.ai.providers import make_provider

            config = load_config()
            config.require_model()
            provider = make_provider(config)
            if not as_json:
                where = (
                    "locally"
                    if config.is_local
                    else f"at {config.endpoint} (the node's code and settings are sent)"
                )
                console.print(f"Reviewing with [cyan]{config.model}[/] {where}…")
        whole = not getattr(parsed_args, "node", None)
        result: Any
        with console.status("Reviewing…") if not as_json else _null():
            if whole:
                from ducta.ai.pipeline_review import review_pipeline, save_pipeline_review

                result = review_pipeline(
                    root,
                    parsed_args.pipeline,
                    provider,
                    env=parsed_args.env,
                    note=getattr(parsed_args, "note", None) or "",
                )
                save_pipeline_review(root, result)
            else:
                node_review = review_node(
                    root,
                    parsed_args.pipeline,
                    parsed_args.node,
                    provider,
                    env=parsed_args.env,
                    note=getattr(parsed_args, "note", None) or "",
                )
                save_review(root, node_review)
                result = node_review
        if as_json:
            print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        else:
            AICommands._show_review(console, result)
        fail_on = getattr(parsed_args, "fail_on", None)
        if fail_on:
            worst = SEVERITIES.index(fail_on)
            if any(SEVERITIES.index(f.severity) <= worst for f in result.findings):
                return ExitCode.VALIDATION_ERROR.value
        return ExitCode.SUCCESS.value

    @staticmethod
    def _show_review(console, result) -> None:
        style = {"high": "red", "medium": "yellow", "low": "cyan"}
        console.print()
        if not result.findings:
            console.print("[green]✓ Nothing to report.[/]")
        for f in result.findings:
            where = ":".join(str(x) for x in (f.file, f.line) if x)
            where = where or (f"setting {f.key}" if f.key else "")
            who = "Ducta" if f.source == "ducta" else "AI"
            node = f"{f.node}: " if getattr(f, "node", None) else ""
            console.print(
                f"[{style[f.severity]}]{f.severity:<6}[/] [bold]{node}{f.title}[/] "
                f"[dim]({f.area} · {who}{' · ' + where if where else ''})[/]",
                highlight=False,
            )
            if f.code:
                console.print(f"       [dim]{f.code}[/]", highlight=False)
            if f.detail:
                console.print(f"       {f.detail}", highlight=False)
            if f.suggestion:
                console.print(f"       [green]→[/] {f.suggestion}", highlight=False)
        ours = sum(1 for f in result.findings if f.source == "ducta")
        summary = f"\n[dim]{ours} from Ducta's checks"
        if result.model:
            summary += f", {len(result.findings) - ours} from {result.model}"
            if result.dropped:
                summary += (
                    f" ({result.dropped} dropped: they cited lines or settings that do not exist)"
                )
        console.print(summary + ". Nothing was changed.[/]")
        if result.notes:
            console.print(f"[yellow]{result.notes}[/]")
        ideas = getattr(result, "ideas", None) or []
        if ideas:
            console.print("\n[bold]Ideas for new nodes[/] [dim](the model's, not checked)[/]")
            for idea in ideas:
                console.print(f"  • {idea}", highlight=False)
            console.print(f'[dim]To add one: ducta ai extend {result.pipeline} "<the idea>"[/]')
        if result.findings:
            console.print(
                f'[dim]To act on one: ducta ai fix {result.pipeline} --note "<the finding>"[/]'
            )

    @staticmethod
    def drafts(parsed_args) -> int:
        from rich.table import Table

        from ducta.ai.builder import list_drafts

        root = _project_root(parsed_args)
        drafts = list_drafts(root)
        if not drafts:
            _console().print('No drafts yet: `ducta ai new "…"`.')
            return ExitCode.SUCCESS.value
        table = Table()
        for column in ("Id", "Kind", "Request", "Model", "State"):
            table.add_column(column)
        for d in drafts:
            state = (
                f"applied {d.applied_at[:16]}"
                if d.applied_at
                else ("[green]valid[/]" if d.ok else "[red]invalid[/]")
            )
            request = d.request if len(d.request) <= 60 else d.request[:57] + "…"
            table.add_row(d.id, d.kind, request, d.model, state)
        _console().print(table)
        return ExitCode.SUCCESS.value

    @staticmethod
    def _draft(parsed_args, verb: str, make: Callable[..., Any]) -> int:
        from ducta.ai.builder import save_draft
        from ducta.ai.config import load_config
        from ducta.ai.providers import make_provider

        root = _project_root(parsed_args)
        config = load_config()
        config.require_model()
        provider = make_provider(config)
        as_json = getattr(parsed_args, "output_format", "rich") == "json"
        console = _console()
        if not as_json:
            where = (
                "locally"
                if config.is_local
                else f"at {config.endpoint} (project configuration and code are sent)"
            )
            console.print(f"{verb} with [cyan]{config.model}[/] {where}…")

        def report(attempt: Any) -> None:
            if as_json:
                return
            status = (
                "[green]valid[/]"
                if not attempt.errors and not attempt.rejected
                else f"[yellow]{attempt.errors + len(attempt.rejected)} problem(s)[/]"
            )
            console.print(f"  attempt {attempt.number}: {len(attempt.files)} file(s), {status}")
            if attempt.messages:
                console.print(f"    [dim]{attempt.messages[0]}[/]", highlight=False)

        with console.status("Waiting for the model…") if not as_json else _null():
            draft = make(root, provider, report)
        path = save_draft(root, draft)

        if as_json:
            print(
                json.dumps(
                    {**draft.to_dict(), "diff": draft.diff(root)}, indent=2, ensure_ascii=False
                )
            )
        else:
            AICommands._show(console, root, draft)
            console.print(f"\nDraft [bold]{draft.id}[/] saved to {path.relative_to(root)}")

        if draft.kind == "blueprint":
            # A design, not files to write: what comes next is building it.
            if not as_json and draft.ok:
                console.print(
                    f"Build it with [bold]ducta ai architect build {draft.id}[/], or ask for "
                    f'changes with [bold]ducta ai revise {draft.id} --note "…"[/].'
                )
            return ExitCode.SUCCESS.value if draft.ok else ExitCode.VALIDATION_ERROR.value
        if not getattr(parsed_args, "write", False):
            if not as_json and draft.ok:
                console.print(f"Write it with [bold]ducta ai apply {draft.id}[/].")
            elif not as_json:
                console.print(
                    "Next: tell the model what to change with "
                    f'[bold]ducta ai revise {draft.id} --note "…"[/], try again with more '
                    "[bold]--attempts[/], or write it anyway with "
                    f"[bold]ducta ai apply {draft.id} --force[/] and fix it by hand."
                )
            return ExitCode.SUCCESS.value if draft.ok else ExitCode.VALIDATION_ERROR.value
        return AICommands._write(console, root, draft, parsed_args)

    @staticmethod
    def apply(parsed_args) -> int:
        from ducta.ai.builder import load_draft

        root = _project_root(parsed_args)
        draft = load_draft(root, parsed_args.draft_id)
        console = _console()
        AICommands._show(console, root, draft)
        return AICommands._write(console, root, draft, parsed_args)

    @staticmethod
    def _write(console, root: Path, draft, parsed_args) -> int:
        from ducta.ai.builder import apply_draft

        force = bool(getattr(parsed_args, "force", False))
        if not draft.ok and not force:
            console.print("[red]The draft does not validate[/]; pass --force to write it anyway.")
            return ExitCode.VALIDATION_ERROR.value
        if not parsed_args.yes and not sys.stdin.isatty():
            # Nobody could be asked, so nothing was written: not a success a
            # script may take for "applied".
            console.print("Nothing written: not a terminal, so pass --yes to confirm.")
            return ExitCode.VALIDATION_ERROR.value
        if not _confirm(f"Write {len(draft.files)} file(s) to {root}?", parsed_args.yes):
            console.print("Nothing written.")
            return ExitCode.SUCCESS.value
        written = apply_draft(root, draft, force=force)
        console.print(f"[green]✓[/] Wrote {', '.join(written)}. Nothing was committed or run.")
        console.print("  Next: [bold]ducta config validate[/], then run it in dev.")
        return ExitCode.SUCCESS.value

    @staticmethod
    def _show(console, root: Path, draft) -> None:
        from rich.syntax import Syntax

        if draft.kind == "blueprint":
            # The design itself; its rendered files are stubs until it is built.
            from ducta.ai.agents.architect.design import blueprint_of

            try:
                console.print(
                    Syntax(blueprint_of(draft).to_yaml(), "yaml", theme="ansi_dark", word_wrap=True)
                )
            except AIError:
                console.print(f"[dim]{draft.raw_answer}[/]", highlight=False)
            if draft.files:
                console.print(f"[dim]It would add: {', '.join(sorted(draft.files))}[/]")
            if draft.evidence:
                console.print(f"[yellow]{draft.evidence}[/]", highlight=False)
            diff = ""
        else:
            diff = draft.diff(root)
        if diff:
            console.print(Syntax(diff, "diff", theme="ansi_dark", word_wrap=True))
        if draft.notes:
            console.print(f"[dim]{draft.notes}[/]")
        blocking = {json.dumps(p, sort_keys=True, default=str) for p in draft.blocking}
        for p in draft.blocking:
            console.print(f"[red]error[/] {_where(p)} {p.get('message')}")
        others = [
            p
            for p in draft.problems
            if json.dumps(p, sort_keys=True, default=str) not in blocking
            and p.get("severity") in ("error", "warning")
        ]
        if others:
            console.print(f"[dim]{len(others)} problem(s) the project already had, or warnings:[/]")
            for p in others[:10]:
                console.print(f"[dim]  {p.get('severity')} {_where(p)} {p.get('message')}[/]")
        console.print(
            "[green]✓ The draft validates in every environment.[/]"
            if draft.ok
            else f"[red]✗ Still invalid after {len(draft.attempts)} attempt(s).[/]"
        )
        if draft.ok and draft.kind == "fix":
            console.print("  Checked without running it: run the pipeline in dev to confirm.")


_CODE_MODEL = re.compile(r"cod(?:e|er|estral)|devstral|starcoder", re.IGNORECASE)
_SIZE = re.compile(r"(\d+(?:\.\d+)?)b\b", re.IGNORECASE)


def pick_model(models: List[str]) -> str:
    """The model a local server serves that drafts best: a code model, the larger the better."""

    def size(name: str) -> float:
        m = _SIZE.search(name)
        return float(m.group(1)) if m else 0.0

    code = [m for m in models if _CODE_MODEL.search(m)]
    return max(code, key=size) if code else models[0]


def _key_target(parsed_args) -> tuple:
    """The provider and endpoint a key is for: the configured ones, or a preset's own."""
    from ducta.ai.config import PRESETS, load_config

    try:
        config = load_config()
    except AIError:
        config = None
    provider = getattr(parsed_args, "provider", None) or (config.provider if config else None)
    if not provider:
        raise AIConfigError(
            "Which provider is the key for? Run `ducta ai setup --provider <name>` first, "
            "or pass --provider (anthropic, openai, openai_compatible)"
        )
    if provider not in PRESETS:
        raise AIConfigError(f"Unknown provider '{provider}' (one of: {', '.join(PRESETS)})")
    if config is not None and config.provider == provider:
        return provider, config.base_url
    return provider, PRESETS[provider].base_url


def _where(p: Any) -> str:
    return ":".join(str(x) for x in (p.get("file"), p.get("line")) if x)


class _null:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *exc: Any) -> Optional[bool]:
        return None


def handle_ai(parsed_args) -> int:
    return AICommands.handle(parsed_args)
