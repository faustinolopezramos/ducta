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

What a draft is, and where drafts are kept: ``<project>/.ducta/ai/drafts/<id>.json``.

Every kind of draft (``new``, ``fix``, ``extend``, ``quality``, ``docs``,
``blueprint``, ``architect``) is a :class:`Draft`; :mod:`ducta.ai.builder`
applies them.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ducta.ai.errors import AIConfigError, AIConflictError, AINotFoundError


def text_sha(text: Optional[str]) -> Optional[str]:
    return None if text is None else hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_text(path: Path) -> Optional[str]:
    return path.read_text(encoding="utf-8") if path.is_file() else None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def add_usage(*usages: Dict[str, int]) -> Dict[str, int]:
    """Token counts added up, key by key (``input_tokens``, ``output_tokens``, cache reads…)."""
    out: Dict[str, int] = {}
    for usage in usages:
        for key, value in (usage or {}).items():
            if isinstance(value, (int, float)):
                out[key] = out.get(key, 0) + int(value)
    return out


def usage_line(usage: Dict[str, int]) -> str:
    """Token counts in words: ``12,345 tokens in (8,000 cached) · 2,345 out``; ``""`` if none."""
    tokens_in = usage.get("input_tokens", 0)
    cached = usage.get("cache_read_input_tokens", 0)
    tokens_out = usage.get("output_tokens", 0)
    if not (tokens_in or cached or tokens_out):
        return ""
    # Anthropic counts cache reads apart from input_tokens; OpenAI-compatible APIs do not.
    total_in = tokens_in + cached + usage.get("cache_creation_input_tokens", 0)
    cache = f" ({cached:,} cached)" if cached else ""
    return f"{total_in:,} tokens in{cache} · {tokens_out:,} out"


# ── drafts ──────────────────────────────────────────────────────────────────


@dataclass
class Attempt:
    number: int
    files: List[str]
    #: Errors the draft is responsible for (see :func:`judge_problems`).
    errors: int
    warnings: int
    rejected: List[str]
    usage: Dict[str, int]
    #: The first few problems, as sent back to the model: what the attempt got wrong.
    messages: List[str] = field(default_factory=list)


@dataclass
class Draft:
    id: str
    request: str
    provider: str
    model: str
    created_at: str
    ok: bool
    files: Dict[str, str]
    #: SHA-256 of each file as it was when the draft was made (``None``: did not exist).
    base: Dict[str, Optional[str]]
    #: Every problem of the project with the draft applied, plus rejections.
    problems: List[Dict[str, Any]]
    notes: str = ""
    new_datasets: List[str] = field(default_factory=list)
    attempts: List[Attempt] = field(default_factory=list)
    #: The model's last answer as it came, for when the draft is not what was expected.
    raw_answer: str = ""
    #: ``new``, ``fix``, ``quality`` (a node's checks) or ``docs`` (descriptions).
    kind: str = "new"
    #: The pipeline fixed, for a fix; the node's pipeline, for ``quality``.
    pipeline: Optional[str] = None
    #: The node a ``quality`` draft is about.
    target: Optional[str] = None
    #: The environment a proposal measured its data in.
    env: Optional[str] = None
    #: What Ducta checked the draft against, in words ("Proven on 2,431 rows of dev").
    evidence: str = ""
    #: Problems the draft introduces (or, for a fix, leaves on its pipeline).
    blocking: List[Dict[str, Any]] = field(default_factory=list)
    applied_at: Optional[str] = None
    #: The draft this one revises ("Ask for changes"), if any.
    revision_of: Optional[str] = None
    #: The first message the model was sent, so a revision continues the same conversation.
    prompt: str = ""
    #: SHA-256 of each file the prompt showed in full (a fix's editable files):
    #: a revision re-sends that prompt, so it refuses if one changed since.
    seen: Dict[str, Optional[str]] = field(default_factory=dict)
    #: Which version of the system prompt made it (:func:`ducta.ai.loop.prompt_version`).
    prompt_version: str = ""

    @property
    def usage(self) -> Dict[str, int]:
        """The tokens every attempt took, added up."""
        return add_usage(*(a.usage for a in self.attempts))

    @property
    def errors(self) -> List[Dict[str, Any]]:
        return [p for p in self.problems if p.get("severity") == "error"]

    def diff(self, root: Path) -> str:
        chunks: List[str] = []
        for rel, text in self.files.items():
            before = read_text(root / rel) or ""
            chunks.extend(
                difflib.unified_diff(
                    before.splitlines(keepends=True),
                    text.splitlines(keepends=True),
                    fromfile=f"a/{rel}" if before else "/dev/null",
                    tofile=f"b/{rel}",
                )
            )
        return "".join(chunks)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Draft":
        data = dict(data)
        # A draft written by another Ducta version may carry fields this one lacks.
        fields = set(Attempt.__dataclass_fields__)
        data["attempts"] = [
            Attempt(**{k: v for k, v in a.items() if k in fields})
            for a in data.get("attempts") or []
        ]
        known = set(cls.__dataclass_fields__)
        draft = cls(**{k: v for k, v in data.items() if k in known})
        # The id names files (the draft's own, an apply's temporary ones): a draft
        # file anyone could edit does not get to pick a path with it.
        if not DRAFT_ID.match(str(draft.id)):
            raise ValueError(f"'{draft.id}' is not a draft id")
        return draft


DRAFT_ID = re.compile(r"^[0-9A-Za-z-]{1,64}\Z")


def drafts_dir(root: Path) -> Path:
    return Path(root) / ".ducta" / "ai" / "drafts"


def save_draft(root: Path, draft: Draft) -> Path:
    from ducta.ai.fsutil import atomic_write_text

    path = drafts_dir(root) / f"{draft.id}.json"
    return atomic_write_text(path, json.dumps(draft.to_dict(), indent=2, ensure_ascii=False))


def list_drafts(root: Path, limit: int = 50) -> List[Draft]:
    """The project's drafts, newest first."""
    folder = drafts_dir(root)
    if not folder.is_dir():
        return []
    out = []
    for path in sorted(folder.glob("*.json"), reverse=True)[:limit]:
        try:
            out.append(Draft.from_dict(json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, ValueError, TypeError):
            continue
    return out


def load_draft(root: Path, draft_id: str) -> Draft:
    if not DRAFT_ID.match(draft_id):
        raise AIConfigError(f"'{draft_id}' is not a draft id")
    folder = drafts_dir(root)
    matches = sorted(folder.glob(f"{draft_id}*.json")) if folder.is_dir() else []
    if not matches:
        raise AINotFoundError(f"No draft '{draft_id}' in {folder}")
    if len(matches) > 1:
        raise AIConfigError(f"'{draft_id}' matches {len(matches)} drafts; give more of the id")
    try:
        return Draft.from_dict(json.loads(matches[0].read_text(encoding="utf-8")))
    except (ValueError, TypeError, AttributeError) as e:
        raise AIConflictError(f"{matches[0].name} is not a readable draft ({e})") from e


def delete_draft(root: Path, draft_id: str) -> None:
    draft = load_draft(root, draft_id)
    (drafts_dir(root) / f"{draft.id}.json").unlink()
