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

Ducta Architect, step one: a blueprint for a request.

The model answers with a blueprint (or with the questions it needs answered);
Ducta checks it (:func:`check_blueprint`), renders it with stub functions and
validates the result like any draft — so a blueprint that passes here builds
into a project that loads. What comes back is a draft of kind ``blueprint``:
reviewed, revised with ``ducta ai revise``, built with
``ducta ai architect build``; never applied as it is.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import yaml  # type: ignore[import-untyped]

from ducta.ai.agents.architect.blueprint import (
    Blueprint,
    Existing,
    check_blueprint,
    load_blueprint,
    parse_blueprint,
    render,
)
from ducta.ai.builder import (
    _MIN_CONTEXT_CHARS,
    MAX_CHARS,
    Assembled,
    Draft,
    ParsedAnswer,
    Scope,
    _describe,
    _judge,
    _key,
    _run,
    _too_large,
    _validate,
    build_context,
    message_budget,
)
from ducta.ai.errors import AIConfigError, AIError
from ducta.ai.providers import LLMProvider

ARCHITECT_PROMPT = """\
You are Ducta Architect: you design data pipelines for a Ducta project as a \
BLUEPRINT — names, datasets, contracts and the logic of each step in words. \
You write no code and no project files: Ducta checks the blueprint and writes \
the files itself.

Answer with ONE fenced block, ```yaml blueprint, then at most five short lines \
on the design choices:
```yaml blueprint
name: <short_snake_name>
goal: <one line>
assumptions: [<what you assumed>]
datasets:                      # only NEW datasets; reuse the catalog's as inputs
  <layer>.<domain>.<table>:
    description: <what one row is>
    format: <omit to use the project's default for the layer>
    keys: [<column>]           # what identifies a row
    write: overwrite           # overwrite | merge (needs keys and format: delta) | append (avoid)
    columns: {<column>: <type>}
    not_null: [<column>]
    unique: [<column>]
    pii: [<column>]            # only columns that identify or contact a person
pipelines:                     # only NEW pipelines, named <layer>.<domain>
  <layer>.<domain>:
    description: <one line>
    owner: <team, if the request says>
    nodes:
      <node_name>:             # unique in the whole project
        description: <one line>
        inputs: {<param>: <dataset>}   # parameter name -> dataset it receives
        outputs: [<dataset>]           # exactly one
        logic: <the transformation, precisely, in words: filters, joins, keys, aggregations>
      <ingest_node>:           # reads a declared source, no code
        kind: ingest
        ingest: {source: <source name>, table: <schema.table>}
        outputs: [<dataset>]
```
Rules:
- Data flows bronze -> silver -> gold: bronze lands raw data, silver cleans and \
conforms it, gold aggregates it for a use. Never read a higher layer to write a lower one.
- Reuse the catalog's datasets as inputs; never redeclare them. Every new dataset \
is written by exactly one node.
- Prefer one pipeline per layer and domain; a node does one clear step.
- Use only the sources the project declares for ingest nodes.
- Follow the project's naming conventions. Write descriptions in the language of \
the request.

If the request lacks something you cannot reasonably assume (which source, what \
identifies a row, the grain of an aggregate), answer INSTEAD with ONE block:
```yaml questions
questions:
  - <a short, specific question>
```
"""

AGAIN_BLUEPRINT = "answer again with the complete blueprint block."


class NeedsAnswers(AIError):
    """The model needs answers before it can design: ask the person, then retry."""

    exit_code = 1
    http_status = 422

    def __init__(self, questions: List[str]):
        super().__init__("The model needs answers first: " + " | ".join(questions))
        self.questions = questions


@dataclass
class CheckReport:
    """A blueprint judged without a model: its own rules, then the project's validator."""

    blueprint: Optional[Blueprint]
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    files: Dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.blueprint is not None and not self.errors

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "name": self.blueprint.name if self.blueprint else None,
            "errors": self.errors,
            "warnings": self.warnings,
            "files": sorted(self.files),
        }


def check(root: Path, text: str) -> CheckReport:
    """Everything Ducta can say about a blueprint's YAML *text* — no model involved."""
    root = Path(root).resolve()
    bp, problems = load_blueprint(text)
    report = CheckReport(blueprint=bp, errors=list(problems))
    if bp is None:
        return report
    ctx = build_context(root)
    if ctx.config_error:
        report.errors.append(f"The project does not validate now: {ctx.config_error}")
        return report
    existing = Existing.of(root, ctx)
    errors, warnings = check_blueprint(root, bp, existing)
    report.errors += errors
    report.warnings += warnings
    if report.errors:
        return report
    report.files, _ = render(root, bp, existing)
    baseline = {_key(p) for p in _validate(root, {}) if p.get("severity") == "error"}
    problems_after = _validate(root, report.files)
    report.errors += [_describe(p) for p in _judge(problems_after, baseline, Scope())]
    report.warnings += [
        _describe(p)
        for p in problems_after
        if p.get("severity") == "warning" and p.get("file") in report.files
    ]
    return report


def _questions(answer: ParsedAnswer) -> List[str]:
    for _lang, body in answer.unnamed:
        try:
            data = yaml.safe_load(body)
        except yaml.YAMLError:
            continue
        if isinstance(data, dict) and isinstance(data.get("questions"), list):
            return [str(q) for q in data["questions"] if str(q).strip()]
    return []


def _bodies(answer: ParsedAnswer) -> List[str]:
    bodies = [b for lang, b in answer.unnamed if lang in ("yaml", "yml", "")]
    return bodies + list(answer.files.values()) + ([answer.catalog] if answer.catalog else [])


def _blueprint_body(answer: ParsedAnswer) -> Optional[str]:
    """The answer's blueprint block: the first YAML block with ``pipelines``."""
    for body in _bodies(answer):
        try:
            data = yaml.safe_load(body)
        except yaml.YAMLError:
            continue
        if isinstance(data, dict) and ("pipelines" in data or "blueprint" in data):
            return body
    return None


def blueprint_assembler(
    root: Path, existing: Existing, warnings: List[str]
) -> Callable[[ParsedAnswer], Assembled]:
    """Parse, check and render the model's blueprint; *warnings* collects the last attempt's."""

    def assemble(answer: ParsedAnswer) -> Assembled:
        out = Assembled()
        body = _blueprint_body(answer)
        asked = _questions(answer)
        if asked and body is None:
            raise NeedsAnswers(asked)
        if body is None:
            # Not recognisable as a blueprint: its first block, so the problems say why.
            body = next(iter(_bodies(answer)), None)
        if body is None:
            out.rejected.append("The answer has no ```yaml blueprint block")
            return out
        bp, problems = load_blueprint(body)
        out.rejected += problems
        if bp is None:
            return out
        errors, found = check_blueprint(root, bp, existing)
        out.rejected += errors
        warnings[:] = found
        if out.rejected:
            return out
        out.files, out.base = render(root, bp, existing)
        out.new_datasets = list(bp.datasets)
        return out

    return assemble


def _first_message(root: Path, provider: LLMProvider, request: str, note: str) -> str:
    ctx = build_context(root)
    if ctx.config_error:
        raise AIConfigError(
            "The project does not validate now, so a blueprint could not be checked: "
            f"{ctx.config_error}. Fix it first (`ducta ai fix <pipeline>` can help)."
        )
    tail = f"\n\n# Request\n{request.strip()}"
    if note.strip():
        tail += f"\n\n# What the user adds\n{note.strip()}"
    room = MAX_CHARS
    budget = message_budget(provider.config, ARCHITECT_PROMPT)
    if budget is not None:
        room = min(room, budget - len(tail))
        if room < _MIN_CONTEXT_CHARS:
            raise _too_large(provider.config, _MIN_CONTEXT_CHARS + len(tail))
    return ctx.render(room) + tail


def design(
    root: Path,
    request: str,
    provider: LLMProvider,
    *,
    note: str = "",
    max_attempts: Optional[int] = None,
    on_attempt: Optional[Callable[..., None]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
) -> Draft:
    """A checked blueprint for *request*: a draft of kind ``blueprint``.

    Raises :class:`NeedsAnswers` when the model asks questions instead.
    """
    root = Path(root).resolve()
    if not request.strip():
        raise AIConfigError("Describe what to build")
    first = _first_message(root, provider, request, note)
    ctx = build_context(root)
    warnings: List[str] = []
    draft = _run(
        root,
        provider,
        system=ARCHITECT_PROMPT,
        first_message=first,
        scope=Scope(kind="new", purpose="blueprint"),
        request=request.strip(),
        ctx=ctx,
        max_attempts=max_attempts,
        on_attempt=on_attempt,
        should_stop=should_stop,
        assembler=blueprint_assembler(root, Existing.of(root, ctx), warnings),
        again=AGAIN_BLUEPRINT,
    )
    draft.evidence = "; ".join(warnings)
    return draft


def blueprint_setup(
    root: Path, draft: Draft
) -> Tuple[Scope, str, Callable[[ParsedAnswer], Assembled], str]:
    """What :func:`ducta.ai.builder.revise` needs to continue a blueprint's conversation."""
    root = Path(root).resolve()
    ctx = build_context(root)
    warnings: List[str] = []
    return (
        Scope(kind="new", purpose="blueprint"),
        ARCHITECT_PROMPT,
        blueprint_assembler(root, Existing.of(root, ctx), warnings),
        AGAIN_BLUEPRINT,
    )


def blueprint_of(draft: Draft) -> Blueprint:
    """The blueprint a ``blueprint`` draft holds (its last answer)."""
    if draft.kind != "blueprint":
        raise AIConfigError(f"Draft {draft.id} is a {draft.kind} draft, not a blueprint")
    from ducta.ai.builder import parse_answer

    body = _blueprint_body(parse_answer(draft.raw_answer))
    bp, problems = load_blueprint(body or "")
    if bp is None or problems:
        raise AIConfigError(f"Draft {draft.id} holds no readable blueprint: {'; '.join(problems)}")
    return bp


__all__ = [
    "ARCHITECT_PROMPT",
    "CheckReport",
    "NeedsAnswers",
    "blueprint_of",
    "blueprint_setup",
    "check",
    "design",
    "parse_blueprint",
]
