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

Proposals: the model suggests, Ducta writes.

* :func:`propose_quality` — the checks and gate for one node's output. Ducta
  measures the output (aggregates only: the model never sees a row), the model
  proposes the block, and Ducta runs it on what it measured: a check that
  would fail on today's data goes back to the model, not to you.
* :func:`propose_docs` — descriptions for the datasets, pipelines and nodes
  that have none, and which columns hold personal data (``metadata.pii``).

In both, the model answers with the proposal only, never a file. Ducta puts it
in the file itself (comments and layout kept) and can only add what was asked:
a node's ``quality`` block, or a missing ``description`` / ``metadata.pii``.
Each becomes an ordinary draft — validated, reviewed, applied or discarded.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Dict, List, Optional, Tuple

import yaml  # type: ignore[import-untyped]

from ducta.ai.builder import (
    Assembled,
    Draft,
    ParsedAnswer,
    Scope,
    _pipeline_file,
    _read,
    _run,
    _sha,
    build_context,
)
from ducta.ai.errors import AIConfigError, AINotFoundError
from ducta.ai.providers import LLMProvider
from ducta.ai.yaml_edit import edit_yaml, mapping

#: The checks a proposal may use: the ones Ducta can run on the measured
#: sample to prove they pass (``business_rules`` runs on Spark only; checks
#: against another dataset need that dataset).
QUALITY_CHECKS: Dict[str, str] = {
    "schema": "{expected_columns: [col, ...], strict: false}",
    "row_count": "{min: N, max: N}",
    "empty_dataset": "true",
    "null_rate": "{columns: [col, ...], threshold: 0.0}   # share 0..1 that may be null",
    "duplicates": "{columns: [col, ...], max_duplicate_rate: 0.0}",
    "range": "{column: col, min: N, max: N}",
}
_BLOCK_KEYS = {"checks", "gate", "fail_fast", "enabled", "dataset_name"}
_GATE_KEYS = {"max_errors", "max_warnings", "min_pass_rate", "required_checks", "on_fail"}
#: Rows of the output measured for a proposal (the row count is always the full one).
MAX_ROWS = 50_000

AGAIN_PROPOSAL = "answer again with the complete proposal block."

QUALITY_PROMPT = """\
You propose the data-quality checks of one node of a Ducta pipeline: the block \
that goes under the node's `quality:` key. Ducta measured the node's output; \
you get column statistics, never rows.

Answer with ONE fenced block, ```yaml quality, holding the COMPLETE new block, \
then at most five short lines saying why each check matters for this data.

Use only these checks (a check may also be given another name with `type: <check>`):
{checks}
and a gate: `gate: {{max_errors: 0, on_fail: skip_downstream}}` (on_fail: \
skip_downstream, stop_all or warn_only).

Rules:
- Every check must PASS on the measured data: a null_rate threshold at or above \
the observed rate, range bounds at or beyond the observed min and max, a \
row_count min at or below the observed rows. Ducta runs your block on that data \
and sends back any check that fails.
- A row_count gets a `min` only — a floor well below today's rows — never a \
`max`: tomorrow's data will be larger.
- Prefer checks that catch real breakage: keys never null or duplicated, \
amounts in a sane range, a floor on the row count. Skip checks that say nothing.
- Keep the node's current checks unless a measured fact shows one is wrong.
- Use column names exactly as listed.
"""

DOCS_PROMPT = """\
You document a Ducta data project: short descriptions for the datasets, \
pipelines and nodes that have none, and which columns hold personal data.

Answer with ONE fenced block, ```yaml docs, in this shape, listing only what \
is asked for:
```yaml docs
datasets:
  <dataset name>: {{description: <one line>, pii: [<column>, ...]}}
pipelines:
  <pipeline name>:
    description: <one line>
    nodes: {{<node name>: <one line>}}
```
Rules:
- A description says what one row is, or what the step does, in one line of \
at most 15 words, in the language the project's other descriptions use \
(English when there are none).
- `pii` lists only columns that identify or contact a person (names, emails, \
phones, addresses, national ids). Leave it out when there are none or the \
columns are unknown.
- Use the names exactly as listed. Do not describe anything not listed.
"""


# ── shared ──────────────────────────────────────────────────────────────────


def _block(answer: ParsedAnswer, wanted: str) -> Tuple[Optional[Any], Optional[str]]:
    """The proposal's YAML mapping, or why there is none."""
    bodies = [body for lang, body in answer.unnamed if lang in ("yaml", "yml", "")]
    if answer.catalog:
        bodies.append(answer.catalog)
    bodies += list(answer.files.values())
    if not bodies:
        return None, f"The answer has no ```yaml {wanted} block"
    try:
        data = yaml.safe_load(bodies[0])
    except yaml.YAMLError as e:
        return None, f"The {wanted} block is not valid YAML: {e}"
    if isinstance(data, dict) and set(data) == {wanted} and isinstance(data[wanted], dict):
        data = data[wanted]
    if not isinstance(data, dict) or not data:
        return None, f"The {wanted} block must be a non-empty mapping"
    return data, None


def _yaml_only(root: Path, rel: str) -> None:
    if PurePosixPath(rel).suffix not in (".yaml", ".yml"):
        raise AIConfigError(f"{rel}: proposals are written to YAML files only")


# ── quality ─────────────────────────────────────────────────────────────────


@dataclass
class QualityFacts:
    """What Ducta knows about a node's output before asking the model."""

    pipeline: str
    pipeline_rel: str
    node: str
    dataset: str
    env: str
    current: Optional[Dict[str, Any]]
    rows: Optional[int] = None
    measured_rows: Optional[int] = None
    columns: List[Dict[str, Any]] = field(default_factory=list)
    #: Ducta's own inference: checks that pass on the data, as a starting point.
    baseline: Dict[str, Any] = field(default_factory=dict)
    #: Why the output could not be measured, when it could not.
    unmeasured: Optional[str] = None
    frame: Any = None

    def render(self) -> str:
        facts: Dict[str, Any] = {
            "pipeline": self.pipeline,
            "node": self.node,
            "output dataset": self.dataset,
            "environment measured": self.env,
        }
        if self.unmeasured:
            facts["measured"] = f"no — {self.unmeasured}"
        else:
            facts["rows"] = self.rows
            if self.measured_rows and self.rows and self.measured_rows < self.rows:
                facts["statistics from the first"] = f"{self.measured_rows} rows"
            facts["columns"] = self.columns
        parts = [
            "# The node's output\n```json\n" + json.dumps(facts, indent=2, default=str) + "\n```"
        ]
        parts.append(
            "# Its current quality block\n```yaml\n"
            + (yaml.safe_dump(self.current, sort_keys=False).strip() if self.current else "(none)")
            + "\n```"
        )
        if self.baseline:
            parts.append(
                "# Checks Ducta infers from the data (they pass; improve on them)\n```yaml\n"
                + yaml.safe_dump(self.baseline, sort_keys=False).strip()
                + "\n```"
            )
        return "\n\n".join(parts)


def _column_facts(profile: Any) -> List[Dict[str, Any]]:
    """Aggregates per column — never a value of a text column (no top values)."""
    out = []
    for c in profile.columns:
        fact: Dict[str, Any] = {
            "name": c.name,
            "type": c.kind,
            "null_rate": round(c.null_rate, 6),
            "distinct": c.distinct_count,
        }
        if c.is_key_candidate:
            fact["key_candidate"] = True
        if c.kind == "numeric" and c.minimum is not None:
            fact["min"], fact["max"] = c.minimum, c.maximum
        out.append(fact)
    return out


def quality_facts(root: Path, pipeline: str, node: str, env: str = "dev") -> QualityFacts:
    """The node, its current checks, and its output measured in *env* (when it can be)."""
    root = Path(root).resolve()
    path = _pipeline_file(root, pipeline)
    rel = path.relative_to(root).as_posix()
    _yaml_only(root, rel)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    nodes = data.get("nodes") or {}
    if node not in nodes:
        raise AINotFoundError(
            f"No node '{node}' in pipeline '{pipeline}' (its nodes: {', '.join(nodes) or 'none'})"
        )
    spec = nodes[node] or {}
    current = spec.get("quality") if isinstance(spec.get("quality"), dict) else None
    outputs = list(spec.get("outputs") or [])
    dataset = (current or {}).get("dataset_name") or (outputs[0] if outputs else None)
    if not dataset:
        raise AIConfigError(f"Node '{node}' writes no dataset: there is nothing to check")
    facts = QualityFacts(pipeline, rel, node, dataset, env, current)
    try:
        from ducta.api.services.dataset_preview import dataset_location, read_frame
        from ducta.check.profiling import infer_spec, profile_dataset

        location, fmt = dataset_location(root, env, dataset)
        frame, _cols, total = read_frame(location, fmt, limit=MAX_ROWS)
        profile = profile_dataset(frame, dataset_name=dataset)
    except KeyError:
        facts.unmeasured = f"'{dataset}' is not in the catalog of {env}"
        return facts
    except Exception as e:  # noqa: BLE001 — not materialized, remote, unreadable: say so
        facts.unmeasured = str(e) or type(e).__name__
        return facts
    facts.frame = frame
    facts.measured_rows = len(frame)
    facts.rows = total if total is not None else len(frame)
    facts.columns = _column_facts(profile)
    facts.baseline = (infer_spec(profile) or {}).get("checks") or {}
    return facts


def _check_type(name: str, params: Any) -> str:
    return str(params.get("type")) if isinstance(params, dict) and params.get("type") else name


def _quality_problems(block: Dict[str, Any], facts: QualityFacts) -> List[str]:
    """What is wrong with a proposed block before it is run."""
    problems: List[str] = []
    raw = block.get("checks")
    checks: Dict[str, Any] = raw if isinstance(raw, dict) else {}
    inline = {k: v for k, v in block.items() if k not in _BLOCK_KEYS}
    every = {**checks, **inline}
    if not every:
        problems.append("The block has no checks")
    known = {c["name"] for c in facts.columns}
    for name, params in every.items():
        kind = _check_type(name, params)
        if kind not in QUALITY_CHECKS:
            problems.append(f"'{name}': only {', '.join(QUALITY_CHECKS)} may be proposed")
            continue
        if not known or not isinstance(params, dict):
            continue
        named = list(params.get("columns") or []) + list(params.get("expected_columns") or [])
        if params.get("column"):
            named.append(params["column"])
        missing = [c for c in named if c not in known]
        if missing:
            problems.append(
                f"'{name}' names {', '.join(map(str, missing))}, not a column of "
                f"{facts.dataset} (its columns: {', '.join(sorted(known))})"
            )
    gate = block.get("gate")
    if gate is not None and not (isinstance(gate, dict) and set(gate) <= _GATE_KEYS):
        problems.append(f"gate: only {', '.join(sorted(_GATE_KEYS))} may be set")
    return problems


def run_on_sample(block: Dict[str, Any], facts: QualityFacts) -> List[str]:
    """The proposed checks that fail on the measured data, with why."""
    if facts.frame is None:
        return []
    from ducta.check import ValidationPhaseRunner
    from ducta.check.core import QualityChecksFailed

    checks = dict(block.get("checks") or {})
    checks.update({k: v for k, v in block.items() if k not in _BLOCK_KEYS})
    with tempfile.TemporaryDirectory(prefix="ducta-ai-quality-") as workspace:
        try:
            report = ValidationPhaseRunner(workspace_path=workspace, fail_fast=False).run(
                dataset_name=facts.dataset, df=facts.frame, config={"checks": checks}
            )
            results = list(getattr(report, "results", []) or [])
        except QualityChecksFailed as e:
            results = list(getattr(e, "results", []) or [])
    return [
        f"'{r.check_name}' fails on the measured data: {r.message}"
        for r in results
        if not getattr(r, "passed", True)
    ]


def quality_assembler(root: Path, facts: QualityFacts) -> Callable[[ParsedAnswer], Assembled]:
    def assemble(answer: ParsedAnswer) -> Assembled:
        out = Assembled()
        block, why = _block(answer, "quality")
        if why:
            out.rejected.append(why)
            return out
        assert block is not None
        out.rejected += _quality_problems(block, facts)
        if out.rejected:
            return out
        out.rejected += run_on_sample(block, facts)
        if out.rejected:
            return out
        if block == facts.current:
            out.rejected.append(
                "The proposal is the node's current block: change something or say why not"
            )
            return out
        text = _read(root / facts.pipeline_rel) or ""

        def put(doc: Any) -> None:
            new = mapping(block)
            new.fa.set_block_style()  # the block itself stays one key per line
            doc["nodes"][facts.node]["quality"] = new

        new = edit_yaml(text, put)
        if new == text:
            out.rejected.append(
                "The proposal is the node's current block: change something or say why not"
            )
            return out
        out.files[facts.pipeline_rel] = new
        out.base[facts.pipeline_rel] = _sha(text)
        return out

    return assemble


def _quality_scope(facts: QualityFacts) -> Scope:
    return Scope(
        kind="proposal",
        editable=frozenset({facts.pipeline_rel}),
        pipeline=facts.pipeline,
        purpose="quality",
        target=facts.node,
    )


def propose_quality(
    root: Path,
    pipeline: str,
    node: str,
    provider: LLMProvider,
    *,
    env: str = "dev",
    note: str = "",
    max_attempts: Optional[int] = None,
    on_attempt: Optional[Callable[..., None]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
) -> Draft:
    """A draft of the quality block for *node*'s output, proven on its data in *env*."""
    root = Path(root).resolve()
    facts = quality_facts(root, pipeline, node, env)
    message = facts.render() + (f"\n\n# What the user says\n{note.strip()}" if note.strip() else "")
    system = QUALITY_PROMPT.format(
        checks="\n".join(f"- {name}: {shape}" for name, shape in QUALITY_CHECKS.items())
    )
    draft = _run(
        root,
        provider,
        system=system,
        first_message=message,
        scope=_quality_scope(facts),
        request=note.strip() or f"Quality checks for {pipeline}.{node}",
        ctx=build_context(root),
        max_attempts=max_attempts,
        on_attempt=on_attempt,
        seen={facts.pipeline_rel: _sha(_read(root / facts.pipeline_rel))},
        should_stop=should_stop,
        assembler=quality_assembler(root, facts),
        again=AGAIN_PROPOSAL,
    )
    draft.env = env
    draft.evidence = _evidence(facts)
    return draft


def _evidence(facts: QualityFacts) -> str:
    if facts.unmeasured:
        return (
            f"Not checked against data: {facts.unmeasured}. Run the pipeline in {facts.env} "
            "first to have the checks proven on its output."
        )
    measured = facts.measured_rows or 0
    of = f" (the first of {facts.rows:,})" if facts.rows and facts.rows > measured else ""
    return f"Proven on {measured:,} rows of {facts.env}{of}."


def quality_evidence(root: Path, draft: Draft) -> str:
    """What a revised quality draft was checked against (measured again)."""
    try:
        return _evidence(
            quality_facts(root, draft.pipeline or "", draft.target or "", draft.env or "dev")
        )
    except Exception:  # noqa: BLE001 — the draft stands; only the sentence is missing
        return ""


# ── documentation ───────────────────────────────────────────────────────────


@dataclass
class DocsFacts:
    """What has no description, with what explains it."""

    datasets: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    pipelines: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    #: Where each dataset / pipeline is written (project-relative).
    dataset_files: Dict[str, str] = field(default_factory=dict)
    pipeline_files: Dict[str, str] = field(default_factory=dict)
    examples: List[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.datasets and not self.pipelines

    def render(self) -> str:
        parts = []
        if self.examples:
            parts.append(
                "# Descriptions the project already has (match their style)\n"
                + "\n".join(self.examples)
            )
        parts.append(
            "# What to document\n```json\n"
            + json.dumps(
                {"datasets": self.datasets, "pipelines": self.pipelines}, indent=2, default=str
            )
            + "\n```"
        )
        return "\n\n".join(parts)


def _columns_of(root: Path, name: str, entry: Dict[str, Any], env: str) -> List[str]:
    """A dataset's column names: from its schema, or the header of its local data."""
    schema = entry.get("schema")
    if isinstance(schema, dict):
        listed = schema.get("columns")
        cols: Any = listed if isinstance(listed, (dict, list)) else schema
        return [str(c.get("name") if isinstance(c, dict) else c) for c in cols][:80]
    try:
        from ducta.api.services.dataset_preview import dataset_location, read_frame

        location, fmt = dataset_location(root, env, name)
        _frame, cols, _total = read_frame(location, fmt, limit=1)
        return [c["name"] for c in cols][:80]
    except Exception:  # noqa: BLE001 — unknown columns are just not listed
        return []


def docs_facts(root: Path, env: str = "dev", limit: int = 60, columns: bool = True) -> DocsFacts:
    """The undocumented datasets, pipelines and nodes, at most *limit* of each.

    ``columns=False`` skips reading column names (counting what is missing).
    """
    from ducta.setting.project_loader import read_project

    root = Path(root).resolve()
    located = read_project(root, expand=False)
    facts = DocsFacts()
    writers: Dict[str, List[str]] = {}
    for pname, pdata in located.pipelines.items():
        for nname, nspec in ((pdata or {}).get("nodes") or {}).items():
            for out in (nspec or {}).get("outputs") or []:
                writers.setdefault(str(out), []).append(
                    f"{pname}.{nname} ({(nspec or {}).get('run', 'ingest')})"
                )
    for name, entry in located.catalog.items():
        entry = entry if isinstance(entry, dict) else {}
        rel = (
            located.catalog_files[name].relative_to(root).as_posix()
            if name in located.catalog_files
            else None
        )
        if entry.get("description"):
            if len(facts.examples) < 5:
                facts.examples.append(f"- {name}: {entry['description']}")
            continue
        if not rel or PurePosixPath(rel).suffix not in (".yaml", ".yml"):
            continue
        if len(facts.datasets) >= limit:
            break
        raw_meta = entry.get("metadata")
        metadata: Dict[str, Any] = raw_meta if isinstance(raw_meta, dict) else {}
        fact: Dict[str, Any] = {"format": entry.get("format"), "written by": writers.get(name, [])}
        found = [] if metadata.get("pii") or not columns else _columns_of(root, name, entry, env)
        if found:
            fact["columns"] = found
        facts.datasets[name] = fact
        facts.dataset_files[name] = rel
    for pname, pdata in located.pipelines.items():
        pdata = pdata or {}
        rel = located.pipeline_files[pname].relative_to(root).as_posix()
        if PurePosixPath(rel).suffix not in (".yaml", ".yml"):
            continue
        missing_nodes = {
            n: {
                "run": (s or {}).get("run"),
                "inputs": (s or {}).get("inputs"),
                "outputs": (s or {}).get("outputs"),
            }
            for n, s in (pdata.get("nodes") or {}).items()
            if not (s or {}).get("description")
        }
        if pdata.get("description") and not missing_nodes:
            continue
        if len(facts.pipelines) >= limit:
            break
        facts.pipelines[pname] = {
            "needs": [x for x in ("description",) if not pdata.get("description")]
        }
        if missing_nodes:
            facts.pipelines[pname]["nodes"] = missing_nodes
        facts.pipeline_files[pname] = rel
    return facts


def _docs_edits(
    block: Dict[str, Any], facts: DocsFacts
) -> Tuple[Dict[str, List[Callable[[Any], None]]], List[str]]:
    """Per file, the edits that add what the proposal says; and what it may not say."""
    edits: Dict[str, List[Callable[[Any], None]]] = {}
    problems: List[str] = []
    unknown = set(block) - {"datasets", "pipelines"}
    if unknown:
        problems.append(
            f"Only `datasets` and `pipelines` may be listed, not {', '.join(sorted(unknown))}"
        )

    for name, doc in (block.get("datasets") or {}).items():
        if name not in facts.datasets:
            problems.append(
                f"Dataset '{name}' was not asked for (it has a description, or does not exist)"
            )
            continue
        doc = doc if isinstance(doc, dict) else {"description": doc}
        description = str(doc.get("description") or "").strip()
        pii = [str(c) for c in (doc.get("pii") or []) if isinstance(c, (str, int))]
        known = facts.datasets[name].get("columns") or []
        bad = [c for c in pii if c not in known]
        if bad:
            problems.append(f"Dataset '{name}': {', '.join(bad)} is not one of its columns")
            continue

        def put(
            doc_: Any, name: str = name, description: str = description, pii: List[str] = pii
        ) -> None:
            from ruamel.yaml.comments import CommentedMap

            entry = doc_.get(name)
            if entry is None or not isinstance(entry, dict):
                entry = CommentedMap()
                doc_[name] = entry
            if description and not entry.get("description"):
                entry.insert(0, "description", description)  # first, as entries are written
            if pii:
                metadata = entry.get("metadata")
                if metadata is None:
                    metadata = CommentedMap()
                    entry["metadata"] = metadata
                if not metadata.get("pii"):
                    metadata["pii"] = mapping(pii)

        edits.setdefault(facts.dataset_files[name], []).append(put)

    for pname, doc in (block.get("pipelines") or {}).items():
        if pname not in facts.pipelines:
            problems.append(f"Pipeline '{pname}' was not asked for")
            continue
        doc = doc if isinstance(doc, dict) else {"description": doc}
        raw_nodes = doc.get("nodes")
        nodes: Dict[str, Any] = raw_nodes if isinstance(raw_nodes, dict) else {}
        asked = facts.pipelines[pname].get("nodes") or {}
        stray = [n for n in nodes if n not in asked]
        if stray:
            problems.append(f"Pipeline '{pname}': nodes {', '.join(stray)} were not asked for")
            continue
        description = str(doc.get("description") or "").strip()

        def put_p(doc_: Any, description: str = description, nodes: Dict[str, Any] = nodes) -> None:
            if description and not doc_.get("description"):
                doc_.insert(0, "description", description)
            for n, text in nodes.items():
                spec: Any = (doc_.get("nodes") or {}).get(n)
                if hasattr(spec, "insert") and text and not spec.get("description"):
                    spec.insert(0, "description", str(text).strip())  # a CommentedMap

        edits.setdefault(facts.pipeline_files[pname], []).append(put_p)
    return edits, problems


def docs_assembler(root: Path, facts: DocsFacts) -> Callable[[ParsedAnswer], Assembled]:
    def assemble(answer: ParsedAnswer) -> Assembled:
        out = Assembled()
        block, why = _block(answer, "docs")
        if why:
            out.rejected.append(why)
            return out
        assert block is not None
        edits, problems = _docs_edits(block, facts)
        out.rejected += problems
        for rel, fns in edits.items():
            text = _read(root / rel) or ""

            def apply(doc: Any, fns: List[Callable[[Any], None]] = fns) -> None:
                for fn in fns:
                    fn(doc)

            new = edit_yaml(text, apply)
            if new != text:
                out.files[rel] = new
                out.base[rel] = _sha(text)
        if not out.files and not out.rejected:
            out.rejected.append("The proposal adds nothing: describe what was asked for")
        return out

    return assemble


def _docs_scope(facts: DocsFacts) -> Scope:
    return Scope(
        kind="proposal",
        editable=frozenset({*facts.dataset_files.values(), *facts.pipeline_files.values()}),
        purpose="docs",
    )


def propose_docs(
    root: Path,
    provider: LLMProvider,
    *,
    env: str = "dev",
    note: str = "",
    max_attempts: Optional[int] = None,
    on_attempt: Optional[Callable[..., None]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
) -> Draft:
    """A draft that adds the missing descriptions (and ``metadata.pii``) to the project."""
    root = Path(root).resolve()
    facts = docs_facts(root, env)
    if facts.empty:
        raise AIConfigError("Every dataset, pipeline and node already has a description")
    message = facts.render() + (f"\n\n# What the user says\n{note.strip()}" if note.strip() else "")
    draft = _run(
        root,
        provider,
        system=DOCS_PROMPT,
        first_message=message,
        scope=_docs_scope(facts),
        request=note.strip() or "Document the project",
        ctx=build_context(root),
        max_attempts=max_attempts,
        on_attempt=on_attempt,
        seen={rel: _sha(_read(root / rel)) for rel in _docs_scope(facts).editable},
        should_stop=should_stop,
        assembler=docs_assembler(root, facts),
        again=AGAIN_PROPOSAL,
    )
    draft.env = env
    return draft


# ── revising a proposal ─────────────────────────────────────────────────────


def proposal_setup(
    root: Path, draft: Draft
) -> Tuple[Scope, str, Callable[[ParsedAnswer], Assembled], str]:
    """What :func:`ducta.ai.builder.revise` needs to continue a proposal's conversation."""
    root = Path(root).resolve()
    if draft.kind == "quality":
        facts = quality_facts(root, draft.pipeline or "", draft.target or "", draft.env or "dev")
        system = QUALITY_PROMPT.format(
            checks="\n".join(f"- {name}: {shape}" for name, shape in QUALITY_CHECKS.items())
        )
        return _quality_scope(facts), system, quality_assembler(root, facts), AGAIN_PROPOSAL
    docs = docs_facts(root, draft.env or "dev")
    # What the draft documented is no longer missing once applied; keep asking the same.
    return _docs_scope(docs), DOCS_PROMPT, docs_assembler(root, docs), AGAIN_PROPOSAL
