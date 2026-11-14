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

The generate → validate → repair loop every drafting feature shares.

* :func:`parse_answer` reads the model's fenced file blocks.
* :class:`Scope` says what a draft may touch; an *assembler* turns an answer
  into files and rejections (each feature brings its own).
* :func:`validate_files` runs Ducta's validator on a scratch copy and
  :func:`judge_problems` keeps the errors the draft is responsible for.
* :func:`run_loop` asks, judges and sends the problems back, up to
  ``max_attempts``, and returns a :class:`~ducta.ai.drafts.Draft`.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, FrozenSet, List, Optional, Sequence, Set, Tuple

from ducta.ai.config import AIConfig, config_path
from ducta.ai.context import MAX_CHARS
from ducta.ai.drafts import Attempt, Draft, add_usage, utc_now
from ducta.ai.errors import AICancelledError, AIConfigError, AIEnvironmentError, AIError
from ducta.ai.providers import ChatMessage, Completion, LLMProvider

# ── the model's answer ──────────────────────────────────────────────────────

_BLOCK = re.compile(
    r"^[ \t]*```(?P<lang>[\w+-]*)[ \t]*(?P<meta>[^\n`]*)\n" r"(?:(?P<body>.*?)\n)?[ \t]*```[ \t]*$",
    re.DOTALL | re.MULTILINE,
)
_FILE_META = re.compile(r"(?:file|path)\s*[=:]\s*[\"']?(?P<path>[^\s\"']+)")


def _clean_path(path: str) -> str:
    """A path as the model wrote it, without the ``./`` some models put in front."""
    while path.startswith("./"):
        path = path[2:]
    return path


@dataclass
class ParsedAnswer:
    files: Dict[str, str] = field(default_factory=dict)
    catalog: Optional[str] = None
    notes: str = ""
    #: Blocks with no file name: (language, body). Small models often drop the
    #: info string; :func:`assemble` places them when the content says where.
    unnamed: List[Tuple[str, str]] = field(default_factory=list)


def parse_answer(text: str) -> ParsedAnswer:
    """The files and catalog additions in a model's answer."""
    out = ParsedAnswer()
    rest = text
    for m in _BLOCK.finditer(text):
        meta, body = m.group("meta").strip(), m.group("body") or ""
        rest = rest.replace(m.group(0), "")
        found = _FILE_META.search(meta)
        if found:
            out.files[_clean_path(found.group("path"))] = body.rstrip() + "\n"
        elif meta.lower().startswith("catalog"):
            out.catalog = ((out.catalog or "") + "\n" + body).strip() + "\n"
        else:
            # A header comment on the first line is the other common shape.
            first, _, remainder = body.partition("\n")
            header = re.match(r"#\s*(?:file|path)\s*[:=]\s*(\S+)", first.strip())
            if header:
                out.files[_clean_path(header.group(1))] = remainder.rstrip() + "\n"
            elif body.strip():
                out.unnamed.append((m.group("lang").lower(), body.rstrip() + "\n"))
    out.notes = rest.strip()
    return out


# ── what a draft may touch ──────────────────────────────────────────────────


@dataclass(frozen=True)
class Scope:
    """What a draft may touch."""

    #: ``new``: one new pipeline, new modules, new datasets. ``fix``: also a
    #: rewrite of the files in ``editable``.
    kind: str = "new"
    editable: FrozenSet[str] = frozenset()
    #: The pipeline being fixed.
    pipeline: Optional[str] = None
    #: What the draft is for, when not ``kind`` (``quality``, ``docs``: see
    #: :mod:`ducta.ai.proposals`), and the node it is about, if one.
    purpose: str = ""
    target: Optional[str] = None


NEW = Scope()


@dataclass
class Assembled:
    #: Project-relative path → full new text.
    files: Dict[str, str] = field(default_factory=dict)
    #: Why parts of the answer were not used; sent back to the model.
    rejected: List[str] = field(default_factory=list)
    new_datasets: List[str] = field(default_factory=list)
    #: SHA-256 of each file in ``files`` as it was read to build it (``None``: absent).
    base: Dict[str, Optional[str]] = field(default_factory=dict)


# ── validation ──────────────────────────────────────────────────────────────


def validate_files(root: Path, files: Dict[str, str]) -> List[Dict[str, Any]]:
    try:
        from ducta.project_store.draft_validation import validate_draft
        from ducta.project_store.store import V2ProjectStore
    except ImportError as e:
        raise AIEnvironmentError(
            "Validating drafts needs Ducta's AI extra: pip install 'ducta[ai]'"
        ) from e
    store = V2ProjectStore.detect(root)
    if store is None:
        raise AIConfigError(f"{root} is not a format-2 Ducta project (no ducta.yaml)")
    return [p.to_dict() for p in validate_draft(store, files)]


def problem_key(p: Dict[str, Any]) -> Tuple[Any, ...]:
    return (p.get("code"), p.get("file"), p.get("node"), p.get("message"))


def concerns(p: Dict[str, Any], scope: Scope) -> bool:
    """Whether problem *p* is on the pipeline a fix is about.

    Not for an extension: it adds to the pipeline as it is, problems included —
    only the errors it adds are its own.
    """
    if scope.kind != "fix" or scope.purpose == "extend":
        return False
    return p.get("pipeline") == scope.pipeline or p.get("file") in scope.editable


def judge_problems(
    problems: List[Dict[str, Any]], baseline: Set[Tuple[Any, ...]], scope: Scope
) -> List[Dict[str, Any]]:
    """The errors a draft is responsible for: new ones, and (a fix) those left on its pipeline."""
    return [
        p
        for p in problems
        if p.get("severity") == "error" and (problem_key(p) not in baseline or concerns(p, scope))
    ]


#: Characters per token, to size a request to a local model's window
#: (YAML and code run about three to four).
CHARS_PER_TOKEN = 3
#: Tokens left free in that window: the model's answer, and on a retry the
#: previous answer plus Ducta's feedback on it.
ANSWER_TOKENS = 3000
FEEDBACK_TOKENS = 500
#: The least project context worth sending with a request.
MIN_CONTEXT_CHARS = MAX_CHARS // 4


def message_budget(config: AIConfig, system: str) -> Optional[int]:
    """The characters a request (first message and earlier turns) may take, if limited.

    Only Ollama's window is Ducta's to set (``context_tokens``, sent as
    ``num_ctx``); other providers take far more than a request holds.
    """
    if config.provider != "ollama":
        return None
    free: int = (
        config.context_tokens - len(system) // CHARS_PER_TOKEN - 2 * ANSWER_TOKENS - FEEDBACK_TOKENS
    )
    return max(0, free) * CHARS_PER_TOKEN


def too_large(config: AIConfig, chars: int) -> AIConfigError:
    return AIConfigError(
        f"The request (about {chars // CHARS_PER_TOKEN:,} tokens, plus room for the answer) "
        f"does not fit the model's context window ({config.context_tokens:,} tokens). Raise "
        f"context_tokens in {config_path()} (if the model supports it) or narrow the request."
    )


def prompt_version(system: str) -> str:
    """A short fingerprint of a system prompt, kept with what it made.

    When a prompt changes, drafts, reviews and explanations say which one made
    them, so an evaluation can tell a better prompt from a better model.
    """
    return hashlib.sha256(system.encode("utf-8")).hexdigest()[:12]


def check_fits(config: AIConfig, system: str, message: str) -> None:
    """Raise before any request when *message* cannot fit the model's window."""
    budget = message_budget(config, system)
    if budget is not None and len(message) > budget:
        raise too_large(config, len(message))


def ask(
    provider: LLMProvider,
    system: str,
    message: str,
    *,
    readable: Callable[[str], bool],
    again: str,
) -> Tuple[Completion, Dict[str, int]]:
    """One request, and one more when its answer cannot be read or was cut off.

    For the features that answer once (reviews, explanations): a small model
    often drops the requested block, and an answer cut by the output limit
    parses as nothing. The second answer is returned when it came; a failed
    retry keeps the first. Returns the answer and the tokens both took.
    """
    messages = [ChatMessage("user", message)]
    first = provider.complete(system, messages)
    if readable(first.text) and not first.truncated:
        return first, dict(first.usage)
    why = (
        "was cut off by the output limit: be more concise"
        if first.truncated
        else "could not be read"
    )
    messages += [
        ChatMessage("assistant", first.text),
        ChatMessage("user", f"Your answer {why}. {again}"),
    ]
    try:
        second = provider.complete(system, messages)
    except AIError:
        return first, dict(first.usage)
    return second, add_usage(first.usage, second.usage)


#: How the model is asked to answer again, after problems or a change request.
AGAIN = "answer again with ALL the blocks (complete files, not just the changes)."


def feedback_message(
    assembled: Assembled, blocking: List[Dict[str, Any]], truncated: bool, again: str = AGAIN
) -> str:
    lines = [f"Ducta's validator rejected the draft. Fix every point and {again}"]
    if truncated:
        lines.append("- Your answer was cut off by the output limit: be more concise.")
    lines += [f"- {r}" for r in assembled.rejected]
    lines += [f"- {describe_problem(p)}" for p in blocking]
    return "\n".join(lines)


def describe_problem(p: Dict[str, Any]) -> str:
    where = ":".join(str(x) for x in (p.get("file"), p.get("line")) if x)
    fix = p.get("fix")
    hint = None
    if isinstance(fix, dict):
        # A Problem's fix is {label, replace: [old, new]}.
        swap = fix.get("replace")
        hint = fix.get("label") or fix.get("description")
        if isinstance(swap, list) and len(swap) == 2:
            hint = f"{hint + ': ' if hint else ''}replace '{swap[0]}' with '{swap[1]}'"
    return f"{where + ': ' if where else ''}{p.get('message')}" + (
        f" (suggested fix: {hint})" if hint else ""
    )


# ── the loop ────────────────────────────────────────────────────────────────


def run_loop(
    root: Path,
    provider: LLMProvider,
    *,
    system: str,
    first_message: str,
    scope: Scope,
    request: str,
    assembler: Callable[[ParsedAnswer], Assembled],
    max_attempts: Optional[int],
    on_attempt: Optional[Callable[[Attempt], None]],
    prior: Sequence[ChatMessage] = (),
    seen: Optional[Dict[str, Optional[str]]] = None,
    current: Optional[List[Dict[str, Any]]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
    again: str = AGAIN,
) -> Draft:
    """Ask, validate, send the problems back; *seen* hashes the files the prompt showed.

    *assembler* turns each parsed answer into the draft's files and what was
    rejected (:func:`ducta.ai.builder.default_assembler` for ``new`` and ``fix``).
    """
    from ducta.ai.policy import require_allowed

    require_allowed(root, provider.config)
    seen = dict(seen or {})
    budget = message_budget(provider.config, system)
    fixed = len(first_message) + sum(len(m.content) for m in prior)
    if budget is not None and fixed > budget:
        raise too_large(provider.config, fixed)
    if current is None:
        current = validate_files(root, {})
    baseline = {problem_key(p) for p in current if p.get("severity") == "error"}
    attempts = max_attempts or provider.config.max_attempts
    # A retry sends the request, the last answer and what was wrong with it:
    # earlier answers are superseded (each one is complete), so the
    # conversation does not outgrow the model's window attempt after attempt.
    base = [ChatMessage("user", first_message), *prior]
    messages = list(base)
    history: List[Attempt] = []
    assembled = Assembled()
    problems: List[Dict[str, Any]] = []
    blocking: List[Dict[str, Any]] = []
    answer = ParsedAnswer()
    completion: Optional[Completion] = None
    interrupted = ""
    for number in range(1, attempts + 1):
        if should_stop and should_stop():
            raise AICancelledError("Stopped")
        try:
            completion = provider.complete(system, messages)
        except AIError as e:
            if completion is None:
                raise
            # Keep what the earlier attempts produced rather than lose it.
            interrupted = f"Attempt {number} did not complete: {e.message}"
            break
        answer = parse_answer(completion.text)
        assembled = assembler(answer)
        assembled.base.update({rel: sha for rel, sha in seen.items() if rel in assembled.files})
        problems = validate_files(root, assembled.files) if assembled.files else []
        blocking = judge_problems(problems, baseline, scope)
        attempt = Attempt(
            number=number,
            files=list(assembled.files),
            errors=len(blocking),
            warnings=sum(1 for p in problems if p.get("severity") == "warning"),
            rejected=list(assembled.rejected),
            usage=completion.usage,
            messages=(list(assembled.rejected) + [describe_problem(p) for p in blocking])[:5],
        )
        history.append(attempt)
        if on_attempt:
            on_attempt(attempt)
        if assembled.files and not blocking and not assembled.rejected:
            break
        messages = base + [
            ChatMessage("assistant", completion.text),
            ChatMessage("user", feedback_message(assembled, blocking, completion.truncated, again)),
        ]

    rejected = [{"severity": "error", "message": r, "source": "ai"} for r in assembled.rejected]
    return Draft(
        id=datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6],
        request=request,
        provider=provider.config.provider,
        model=(completion.model if completion else provider.config.model) or "",
        created_at=utc_now(),
        ok=bool(assembled.files) and not assembled.rejected and not blocking,
        files=assembled.files,
        base={rel: assembled.base.get(rel) for rel in assembled.files},
        problems=problems + rejected,
        notes="\n\n".join(x for x in (answer.notes, interrupted) if x),
        new_datasets=assembled.new_datasets,
        attempts=history,
        raw_answer=completion.text if completion else "",
        kind=scope.purpose or scope.kind,
        pipeline=scope.pipeline,
        target=scope.target,
        blocking=blocking + rejected,
        prompt=first_message,
        seen=seen,
        prompt_version=prompt_version(system),
    )
