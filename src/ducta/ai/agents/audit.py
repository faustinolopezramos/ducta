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

What an agent did, one JSON line per action: who, what, on what, why, and
how it went. Append-only; Sentinel also counts its daily budget from it.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

from ducta.ai.agents.store import agent_dir, now


def audit_path(root: Path, agent: str) -> Path:
    return agent_dir(root, agent) / "audit.jsonl"


def record(
    root: Path,
    agent: str,
    action: str,
    *,
    target: Dict[str, Any],
    result: str,
    reason: str = "",
    actor: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    """Append one action to the agent's audit log, and return it."""
    entry = {
        "at": now(),
        "actor": actor or agent,
        "action": action,
        "target": target,
        "result": result,
        "reason": reason,
        **extra,
    }
    path = audit_path(root, agent)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    return entry


def entries(root: Path, agent: str) -> Iterator[Dict[str, Any]]:
    """Every entry, oldest first; a damaged line is skipped."""
    path = audit_path(root, agent)
    if not path.is_file():
        return
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if isinstance(entry, dict):
                yield entry


def _newest_first(path: Path, block: int = 64 * 1024) -> Iterator[Dict[str, Any]]:
    """The entries of *path*, last line first, reading the file backwards in blocks.

    The log only grows and is in time order, so the last day's entries are at its
    end: counting them never reads the months before.
    """
    with path.open("rb") as f:
        f.seek(0, 2)
        pos = f.tell()
        tail = b""
        while pos > 0:
            step = min(block, pos)
            pos -= step
            f.seek(pos)
            tail = f.read(step) + tail
            lines = tail.split(b"\n")
            # The first piece may be the end of a line that starts in the block before.
            tail, complete = (lines[0], lines[1:]) if pos > 0 else (b"", lines)
            for raw in reversed(complete):
                try:
                    entry = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(entry, dict):
                    yield entry


def count_since(root: Path, agent: str, hours: float, **match: Any) -> int:
    """Entries of the last *hours* whose keys equal *match* (``action="rerun"``)."""
    path = audit_path(root, agent)
    if not path.is_file():
        return 0
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    total = 0
    for entry in _newest_first(path):
        try:
            at = datetime.fromisoformat(str(entry.get("at")))
        except ValueError:
            continue
        if at < since:
            break  # everything before it is older still
        if all(entry.get(k) == v for k, v in match.items()):
            total += 1
    return total
