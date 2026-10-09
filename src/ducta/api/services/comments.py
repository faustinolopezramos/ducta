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

Comments on a project's nodes and code lines. ``CommentStore`` is the seam:
locally each thread is one JSON file under ``.ducta/comments/`` — versioned
with the project, and one file per thread so two people commenting never
conflict in git. A server deployment can keep them in its database instead.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

COMMENTS_DIR = Path(".ducta") / "comments"
_ID = re.compile(r"^[0-9a-f]{32}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Reply:
    id: str
    author: str
    body: str
    created_at: str


@dataclass
class Thread:
    id: str
    #: What it is about: {"pipeline", "node"} or {"file", "line"}.
    anchor: Dict[str, Any]
    author: str
    body: str
    created_at: str
    resolved: bool = False
    resolved_by: Optional[str] = None
    replies: List[Reply] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Thread":
        replies = [Reply(**r) for r in data.get("replies") or []]
        return cls(**{**data, "replies": replies})


class CommentNotFound(KeyError):
    pass


class CommentStore(Protocol):
    def list(self, **anchor: Any) -> List[Thread]: ...
    def add(self, anchor: Dict[str, Any], author: str, body: str) -> Thread: ...
    def reply(self, thread_id: str, author: str, body: str) -> Thread: ...
    def resolve(self, thread_id: str, by: str, resolved: bool = True) -> Thread: ...
    def delete(self, thread_id: str) -> None: ...


def clean_anchor(anchor: Dict[str, Any]) -> Dict[str, Any]:
    """A node (``pipeline`` + ``node``) or a line of a file (``file`` + ``line``)."""
    if anchor.get("node"):
        out = {"node": str(anchor["node"])}
        if anchor.get("pipeline"):
            out["pipeline"] = str(anchor["pipeline"])
        return out
    file = str(anchor.get("file") or "").strip().lstrip("/")
    if file and ".." not in Path(file).parts:
        out = {"file": file}
        if anchor.get("line") is not None:
            out["line"] = int(anchor["line"])
        return out
    raise ValueError("A comment is about a node (node) or a file line (file, line)")


class LocalCommentStore:
    """Threads as ``.ducta/comments/<id>.json`` in the project."""

    def __init__(self, project_root: Path) -> None:
        self.dir = Path(project_root) / COMMENTS_DIR

    def _path(self, thread_id: str) -> Path:
        if not _ID.match(thread_id):
            raise CommentNotFound(thread_id)
        return self.dir / f"{thread_id}.json"

    def _read(self, thread_id: str) -> Thread:
        path = self._path(thread_id)
        if not path.is_file():
            raise CommentNotFound(thread_id)
        return Thread.from_dict(json.loads(path.read_text("utf-8")))

    def _write(self, thread: Thread) -> Thread:
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self._path(thread.id)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(thread.to_dict(), indent=2, ensure_ascii=False) + "\n", "utf-8")
        tmp.replace(path)
        return thread

    def list(self, **anchor: Any) -> List[Thread]:
        if not self.dir.is_dir():
            return []
        out = []
        for path in self.dir.glob("*.json"):
            try:
                thread = Thread.from_dict(json.loads(path.read_text("utf-8")))
            except (ValueError, TypeError):
                continue  # a hand-edited file that no longer parses is skipped, not fatal
            if all(thread.anchor.get(k) == v for k, v in anchor.items() if v is not None):
                out.append(thread)
        return sorted(out, key=lambda t: t.created_at)

    def add(self, anchor: Dict[str, Any], author: str, body: str) -> Thread:
        body = body.strip()
        if not body:
            raise ValueError("A comment needs text")
        thread = Thread(
            id=uuid.uuid4().hex,
            anchor=clean_anchor(anchor),
            author=author,
            body=body,
            created_at=_now(),
        )
        return self._write(thread)

    def reply(self, thread_id: str, author: str, body: str) -> Thread:
        if not body.strip():
            raise ValueError("A reply needs text")
        thread = self._read(thread_id)
        thread.replies.append(
            Reply(id=uuid.uuid4().hex, author=author, body=body.strip(), created_at=_now())
        )
        return self._write(thread)

    def resolve(self, thread_id: str, by: str, resolved: bool = True) -> Thread:
        thread = self._read(thread_id)
        thread.resolved = resolved
        thread.resolved_by = by if resolved else None
        return self._write(thread)

    def delete(self, thread_id: str) -> None:
        path = self._path(thread_id)
        if not path.is_file():
            raise CommentNotFound(thread_id)
        path.unlink()

    def get(self, thread_id: str) -> Thread:
        return self._read(thread_id)
