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

Incidents: one per pipeline, environment and kind of trouble, while it lasts.

A failure that repeats is a new line in the open incident's timeline, not a
new incident; the next successful run of the pipeline resolves it.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ducta.ai.agents.store import RecordStore, new_id, now, read_json

KINDS = ("failure", "sla_miss", "slow", "stale")
#: open: seen, nothing decided yet · remediating: Sentinel has an action
#: pending · escalated: a person must act · resolved · ignored (by a person).
STATUSES = ("open", "remediating", "escalated", "resolved", "ignored")
ACTIVE = ("open", "remediating", "escalated")
#: A closed incident (resolved, ignored) this many days old moves to ``archive/``:
#: every run and pass reads the incidents folder whole, and it only grew.
ARCHIVE_AFTER_DAYS = 90


@dataclass
class Incident:
    id: str
    env: str
    pipeline: str
    kind: str
    status: str = "open"
    opened_at: str = ""
    updated_at: str = ""
    resolved_at: Optional[str] = None
    #: Ducta's diagnosis of the latest failure (see api/services/diagnosis.py).
    diagnosis: Dict[str, Any] = field(default_factory=dict)
    #: The runbook chosen for it, the level (L0 observe, L1 act, L2 propose), and why.
    runbook: str = ""
    level: str = "L0"
    reason: str = ""
    #: Runs that failed under this incident, and re-runs Sentinel made.
    failures: int = 0
    attempts: int = 0
    #: The nodes that failed under this incident: a run resolves it only if it ran them all.
    nodes: List[str] = field(default_factory=list)
    last_run_id: Optional[str] = None
    #: An action waiting for its time: {"action", "at", "nodes", "until", "upstream"}.
    pending: Optional[Dict[str, Any]] = None
    #: What was proposed: {"explanation": run_id, "draft": draft_id}.
    links: Dict[str, Any] = field(default_factory=dict)
    timeline: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def active(self) -> bool:
        return self.status in ACTIVE

    def note(self, actor: str, action: str, detail: str = "", **extra: Any) -> None:
        entry = {"at": now(), "actor": actor, "action": action, "detail": detail, **extra}
        self.timeline.append({k: v for k, v in entry.items() if v not in (None, "")})
        self.updated_at = entry["at"]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Incident":
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items() if k in known})


def _parse(value: Optional[str]) -> Optional[datetime]:
    try:
        found = datetime.fromisoformat(str(value)) if value else None
    except ValueError:
        return None
    if found is not None and found.tzinfo is None:
        found = found.replace(tzinfo=timezone.utc)
    return found


class Incidents:
    """The project's incidents, on disk under ``.ducta/ai/sentinel/incidents/``."""

    def __init__(self, root: Path):
        self.store = RecordStore(root, "sentinel", "incidents")

    def save(self, incident: Incident) -> Incident:
        self.store.save(incident.id, incident.to_dict())
        return incident

    def get(self, incident_id: str) -> Optional[Incident]:
        try:
            data = self.store.load(incident_id) or read_json(
                self.archive_dir / self.store.path(incident_id).name
            )
        except ValueError:
            return None
        return Incident.from_dict(data) if isinstance(data, dict) else None

    @property
    def archive_dir(self) -> Path:
        return self.store.folder / "archive"

    def archive_closed(self, older_than_days: int = ARCHIVE_AFTER_DAYS) -> List[str]:
        """Move closed incidents last changed more than *older_than_days* ago to ``archive/``.

        They stay readable by id (:meth:`get`); lists of incidents no longer read them.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
        moved: List[str] = []
        for data in self.store.list(limit=None):
            incident = Incident.from_dict(data)
            if incident.active:
                continue
            at = _parse(incident.resolved_at or incident.updated_at)
            if at is None or at >= cutoff:
                continue
            source = self.store.path(incident.id)
            self.archive_dir.mkdir(parents=True, exist_ok=True)
            os.replace(source, self.archive_dir / source.name)
            moved.append(incident.id)
        return moved

    def list(self, *, status: Optional[str] = None, env: Optional[str] = None) -> List[Incident]:
        out = [Incident.from_dict(d) for d in self.store.list(limit=None)]
        if status == "active":
            out = [i for i in out if i.active]
        elif status:
            out = [i for i in out if i.status == status]
        if env:
            out = [i for i in out if i.env == env]
        return out

    def active(self, env: str, pipeline: str, kind: Optional[str] = None) -> List[Incident]:
        return [
            i
            for i in self.list(status="active", env=env)
            if i.pipeline == pipeline and (kind is None or i.kind == kind)
        ]

    def open(self, env: str, pipeline: str, kind: str) -> Tuple[Incident, bool]:
        """The active incident for this trouble, or a new one; and whether it is new."""
        found = self.active(env, pipeline, kind)
        if found:
            return found[0], False
        at = now()
        return Incident(
            id=new_id(), env=env, pipeline=pipeline, kind=kind, opened_at=at, updated_at=at
        ), True
