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

# What `ducta stream run` and `ducta stream plan` print about a stream, as text.
#
# Additive to the log, never a replacement for it: a summary once at start, then a
# table appended every so often (and the moment something changes). Appended rather
# than redrawn in place because Ducta's own log lines share the terminal; a redraw
# would overwrite them.

from __future__ import annotations

import os
import re
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from ducta.stream.node_state import NodeState, derive_node_state, node_names
from ducta.stream.plan import ERROR, PipelinePlan

#: Seconds between the tables a running stream appends (unless something changes).
DEFAULT_REPORT_SECONDS = 30.0
REPORT_SECONDS_ENV = "DUCTA_STREAM_REPORT_SECONDS"
#: How long the first table waits for a node to report before printing anyway.
FIRST_REPORT_WAIT_SECONDS = 15.0


def _utf8() -> bool:
    encoding = getattr(sys.stdout, "encoding", None) or ""
    return encoding.lower().replace("-", "") in ("utf8", "utf")


def _glyph(unicode_text: str, ascii_text: str) -> str:
    return unicode_text if _utf8() else ascii_text


def format_rate(value: Optional[float]) -> str:
    """``1.2k/s``, ``140/s``, ``0.54/s``, ``-``."""
    if value is None:
        return "-"
    if value >= 1000:
        return f"{value / 1000:.1f}k/s"
    if value >= 10:
        return f"{round(value)}/s"
    return f"{value:.2f}/s"


def format_duration(seconds: Optional[float]) -> str:
    """``45s``, ``3m``, ``1h 5m`` - coarse on purpose."""
    if seconds is None:
        return "-"
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    return f"{s // 3600}h {(s % 3600) // 60}m"


def format_uptime(seconds: Optional[float]) -> str:
    """``00:42``, ``1:05:09``."""
    if seconds is None:
        return "-"
    s = int(seconds)
    hours, rest = divmod(s, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def _table(headers: List[str], rows: List[List[str]], right: Tuple[int, ...] = ()) -> List[str]:
    widths = [
        max(len(h), *(len(r[i]) for r in rows)) if rows else len(h) for i, h in enumerate(headers)
    ]

    def line(cells: List[str]) -> str:
        parts = [
            c.rjust(widths[i]) if i in right else c.ljust(widths[i]) for i, c in enumerate(cells)
        ]
        return "  " + "  ".join(parts).rstrip()

    return [line(headers)] + [line(r) for r in rows]


# ── a running stream ─────────────────────────────────────────────────────────


_UNITS = ((r"milliseconds?", "ms"), (r"seconds?", "s"), (r"minutes?", "min"), (r"hours?", "h"))


def short_trigger(text: str) -> str:
    """``every 5 seconds`` -> ``every 5 s``; ``available_now`` stays as it is."""
    for pattern, unit in _UNITS:
        text = re.sub(rf"(\d+(?:\.\d+)?) {pattern}\b", rf"\1 {unit}", text)
    return text


def _running_text(active: int, total: int) -> str:
    """``2 nodes running`` when all are, ``1 of 4 nodes running`` when not."""
    noun = "node" if total == 1 else "nodes"
    if active == total:
        return f"{total} {noun} running"
    return f"{active} of {total} {noun} running"


def _failure_text(states: List[NodeState]) -> str:
    """``1 of 4 nodes failed``, ``1 of 4 nodes failed, 1 skipped``."""
    total = len(states)
    failed = sum(1 for s in states if s.state == "failed")
    skipped = sum(1 for s in states if s.state == "skipped")
    noun = "node" if total == 1 else "nodes"
    if failed and skipped:
        return f"{failed} of {total} {noun} failed, {skipped} skipped"
    if failed:
        return f"{failed} of {total} {noun} failed"
    if skipped:
        return f"{skipped} of {total} {noun} skipped"
    return "partial failure"


def render_start_summary(snapshot: Dict[str, Any], pipeline: str, env: str) -> str:
    """What the stream just started: one header, then a line per node.

    The checkpoint is not here (it is in the log line of each query, in ``-v`` and in
    ``ducta stream plan``): it does not change while the stream runs.
    """
    arrow = _glyph("→", "->")
    dot = _glyph("·", "-")
    summaries = snapshot.get("node_summaries") or {}
    total = int(snapshot.get("total_queries") or 0)
    active = int(snapshot.get("active_queries") or 0)
    execution = str(snapshot.get("execution_id") or "")[:8]
    lines = [
        f"{pipeline} {dot} {env} {dot} {_running_text(active, total)} {dot} "
        f"execution {execution} {dot} Ctrl+C to stop"
    ]
    names = node_names(snapshot)
    width = max((len(n) for n in names), default=0)
    for node in names:
        info = summaries.get(node) or {}
        if not info:
            lines.append(f"  {node}")
            continue
        trigger = short_trigger(str(info.get("trigger") or ""))
        lines.append(
            f"  {node:<{width}}  {info.get('source', '?')} {arrow} {info.get('sink', '?')}   {trigger}".rstrip()
        )
    return "\n".join(lines)


def _state_cell(state: NodeState) -> str:
    if state.state == "active" and state.health == "stalled":
        return "stalled"
    if state.state == "active" and state.health == "idle":
        return f"active, idle {format_duration(state.idle_seconds)}"
    return state.state


def _rate_cell(state: NodeState) -> str:
    """Rows per second processed; the input rate too, only when the node falls behind it."""
    processed, incoming = state.processed_rows_per_second, state.input_rows_per_second
    text = format_rate(processed)
    if (
        processed is not None
        and incoming is not None
        and incoming >= 5
        and incoming > processed * 1.2
    ):
        text += f" (in {format_rate(incoming)})"
    return text


def _table_header(snapshot: Dict[str, Any], states: List[NodeState]) -> str:
    dot = _glyph("·", "-")
    status = str(snapshot.get("status") or "unknown")
    if status == "running":
        label, mark = "running", _glyph("●", "*")
    elif status == "partial_failure":
        label, mark = _failure_text(states), "!"
    else:
        label, mark = status.replace("_", " "), "!"
    return f"{mark} {label} {dot} up {format_uptime(snapshot.get('uptime_seconds'))}"


def render_live_table(snapshot: Dict[str, Any]) -> str:
    """The running table: one row per node, plus a line per node that needs attention."""
    states = [derive_node_state(node, snapshot) for node in node_names(snapshot)]
    rows = [
        [
            s.node,
            _state_cell(s),
            _rate_cell(s),
            "-" if s.last_batch_id is None else str(s.last_batch_id),
        ]
        for s in states
    ]
    lines = [_table_header(snapshot, states)]
    lines += _table(["NODE", "STATE", "ROWS/s", "BATCH"], rows, right=(2, 3))
    for s in states:
        if s.state in ("failed", "skipped") and s.error:
            lines.append(f"  ! {s.node}: {s.error}")
        elif s.health == "stalled":
            lines.append(f"  ! {s.node}: no progress report for a long time - it may be hung")
        elif s.health == "idle":
            lines.append(
                f"  {s.node}: no new input for {format_duration(s.idle_seconds)} "
                "(a quiet source, not a failure)"
            )
    return "\n".join(lines)


def render_final_summary(snapshot: Dict[str, Any]) -> str:
    """How the run ended and what each node processed in total.

    Printed once, after the stream stops (Ctrl+C) or ends on its own (a terminating
    trigger): the figures the live table only ever showed as rates.
    """
    names = node_names(snapshot)
    if not names:
        return ""
    dot = _glyph("·", "-")
    status = str(snapshot.get("status") or "unknown")
    states = [derive_node_state(node, snapshot) for node in names]
    if status == "partial_failure":
        ended = _failure_text(states)
    else:
        ended = status.replace("_", " ")
    verb = {"stopped": "Stopped", "completed": "Finished"}.get(status, f"Ended: {ended}")
    totals = snapshot.get("totals") or {}
    rows = []
    for node in names:
        t = totals.get(node) or {}
        rows.append(
            [
                node,
                f"{int(t['batches']):,}" if "batches" in t else "-",
                f"{int(t['rows']):,}" if "rows" in t else "-",
                derive_node_state(node, snapshot).state,
            ]
        )
    lines = [f"{verb} {dot} ran {format_uptime(snapshot.get('uptime_seconds'))}"]
    lines += _table(["NODE", "BATCHES", "ROWS IN", "ENDED"], rows, right=(1, 2))
    return "\n".join(lines)


def report_interval() -> float:
    raw = os.environ.get(REPORT_SECONDS_ENV)
    try:
        value = float(raw) if raw else DEFAULT_REPORT_SECONDS
    except ValueError:
        return DEFAULT_REPORT_SECONDS
    return value if value > 0 else DEFAULT_REPORT_SECONDS


class LiveReporter:
    """Decides when the running table is worth printing again.

    Once on the first look, then every ``interval`` seconds, and at once when a
    node changes state (starts failing, stalls, goes idle, recovers).
    """

    def __init__(
        self, interval: Optional[float] = None, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.interval = report_interval() if interval is None else interval
        self._clock = clock
        self._last_printed: Optional[float] = None
        self._first_seen: Optional[float] = None
        self._signature: Optional[Tuple] = None

    @staticmethod
    def _signature_of(snapshot: Dict[str, Any]) -> Tuple:
        return (
            snapshot.get("status"),
            tuple(
                (s.node, s.state, s.health, s.error)
                for s in (derive_node_state(n, snapshot) for n in node_names(snapshot))
            ),
        )

    def tick(self, snapshot: Dict[str, Any]) -> Optional[str]:
        """The table to print now, or None."""
        now = self._clock()
        if self._first_seen is None:
            self._first_seen = now
        signature = self._signature_of(snapshot)
        due = self._last_printed is None or now - self._last_printed >= self.interval
        changed = self._signature is not None and signature != self._signature
        self._signature = signature
        # Right after the start no node has reported yet, and a table of dashes says
        # nothing: wait for the first report (or a few seconds, or a change).
        waiting = (
            not changed
            and now - self._first_seen < FIRST_REPORT_WAIT_SECONDS
            and not any(
                derive_node_state(n, snapshot).last_batch_id is not None
                for n in node_names(snapshot)
            )
        )
        if waiting or not (due or changed):
            return None
        self._last_printed = now
        return render_live_table(snapshot)


# ── the plan ─────────────────────────────────────────────────────────────────


def render_plan(plan: PipelinePlan) -> str:
    """``ducta stream plan``: what would run, and what would get in its way."""
    dot = _glyph("·", "-")
    lines = [
        f"Plan {dot} {plan.pipeline} {dot} env {plan.env or '-'} {dot} nothing was started",
        "",
    ]
    for node in plan.nodes:
        after = f"  (after {', '.join(node.after)})" if node.after else ""
        lines.append(f"  {node.name}{after}")
        lines.append(f"    reads       {node.source}")
        lines.append(f"    writes      {node.sink}")
        if node.transform:
            lines.append(f"    transform   {node.transform}")
        lines.append(f"    fires       {node.trigger} {dot} {node.output_mode}")
        lines.append(f"    checkpoint  {node.checkpoint or '-'}")
        for issue in node.issues:
            marker = "x" if issue.level == ERROR else "!"
            lines.append(f"    {marker} {issue.text}")
        lines.append("")
    for issue in plan.issues:
        lines.append(f"  {'x' if issue.level == ERROR else '!'} {issue.text}")
    errors, warnings = plan.errors, plan.warnings
    count = len(plan.nodes)
    noun = "node" if count == 1 else "nodes"
    if errors:
        lines.append(
            f"{len(errors)} error{'s' if len(errors) != 1 else ''}, "
            f"{len(warnings)} warning{'s' if len(warnings) != 1 else ''}: "
            "fix the errors before starting."
        )
    elif warnings:
        lines.append(
            f"Ready: {count} {noun}, {len(warnings)} warning{'s' if len(warnings) != 1 else ''}."
        )
    else:
        lines.append(f"Ready: {count} {noun}, no problems found.")
    return "\n".join(lines)
