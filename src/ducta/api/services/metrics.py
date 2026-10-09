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

How a project's pipelines and nodes have been doing: runs, success rate,
duration (p50/p95, and the recent trend), and whether each pipeline is as
fresh as its ``metadata.sla`` asks. Read from the run certificates — durable
evidence that survives restarts, unlike an in-memory execution list.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any, Dict, Iterable, List, Optional, Tuple

_TREND = 20


def _ts(value: Any) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _p95(values: List[float]) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))]


def sla_deadline(sla: str, now: datetime) -> Optional[datetime]:
    """The time by which the last success must be — `daily 06:00`, `hourly`, `6h`…"""
    text = (sla or "").strip().lower()
    m = re.fullmatch(r"(\d+)([smhd])", text)
    if m:
        unit = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}[m[2]]
        return now - timedelta(**{unit: int(m[1])})
    m = re.fullmatch(r"(hourly|daily|weekly|monthly)(?: (\d{1,2}):(\d{2}))?", text)
    if not m:
        return None
    period = {
        "hourly": timedelta(hours=1),
        "daily": timedelta(days=1),
        "weekly": timedelta(weeks=1),
        "monthly": timedelta(days=31),
    }[m[1]]
    if m[1] != "daily" or m[2] is None:
        return now - period  # a time of day only means something daily
    # "daily 06:00": a success is due after the most recent 06:00 (UTC) that has passed.
    due = now.replace(hour=int(m[2]), minute=int(m[3]), second=0, microsecond=0)
    return due if due <= now else due - timedelta(days=1)


def freshness(last_success: Optional[datetime], sla: Optional[str], now: datetime) -> str:
    if not sla:
        return "no_sla"
    deadline = sla_deadline(sla, now)
    if deadline is None:
        return "unknown"
    if last_success is None:
        return "late"
    return "ok" if last_success >= deadline else "late"


def project_metrics(
    certificates: Iterable[Dict[str, Any]],
    slas: Dict[str, Optional[str]],
    days: int = 30,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """``{"pipelines": [...], "nodes": [...]}`` over the last *days* days."""
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    runs: Dict[str, List[Tuple[datetime, Dict[str, Any]]]] = {}
    last_ok: Dict[str, datetime] = {}
    for cert in certificates:
        at = _ts(cert.get("started_at"))
        pipeline = str(cert.get("pipeline") or "")
        if not at or not pipeline:
            continue
        if cert.get("status") == "success" and (pipeline not in last_ok or at > last_ok[pipeline]):
            last_ok[pipeline] = at
        if at >= since:
            runs.setdefault(pipeline, []).append((at, cert))

    pipelines = []
    nodes: Dict[str, Dict[str, Any]] = {}
    for pipeline in sorted(set(runs) | set(slas)):
        history = sorted(runs.get(pipeline, []), key=lambda r: r[0])
        durations = [float(c.get("duration_seconds") or 0) for _a, c in history]
        ok = sum(1 for _a, c in history if c.get("status") == "success")
        pipelines.append(
            {
                "pipeline": pipeline,
                "runs": len(history),
                "success_rate": round(ok / len(history), 3) if history else None,
                "p50_seconds": round(median(durations), 3) if durations else None,
                "p95_seconds": round(_p95(durations), 3) if durations else None,
                "last_status": history[-1][1].get("status") if history else None,
                "last_run_at": history[-1][0].isoformat() if history else None,
                "last_success_at": last_ok[pipeline].isoformat() if pipeline in last_ok else None,
                "sla": slas.get(pipeline),
                "freshness": freshness(last_ok.get(pipeline), slas.get(pipeline), now),
                "trend": [
                    {
                        "at": a.isoformat(),
                        "status": c.get("status"),
                        "seconds": c.get("duration_seconds"),
                    }
                    for a, c in history[-_TREND:]
                ],
            }
        )
        for at, cert in history:
            for node in cert.get("nodes") or []:
                entry = nodes.setdefault(
                    str(node.get("name")),
                    {
                        "node": node.get("name"),
                        "pipeline": pipeline,
                        "durations": [],
                        "failures": 0,
                        "trend": [],
                    },
                )
                entry["durations"].append(float(node.get("duration_seconds") or 0))
                if node.get("status") not in ("success", "completed", "skipped", "reused"):
                    entry["failures"] += 1
                entry["trend"].append(
                    {
                        "at": at.isoformat(),
                        "status": node.get("status"),
                        "seconds": node.get("duration_seconds"),
                    }
                )
    node_rows = []
    for entry in nodes.values():
        d = entry.pop("durations")
        node_rows.append(
            {
                **entry,
                "runs": len(d),
                "p50_seconds": round(median(d), 3) if d else None,
                "p95_seconds": round(_p95(d), 3) if d else None,
                "trend": entry["trend"][-_TREND:],
            }
        )
    return {
        "days": days,
        "pipelines": pipelines,
        "nodes": sorted(node_rows, key=lambda n: str(n["node"])),
    }
