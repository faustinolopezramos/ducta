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

Where the agents keep their state: ``.ducta/ai/<agent>/`` in the project.

Records are JSON files written whole to a temporary file and swapped in, so a
reader (the server, a daemon, the CLI) never sees half of one.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_ID = re.compile(r"^[0-9A-Za-z-]{1,64}$")


def agent_dir(root: Path, agent: str) -> Path:
    return Path(root) / ".ducta" / "ai" / agent


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id() -> str:
    """Sortable by time, unique: ``20261015-143000-1a2b3c``."""
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]


def write_json(path: Path, data: Any) -> Path:
    """Write *data* to *path* atomically (a temporary file, then a swap)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), "utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    return path


def read_json(path: Path) -> Optional[Any]:
    """*path*'s JSON, or ``None`` when it is missing or unreadable."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


class RecordStore:
    """One JSON file per record, under ``.ducta/ai/<agent>/<kind>/``."""

    def __init__(self, root: Path, agent: str, kind: str):
        self.folder = agent_dir(root, agent) / kind

    def path(self, record_id: str) -> Path:
        if not _ID.match(record_id):
            raise ValueError(f"'{record_id}' is not a record id")
        return self.folder / f"{record_id}.json"

    def save(self, record_id: str, data: Dict[str, Any]) -> Path:
        return write_json(self.path(record_id), data)

    def load(self, record_id: str) -> Optional[Dict[str, Any]]:
        data = read_json(self.path(record_id))
        return data if isinstance(data, dict) else None

    def list(self, limit: Optional[int] = 200) -> List[Dict[str, Any]]:
        """The newest *limit* records first (ids sort by time); all of them for ``None``."""
        if not self.folder.is_dir():
            return []
        out: List[Dict[str, Any]] = []
        for path in sorted(self.folder.glob("*.json"), reverse=True)[:limit]:
            data = read_json(path)
            if isinstance(data, dict):
                out.append(data)
        return out
