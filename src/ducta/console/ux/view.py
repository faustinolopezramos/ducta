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

How the ``ducta`` command shows what it does.

Two modes. *Classic* prints every log line as it happens: what the library, the
API server, ``--verbose`` and ``DUCTA_CONSOLE=classic`` show. *Compact*, the
CLI's default, shows a run the way a person reads it — a header, one line per
node, a summary, and a single error block that says where and what to do next.
Everything still goes to the log file at DEBUG; only the terminal changes.

The engine reaches this module lazily, to ask :func:`is_compact` or to hand over
an event. A process that never calls :func:`set_mode` is unaffected.
"""

from __future__ import annotations

import difflib
import threading
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

_lock = threading.RLock()
_compact = False
_quiet = False


def set_mode(*, compact: bool, quiet: bool = False) -> None:
    """Choose how the terminal shows a run (the CLI calls this once, at start)."""
    global _compact, _quiet
    _compact, _quiet = compact, quiet
    reset_run()


def is_compact() -> bool:
    return _compact


def is_quiet() -> bool:
    """``--quiet`` in compact mode: errors and the final line only."""
    return _compact and _quiet


def console() -> Any:
    from ducta.console.ux.rich_logger import RichLoggerManager

    return RichLoggerManager.get_console()


def display_path(path: Any) -> str:
    """*path* as the user would type it: relative to here, or to ``~``."""
    p = Path(str(path))
    try:
        resolved = p.resolve()
    except OSError:
        return str(p)
    for base, prefix in ((Path.cwd(), ""), (Path.home(), "~/")):
        try:
            rel = resolved.relative_to(base.resolve())
        except ValueError:
            continue
        text = rel.as_posix()
        return f"{prefix}{text}" if text != "." else (prefix.rstrip("/") or ".")
    return str(resolved)


def _short_id(run_id: Optional[str]) -> str:
    return (run_id or "")[:8]


# ── per-run state ───────────────────────────────────────────────────────────


@dataclass
class _Node:
    started: float = field(default_factory=time.monotonic)
    checks: int = 0
    warnings: int = 0
    failed_checks: List[str] = field(default_factory=list)
    done: bool = False
    failed: bool = False


@dataclass
class _Run:
    nodes: Dict[str, _Node] = field(default_factory=dict)
    name_width: int = 8
    output_width: int = 0


_run = _Run()


def reset_run(node_names: Iterable[str] = (), output_names: Iterable[str] = ()) -> None:
    """Start a run's view. The names set the columns, so that lines printed as
    each node ends — in whatever order — still line up."""
    global _run
    with _lock:
        names = [_display_name(n) for n in node_names]
        _run = _Run(
            name_width=max([8, *(len(n) for n in names)]),
            output_width=max([0, *(len(str(o)) for o in output_names)]),
        )


def _display_name(node: str) -> str:
    return node.split(".")[-1] if "." in node else node


def _node(node: str) -> _Node:
    name = _display_name(node)
    with _lock:
        return _run.nodes.setdefault(name, _Node())


def node_started(node: str) -> None:
    _node(node).started = time.monotonic()


def _checks_label(state: _Node) -> Tuple[str, str]:
    if not state.checks:
        return "", ""
    plural = "s" if state.checks != 1 else ""
    if state.failed_checks:
        return f"{len(state.failed_checks)} of {state.checks} checks failed", "red"
    if state.warnings:
        return f"{state.checks} check{plural} · {state.warnings} warning", "yellow"
    return f"{state.checks} check{plural} passed", "dim green"


def node_finished(
    node: str, duration: float, outputs: Sequence[Tuple[str, Optional[int]]] = ()
) -> None:
    """``  ✓ extract     508 rows → bronze.etl.raw_data   0.7s   2 checks passed``"""
    from rich.text import Text

    state = _node(node)
    state.done = True
    if is_quiet():
        return
    name = _display_name(node)
    width = _run.name_width
    lines: List[Any] = []
    first = Text("  ")
    first.append("✓ ", style="bold green")
    first.append(name.ljust(width), style="bold")
    rest = list(outputs)
    if rest:
        key, rows = rest.pop(0)
        first.append_text(_output_text(key, rows))
    first.append(f"   {duration:.1f}s", style="dim")
    label, style = _checks_label(state)
    if label:
        first.append(f"   {label}", style=style)
    lines.append(first)
    for key, rows in rest:
        more = Text("  " + " " * (width + 2))
        more.append_text(_output_text(key, rows))
        lines.append(more)
    with _lock:
        for line in lines:
            console().print(line, soft_wrap=True)


def _output_text(key: str, rows: Optional[int]) -> Any:
    from rich.text import Text

    text = Text("  ")
    text.append(f"{rows:>7,} rows" if rows is not None else " " * 12)
    text.append(" → ", style="dim")
    text.append(key.ljust(_run.output_width), style="cyan")
    return text


def node_failed(node: str, error: BaseException) -> None:
    """``  ✗ transform   failed after 0.4s`` — once, however many layers report it."""
    from rich.text import Text

    state = _node(node)
    with _lock:
        if state.failed:
            return
        state.failed = True
    if is_quiet():
        return
    elapsed = time.monotonic() - state.started
    line = Text("  ")
    line.append("✗ ", style="bold red")
    line.append(_display_name(node).ljust(_run.name_width), style="bold")
    line.append(f" failed after {elapsed:.1f}s", style="red")
    console().print(line, soft_wrap=True)


def nodes_seen() -> Tuple[List[str], List[str]]:
    """``(finished, failed)`` display names, in the order they happened."""
    with _lock:
        done = [n for n, s in _run.nodes.items() if s.done]
        failed = [n for n, s in _run.nodes.items() if s.failed]
    return done, failed


# ── quality ─────────────────────────────────────────────────────────────────


def quality_report(report: Any) -> None:
    """A node's checks: counted on its line; only failures and warnings are printed."""
    from rich.text import Text

    state = _node(str(getattr(report, "dataset_name", "") or "?"))
    results = list(getattr(report, "results", None) or [])
    state.checks += len(results)
    shown = []
    for r in results:
        if getattr(r, "passed", True):
            continue
        name = str(getattr(r, "check_name", "?"))
        is_error = bool(getattr(r, "is_error", True))
        if is_error:
            state.failed_checks.append(name)
        else:
            state.warnings += 1
        shown.append((name, str(getattr(r, "message", "")), is_error))
    if is_quiet():
        return
    for name, message, is_error in shown:
        line = Text("      ")
        line.append("✗ " if is_error else "! ", style="red" if is_error else "yellow")
        line.append(f"{_display_name(state_name(report))}: ", style="dim")
        line.append(name, style="bold")
        line.append(f"  {message}")
        console().print(line, soft_wrap=True)


def state_name(report: Any) -> str:
    return str(getattr(report, "dataset_name", "") or "?")


def quality_summary(reports: Sequence[Any]) -> None:
    """Preflight checks of every input: silent when all pass."""
    for report in reports:
        if not getattr(report, "passed", True):
            quality_report(report)


# ── a run: header, summary, failure ─────────────────────────────────────────


def print_header(
    pipeline: str,
    env: str,
    project: Optional[Path],
    *,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    node: Optional[str] = None,
) -> None:
    """``ducta 0.2.0 · etl · dev · p1``"""
    if is_quiet():
        return
    from rich.text import Text

    from ducta import __version__

    parts = [pipeline, env]
    if project is not None:
        parts.append(project.name)
    if start_date or end_date:
        parts.append(f"{start_date or '…'} → {end_date or '…'}")
    if node:
        parts.append(f"node {node}")
    line = Text()
    line.append(f"ducta {__version__}", style="bold cyan")
    for part in parts:
        line.append(" · ", style="dim")
        line.append(part)
    console().print(line, soft_wrap=True)
    console().print()


def print_run_summary(result: Any, elapsed: float) -> None:
    """The end of a run that returned: what it did, and where its evidence is."""
    from rich.text import Text

    nodes = list(getattr(result, "nodes", None) or [])
    ok_count = sum(1 for n in nodes if getattr(n, "ok", True))
    pipeline = getattr(result, "pipeline", "")
    gate = getattr(result, "gate_blocked", None) or {}
    skipped = getattr(result, "skipped", None) or {}
    out = console()
    if not is_quiet():
        out.print()
    line = Text()
    if gate or skipped:
        line.append("✗ ", style="bold red")
        cause = "a quality gate blocked it" if gate else "nodes were skipped"
        line.append(f"{pipeline} did not finish: {cause}", style="bold")
    else:
        line.append("✓ ", style="bold green")
        line.append(f"{pipeline} finished", style="bold")
        line.append(f" in {elapsed:.1f}s", style="dim")
        if nodes:
            line.append(f" · {ok_count}/{len(nodes)} nodes", style="dim")
    out.print(line, soft_wrap=True)
    rows: List[Tuple[str, str]] = []
    for node_name, info in gate.items():
        reason = info.get("error", "blocked") if isinstance(info, dict) else info
        rows.append(("blocked", f"{node_name} — {reason}"))
    for node_name, reason in skipped.items():
        if node_name not in gate:
            rows.append(("skipped", f"{node_name} — {reason}"))
    reused = getattr(result, "reused_pipelines", None) or []
    if reused:
        rows.append(("reused", ", ".join(reused)))
    cert = getattr(result, "certificate_path", None)
    if cert:
        rows.append(("certificate", display_path(cert)))
        run_id = getattr(result, "run_id", None)
        if run_id:
            rows.append(("inspect", f"ducta certify show --run-id {_short_id(run_id)}"))
    elif getattr(result, "certificate_error", None):
        rows.append(("certificate", f"not written: {result.certificate_error}"))
    if is_quiet():
        return
    _print_rows(rows)


def _print_rows(rows: Sequence[Tuple[str, str]], indent: int = 2) -> None:
    from rich.text import Text

    if not rows:
        return
    width = max(len(k) for k, _ in rows)
    for key, value in rows:
        line = Text(" " * indent)
        line.append(key.ljust(width), style="dim")
        line.append("  ")
        line.append(value)
        console().print(line, soft_wrap=True)


def _root_cause(error: BaseException) -> BaseException:
    """The exception that started it: down ``__cause__`` past Ducta's own wrappers."""
    from ducta.core.errors import DuctaError

    seen = set()
    current = error
    while id(current) not in seen:
        seen.add(id(current))
        nxt = current.__cause__
        if nxt is None:
            break
        current = nxt
        if not isinstance(current, DuctaError):
            break
    return current


def run_result_of(error: BaseException) -> Any:
    """The ``PipelineRunResult`` a failed run attached to its exception, if any."""
    seen = set()
    current: Optional[BaseException] = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        found = getattr(current, "run_result", None)
        if found is not None:
            return found
        current = current.__cause__ or current.__context__
    return None


def _user_frame(error: BaseException, project: Optional[Path]) -> Optional[traceback.FrameSummary]:
    """The deepest frame in the project's own code: where *its* line is."""
    import ducta

    package = Path(ducta.__file__).resolve().parent
    root = (project or Path.cwd()).resolve()
    best = None
    for frame in traceback.extract_tb(error.__traceback__):
        path = Path(frame.filename)
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if "site-packages" in resolved.parts or package in resolved.parents:
            continue
        try:
            resolved.relative_to(root)
        except ValueError:
            continue
        best = frame
    return best


def _first_line(text: str, limit: int = 160) -> str:
    line = next((ln.strip() for ln in str(text).splitlines() if ln.strip()), "")
    return line if len(line) <= limit else line[: limit - 1] + "…"


def describe_failure(error: BaseException, project: Optional[Path] = None) -> Dict[str, Any]:
    """What to say about *error*: its message, where in the user's code, a hint."""
    from ducta.console.ux.error_analyzer import classify_error

    cause = _root_cause(error)
    analysis = classify_error(str(cause), cause if isinstance(cause, Exception) else None)
    context = analysis.get("context") or {}
    message = analysis.get("message") or _first_line(str(cause))
    hint = None
    columns: List[str] = []
    if "wrong_column" in context:
        wrong = context["wrong_column"]
        columns = [c.strip() for c in context.get("available_columns", []) if c.strip()]
        close = difflib.get_close_matches(wrong, columns, n=1, cutoff=0.6)
        message = f"Column '{wrong}' does not exist"
        if close:
            hint = f"did you mean '{close[0]}'?"
    elif analysis.get("suggestions"):
        hint = str(analysis["suggestions"][0])
    frame = _user_frame(cause, project) or _user_frame(error, project)
    return {
        "message": message,
        "hint": hint,
        "columns": columns,
        "frame": frame,
        "cause": f"{type(cause).__name__}: {_first_line(str(cause))}",
        "cause_exc": cause,
    }


def print_run_failure(
    error: BaseException,
    *,
    pipeline: str,
    env: str,
    project: Optional[Path],
    all_nodes: Sequence[str] = (),
    log_file: Optional[str] = None,
) -> None:
    """One block for a failed run: what, where, and what to run next."""
    from rich.text import Text

    failed_nodes = list(getattr(error, "failed_nodes", None) or [])
    done, failed_seen = nodes_seen()
    node: Optional[str] = (
        _display_name(failed_nodes[0])
        if failed_nodes
        else (failed_seen[0] if failed_seen else None)
    )
    info = describe_failure(error, project)
    out = console()
    out.print()
    head = Text()
    head.append("✗ ", style="bold red")
    if node:
        head.append(f"{node} failed: ", style="bold")
    head.append(str(info["message"]), style="bold")
    if info["hint"]:
        head.append(f" — {info['hint']}", style="yellow")
    out.print(head, soft_wrap=True)

    frame = info["frame"]
    rows: List[Tuple[str, str]] = []
    if frame is not None:
        where = f"{display_path(frame.filename)}:{frame.lineno}"
        source = (frame.line or "").strip()
        rows.append(("at", f"{where}   {source}" if source else where))
    if info["columns"]:
        rows.append(("columns", ", ".join(info["columns"])))
    rows.append(("cause", str(info["cause"])))
    _print_rows(rows)

    shown = {*done, *failed_seen, *(_display_name(n) for n in failed_nodes)}
    not_run = [n for n in (_display_name(x) for x in all_nodes) if n not in shown]
    result = run_result_of(error)
    nxt: List[Tuple[str, str]] = []
    if not_run:
        nxt.append(("not run", ", ".join(not_run)))
    rerun = f"ducta start -e {env} -p {pipeline}"
    if node:
        rerun += f" -n {node}"
    nxt.append(("re-run", rerun))
    error_file = _write_error_file(info["cause_exc"], error, project)
    if error_file:
        nxt.append(("explain", f"ducta ai explain --error-file {display_path(error_file)}"))
    if log_file:
        nxt.append(("log", display_path(log_file)))
    run_id = getattr(result, "run_id", None)
    if run_id and getattr(result, "certificate_path", None):
        nxt.append(("run", f"ducta certify show --run-id {_short_id(run_id)}"))
    out.print()
    _print_rows(nxt)


def _write_error_file(
    cause: BaseException, error: BaseException, project: Optional[Path]
) -> Optional[Path]:
    """The full error, for `ducta ai explain` and for reading: logs/last-error.txt."""
    if project is None:
        return None
    try:
        target = project / "logs" / "last-error.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        text = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        target.write_text(text, encoding="utf-8")
        return target
    except OSError:
        return None


def print_error(message: str, hints: Sequence[Tuple[str, str]] = ()) -> None:
    """``✗ message`` and, under it, aligned ``label  value`` hints."""
    from rich.text import Text

    lines = str(message).rstrip().splitlines() or [""]
    head = Text()
    head.append("✗ ", style="bold red")
    head.append(lines[0], style="bold")
    console().print(head, soft_wrap=True)
    for extra in lines[1:]:
        console().print(Text("  " + extra.strip()), soft_wrap=True)
    _print_rows(hints)
