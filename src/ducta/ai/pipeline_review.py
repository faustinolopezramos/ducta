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

A review of a whole pipeline: every node, and what is only visible across them.

The same contract as a node's review (:mod:`ducta.ai.review`), one level up:

* Ducta's checks, without a model — each node's (:func:`ducta_checks`, with
  the node named on the finding), plus the pipeline's own: no owner, nodes
  with no description, nothing checking the data it writes.
* The model's findings, when a provider is given — it sees the pipeline's file,
  each node's function (numbered) and what Ducta knows of each. A finding names
  the node it is about and must point at a line of that node's function or a
  setting (:func:`check_finding`, per node); one that does not is dropped.
* Ideas for new nodes: the model's suggestions, *not* checked — each is a
  request for ``ducta ai extend``.

A review changes nothing; it is kept per pipeline, beside the nodes' reviews.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml  # type: ignore[import-untyped]

from ducta.ai.builder import _pipeline_file, _validate, message_budget, parse_answer
from ducta.ai.context import redact_config
from ducta.ai.errors import AIConfigError
from ducta.ai.providers import ChatMessage, LLMProvider
from ducta.ai.review import (
    AREAS,
    SEVERITIES,
    Finding,
    ReviewFacts,
    check_finding,
    ducta_checks,
    review_facts,
)

#: The most findings, and ideas, of the model's that are kept.
MAX_AI_FINDINGS = 12
MAX_IDEAS = 3
#: The most characters of a pipeline sent to the model (its file and functions).
MAX_PIPELINE_CHARS = 48_000

PIPELINE_REVIEW_PROMPT = """\
You review a whole Ducta data pipeline: its file, each node's Python function \
and how they fit together. Ducta gives you the facts and the findings it is \
sure of; add what it cannot see — logic errors, a node that undoes or repeats \
another's work, wrong assumptions about the data between nodes, wasteful Spark \
or pandas, settings that do not fit what the runs show.

Answer with ONE fenced block, ```yaml review, then nothing else:
```yaml review
findings:
  - node: <the node it is about; omit for the pipeline as a whole>
    severity: high | medium | low
    area: {areas}
    title: <what is wrong, in at most 10 words>
    line: <line number of THAT node's function, when it is about code>
    code: <the exact text of that line, or the part of it that matters>
    key: <the setting it is about, e.g. retry, timeout_seconds, metadata.owner>
    detail: <why it matters here, one or two sentences>
    suggestion: <the smallest change that fixes it>
ideas:
  - <a node worth adding to this pipeline, as a request: what it reads, what it computes, what it writes>
```
Rules:
- At most {max} findings, the most important first, and at most {ideas} ideas. \
None is a fine answer: `findings: []`, `ideas: []`.
- A finding about code names its node and gives `line` and `code` copied from \
that node's numbered code exactly; Ducta drops one whose line or text does not match.
- Do not repeat what Ducta already found. Do not invent nodes, columns, files \
or settings.
- Write title, detail, suggestion and ideas in the language of the user's \
note, or English.
"""


@dataclass
class PipelineReview:
    pipeline: str
    env: str
    created_at: str
    #: Each names its node (``None``: the pipeline itself).
    findings: List[Finding]
    #: Nodes worth adding, as requests for ``ducta ai extend`` — the model's, unchecked.
    ideas: List[str] = field(default_factory=list)
    nodes: List[str] = field(default_factory=list)
    model: Optional[str] = None
    dropped: int = 0
    notes: str = ""
    usage: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        out = asdict(self)
        out["findings"] = [f.to_dict() for f in self.findings]
        out["kind"] = "pipeline"
        return out

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PipelineReview":
        data = dict(data)
        fields = set(Finding.__dataclass_fields__)
        data["findings"] = [
            Finding(**{k: v for k, v in f.items() if k in fields})
            for f in data.get("findings") or []
        ]
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items() if k in known})


def _order(findings: List[Finding]) -> List[Finding]:
    rank = {s: i for i, s in enumerate(SEVERITIES)}
    return sorted(findings, key=lambda f: (rank[f.severity], f.source != "ducta", f.node or ""))


# ── facts and Ducta's checks ───────────────────────────────────────────────


def pipeline_facts(root: Path, pipeline: str, env: str = "dev") -> Dict[str, ReviewFacts]:
    """Each node's facts (:func:`review_facts`), in the pipeline's order."""
    path = _pipeline_file(root, pipeline)
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    nodes = doc.get("nodes") if isinstance(doc, dict) else None
    if not isinstance(nodes, dict) or not nodes:
        raise AIConfigError(f"Pipeline '{pipeline}' has no nodes to review")
    from ducta.setting.project_loader import apply_environment, read_project

    # The project and its problems are read once, for every node.
    resolved = apply_environment(read_project(root), env)
    problems = _validate(root, {})
    return {
        str(name): review_facts(
            root, pipeline, str(name), env, resolved=resolved, problems=problems
        )
        for name in nodes
    }


def _pipeline_findings(facts: Dict[str, ReviewFacts]) -> List[Finding]:
    """What is about the pipeline itself, not one node."""
    first = next(iter(facts.values()))
    settings = first.pipeline_settings
    out: List[Finding] = []
    if not (settings.get("metadata") or {}).get("owner"):
        out.append(
            Finding(
                "medium",
                "config",
                "No owner",
                "Nobody is named for this pipeline: an alert, an incident or a question has no one to go to.",
                "Set metadata.owner (a team or a person).",
                key="metadata.owner",
            )
        )
    if not settings.get("description"):
        out.append(
            Finding(
                "low",
                "config",
                "The pipeline has no description",
                "The catalog, the lineage and the docs show it without saying what it is for.",
                "Add a one-line description (or `ducta ai document`).",
                key="description",
            )
        )
    undescribed = [n for n, f in facts.items() if not f.spec.get("description")]
    if undescribed:
        out.append(
            Finding(
                "low",
                "config",
                f"{len(undescribed)} node{'s' if len(undescribed) != 1 else ''} without a description",
                f"{', '.join(undescribed[:6])}{' …' if len(undescribed) > 6 else ''} say nothing of what they do.",
                "Add a description to each (or `ducta ai document`).",
                key="description",
            )
        )
    if not any(f.spec.get("quality") for f in facts.values()):
        out.append(
            Finding(
                "medium",
                "quality",
                "Nothing in this pipeline checks its data",
                "No node has a quality block: bad data is written, and read further on, without a word.",
                "Add checks to its last node's output first (`ducta ai quality`).",
                key="quality",
            )
        )
    return out


def ducta_pipeline_checks(facts: Dict[str, ReviewFacts]) -> List[Finding]:
    """The findings Ducta is certain of, for every node and the pipeline, without a model."""
    out = _pipeline_findings(facts)
    seen = set()
    for node, f in facts.items():
        for finding in ducta_checks(f):
            # A problem of the pipeline's file shows on every node: once is enough.
            key = (finding.title, finding.detail, finding.file, finding.line)
            if key in seen:
                continue
            seen.add(key)
            out.append(replace(finding, node=node))
    return _order(out)


# ── the model's findings, checked ───────────────────────────────────────────


def _render(
    root: Path,
    pipeline: str,
    facts: Dict[str, ReviewFacts],
    found: List[Finding],
    remote: bool,
    note: str,
) -> str:
    first = next(iter(facts.values()))
    path = root / first.pipeline_rel
    doc = redact_config(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
    parts = [
        f"# Pipeline {pipeline} ({first.env})\n```yaml\n"
        + yaml.safe_dump(doc, sort_keys=False).strip()
        + "\n```"
    ]
    for name, f in facts.items():
        known: Dict[str, Any] = {
            "outputs written with": f.write_modes,
            "read elsewhere by": f.readers,
            "seconds per recent run (newest first)": f.durations or "no successful run yet",
        }
        block = [f"## Node {name}", "```json\n" + json.dumps(known, default=str) + "\n```"]
        code = f.numbered_code(remote)
        if code:
            fn = f.function or {}
            block.append(
                f"Its function {fn.get('function')} in {fn.get('file')}:\n```python\n{code}\n```"
            )
        elif f.spec.get("kind") == "ingest":
            block.append("An ingest node: no Python.")
        parts.append("\n".join(block))
    if found:
        parts.append(
            "# Ducta already found (do not repeat)\n"
            + "\n".join(
                f"- [{x.severity}] {x.node + ': ' if x.node else ''}{x.title}"
                + (f" (line {x.line})" if x.line else "")
                for x in found
            )
        )
    if note.strip():
        parts.append("# What the user says\n" + note.strip())
    return "\n\n".join(parts)


def _check(raw: Any, facts: Dict[str, ReviewFacts]) -> Optional[Finding]:
    """The model's finding, checked against the node it names (or the pipeline)."""
    if not isinstance(raw, dict):
        return None
    node = raw.get("node")
    if node not in (None, ""):
        node = str(node).strip()
        if node not in facts:
            return None  # a node this pipeline does not have
        found = check_finding(raw, facts[node])
        return replace(found, node=node) if found else None
    # About the pipeline: no line of any function, only a setting (or none).
    pipeline_level = replace(next(iter(facts.values())), function=None, code_lines=[])
    raw = {k: v for k, v in raw.items() if k not in ("line", "code")}
    return check_finding(raw, pipeline_level)


def _ideas(raw: Any) -> List[str]:
    if not isinstance(raw, list):
        return []
    out: List[str] = []
    for item in raw:
        text = item.get("request") or item.get("title") if isinstance(item, dict) else item
        text = re.sub(r"\s+", " ", str(text or "")).strip()
        if 10 <= len(text) <= 400 and text not in out:
            out.append(text)
    return out[:MAX_IDEAS]


def review_pipeline(
    root: Path,
    pipeline: str,
    provider: Optional[LLMProvider],
    *,
    env: str = "dev",
    note: str = "",
) -> PipelineReview:
    """Ducta's findings for *pipeline*, plus the model's when *provider* is given — each checked."""
    root = Path(root).resolve()
    facts = pipeline_facts(root, pipeline, env)
    found = ducta_pipeline_checks(facts)
    review = PipelineReview(
        pipeline=pipeline,
        env=env,
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        findings=list(found),
        nodes=list(facts),
    )
    if provider is None:
        return review
    message = _render(root, pipeline, facts, found, remote=not provider.config.is_local, note=note)
    system = PIPELINE_REVIEW_PROMPT.format(
        areas=" | ".join(AREAS), max=MAX_AI_FINDINGS, ideas=MAX_IDEAS
    )
    limit = MAX_PIPELINE_CHARS
    budget = message_budget(provider.config, system)
    if budget is not None:
        limit = min(limit, budget)
    if len(message) > limit:
        raise AIConfigError(
            f"Pipeline '{pipeline}' is too large to review whole with this model "
            f"({len(message):,} characters; {limit:,} fit). Review its nodes one by one "
            f"(`ducta ai review {pipeline} <node>`), or raise context_tokens."
        )
    completion = provider.complete(system, [ChatMessage("user", message)])
    review.model = completion.model or provider.config.model
    review.usage = dict(completion.usage)
    answer = parse_answer(completion.text)
    bodies = [b for lang, b in answer.unnamed if lang in ("yaml", "yml", "")] + list(
        answer.files.values()
    )
    try:
        data = yaml.safe_load(bodies[0]) if bodies else None
    except yaml.YAMLError:
        data = None
    if not isinstance(data, dict):
        review.notes = "The model's answer could not be read; only Ducta's findings are shown."
        return review
    found_raw = data.get("findings")
    raw: List[Any] = found_raw if isinstance(found_raw, list) else []
    asked = raw[: MAX_AI_FINDINGS * 2]
    checked = [f for f in (_check(r, facts) for r in asked) if f]
    review.dropped = len(asked) - len(checked)
    said = {(f.node, f.key) for f in found if f.key} | {(f.node, f.line) for f in found if f.line}
    kept = [
        f
        for f in checked
        if (f.node, f.key) not in said and ((f.node, f.line) not in said or f.key)
    ]
    review.findings = _order(found + kept[:MAX_AI_FINDINGS])
    review.ideas = _ideas(data.get("ideas"))
    return review


# ── kept per pipeline ───────────────────────────────────────────────────────


def _path(root: Path, pipeline: str) -> Path:
    safe = "".join(c for c in pipeline if c.isalnum() or c in "-_.")
    return Path(root) / ".ducta" / "ai" / "reviews" / "pipelines" / f"{safe}.json"


def save_pipeline_review(root: Path, review: PipelineReview) -> Path:
    from ducta.ai.fsutil import atomic_write_text

    path = _path(root, review.pipeline)
    return atomic_write_text(path, json.dumps(review.to_dict(), indent=2, ensure_ascii=False))


def load_pipeline_review(root: Path, pipeline: str) -> Optional[PipelineReview]:
    try:
        data = json.loads(_path(root, pipeline).read_text(encoding="utf-8"))
        return PipelineReview.from_dict(data)
    except (OSError, ValueError, TypeError):
        return None


__all__ = [
    "PipelineReview",
    "ducta_pipeline_checks",
    "load_pipeline_review",
    "pipeline_facts",
    "review_pipeline",
    "save_pipeline_review",
]
