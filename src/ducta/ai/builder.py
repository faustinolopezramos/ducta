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
"""

from __future__ import annotations

import difflib
import functools
import hashlib
import json
import os
import re
import shutil
import sys
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Dict, FrozenSet, List, Optional, Sequence, Set, Tuple

import yaml  # type: ignore[import-untyped]

from ducta.ai.context import (
    MAX_CHARS,
    SKIP_DIRS,
    ProjectContext,
    build_context,
    find_secrets,
    normalize_location,
    redact,
)
from ducta.ai.errors import (
    AICancelledError,
    AIConfigError,
    AIConflictError,
    AIEnvironmentError,
    AIError,
    AINotFoundError,
)
from ducta.ai.providers import ChatMessage, Completion, LLMProvider
from ducta.setting.project_loader import (
    CATALOG_DIR,
    PIPELINES_DIR,
    catalog_location,
    visible_in,
)

_BASE_PROMPT = """\
You are the pipeline builder of Ducta, a data-pipeline framework. You write \
format-2 project files that pass Ducta's validator on the first try.

## Format 2, in brief
A pipeline is one YAML file, `pipelines/<name>.yaml`; its name is the file stem.
```yaml
description: One line on what the pipeline does
requires_dates: false          # true only if node functions take start_date/end_date
depends_on: [other.pipeline]   # pipelines that must run first (the ones producing its inputs)
metadata: {tags: [silver]}     # recognised: owner, tags, sla, pii, criticality, docs
nodes:
  layer.node_name:             # unique across the whole project
    description: What this node does
    run: src.module:function   # module path : function name (in the project's code folder)
    inputs: {param_name: catalog.dataset.name}   # parameter of the function -> dataset it receives
    outputs: [catalog.dataset.name]              # what the function returns is written here
    after: [layer.other_node]  # only to order nodes that do not share a dataset
    quality:                   # optional checks on the output
      checks:
        row_count: {min: 1}
        null_rate: {columns: [id], threshold: 0.0}
      gate: {max_errors: 0}
```
An ingest node reads a table from a declared source, with no Python:
```yaml
  bronze.ingest_orders:
    kind: ingest
    ingest: {source: <source name>, table: dbo.orders}
    outputs: [bronze.sales.orders]
```
Every dataset a node reads or writes must be in the catalog. Datasets are \
named `<layer>.<schema>.<table>`; a catalog entry is
```yaml
silver.sales.orders_clean:
  format: parquet              # omit when a catalog default glob already gives one
  description: What a row is
```

## Node functions
A transform node's function takes one parameter per key of `inputs` (same names), \
plus `**kwargs`, and returns the DataFrame written to its single output. Use the \
same DataFrame library and style as the project's example function. Keep functions \
pure: no reads or writes of files, no connections, no prints.

## How to answer
Answer ONLY with fenced blocks, one per file, then at most three short lines \
explaining what you did. The info string names the file:
```yaml file=pipelines/<pipeline>.yaml
...
```
```yaml catalog
<only the NEW datasets, as a YAML mapping>
```
```python file=<code folder>/<module>.py
...
```
The request says which folder is the project's code folder ("Where code goes").
"""

NEW_RULES = """Rules:
- Create a NEW pipeline file with NEW node names. Never repeat, rewrite or move the \
project's existing nodes, pipelines, catalog entries or modules: reference what \
they produce through `inputs` and `depends_on`.
- Reuse existing datasets as inputs whenever they fit; never redeclare them.
- Put new functions in a NEW module in the project's code folder (e.g. \
`<code folder>/<pipeline_name_with_underscores>.py`); existing functions may be \
reused by `run:` as they are.
- Follow the project's naming conventions for nodes, datasets and pipelines.
- Write descriptions in the language of the request.
"""

FIX_RULES = """Rules — you are FIXING an existing pipeline:
- Answer with the COMPLETE corrected text of each file you change. Only the files \
listed as editable may change; leave every other file out of your answer.
- Change as little as possible. Keep node, dataset and pipeline names unless the \
name itself is the problem.
- New datasets go in a ```yaml catalog block; new helper functions may go in a NEW module.
- Explain the cause in one or two lines, in the language of the request.
"""

SYSTEM_PROMPT = _BASE_PROMPT + NEW_RULES
FIX_PROMPT = _BASE_PROMPT + FIX_RULES

_BLOCK = re.compile(
    r"^[ \t]*```(?P<lang>[\w+-]*)[ \t]*(?P<meta>[^\n`]*)\n" r"(?:(?P<body>.*?)\n)?[ \t]*```[ \t]*$",
    re.DOTALL | re.MULTILINE,
)
_FILE_META = re.compile(r"(?:file|path)\s*[=:]\s*[\"']?(?P<path>[^\s\"']+)")
_RUN = re.compile(r"run:\s*[\"']?([\w.]+):")
#: Python runs these on its own (pytest, site, packaging): a draft never adds one.
_AUTO_RUN = {"conftest.py", "sitecustomize.py", "usercustomize.py", "setup.py", "noxfile.py"}
#: What a new dataset's catalog entry may say. Where it lives (``path``,
#: ``table``) is checked apart: see :func:`_catalog_problems`.
_CATALOG_KEYS = {
    "format",
    "description",
    "schema",
    "metadata",
    "quality",
    "incremental",
    "options",
    "read",
    "write",
    "path",
    "table",
}
#: The most a fix may show the model of its editable files, in characters.
_MAX_EDITABLE_CHARS = 60_000


_STDLIB: FrozenSet[str] = frozenset(getattr(sys, "stdlib_module_names", ()))


@functools.lru_cache(maxsize=1)
def _installed() -> FrozenSet[str]:
    """Top-level names of the installed packages."""
    try:
        from importlib.metadata import packages_distributions

        return frozenset(packages_distributions())
    except Exception:  # noqa: BLE001 — without metadata, the standard library still counts
        return frozenset()


def _shadows(root: Path, p: PurePosixPath) -> Optional[str]:
    """The module a new file at *p* would hide on import, if any.

    A new top-level module or package would hide the standard library or an
    installed package of the same name; a module inside a package hides only
    the standard library (when that folder is on ``sys.path``).
    """
    top = p.parts[0] if len(p.parts) > 1 else p.stem
    if not (root / p.parts[0]).exists() and (top in _STDLIB or top in _installed()):
        return top
    if p.stem != "__init__" and p.stem in _STDLIB:
        return p.stem
    return None


def _clean_path(path: str) -> str:
    """A path as the model wrote it, without the ``./`` some models put in front."""
    while path.startswith("./"):
        path = path[2:]
    return path


# ── the model's answer ──────────────────────────────────────────────────────


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


def _sha(text: Optional[str]) -> Optional[str]:
    return None if text is None else hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read(path: Path) -> Optional[str]:
    return path.read_text(encoding="utf-8") if path.is_file() else None


def _is_pipeline(rel: str) -> bool:
    p = PurePosixPath(rel)
    # A module may live in pipelines/ too, when the project keeps its code there.
    return bool(p.parts) and p.parts[0] == PIPELINES_DIR and p.suffix != ".py"


def _outside(root: Path, rel: str) -> Optional[str]:
    """Why *rel* is not a file inside the project, or ``None``."""
    p = PurePosixPath(rel)
    if not p.parts or p.name in ("", "."):
        return f"'{rel}' is not a file path"
    if p.is_absolute() or ".." in p.parts:
        return f"{rel}: paths must be inside the project"
    # A symlinked folder must not lead out of the project either.
    if not (Path(root) / rel).resolve().is_relative_to(Path(root).resolve()):
        return f"{rel}: paths must be inside the project"
    return None


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


def _check_path(root: Path, rel: str, scope: Scope = NEW) -> Optional[str]:
    """Why *rel* may not be written by a draft, or ``None``."""
    why = _outside(root, rel)
    if why:
        return why
    p = PurePosixPath(rel)
    if rel in scope.editable:
        return None
    in_code_folder = p.suffix == ".py" and p.parts[0] == PIPELINES_DIR and _is_package(root, p)
    if p.parts[0] == PIPELINES_DIR and not in_code_folder:
        if scope.kind == "fix":
            return f"{rel}: only {', '.join(sorted(scope.editable))} may change in this fix"
        if len(p.parts) != 2 or p.suffix not in (".yaml", ".yml"):
            return f"{rel}: a pipeline file is pipelines/<name>.yaml"
    elif p.suffix == ".py":
        if any(part in SKIP_DIRS or part.startswith(".") for part in p.parts[:-1]):
            return f"{rel}: code goes in the project's code folder ({code_folder(root)}/)"
        if p.name in _AUTO_RUN:
            return f"{rel}: Python runs {p.name} on its own; put the code in a regular module"
        clash = _shadows(root, p)
        if clash:
            return (
                f"{rel}: '{clash}' is the name of a Python module the project imports "
                "(standard library or an installed package); choose another name"
            )
    else:
        return (
            f"{rel}: a draft may only add a pipeline file, Python modules and catalog "
            "entries (in a ```yaml catalog block)"
        )
    if (root / rel).exists():
        return f"{rel} already exists; create a new file with another name"
    return None


def _is_package(root: Path, p: PurePosixPath) -> bool:
    """Whether *p*'s folder is an existing Python package (so a module may go there)."""
    return len(p.parts) > 1 and (root.joinpath(*p.parts[:-1]) / "__init__.py").is_file()


def code_folder(root: Path) -> str:
    """Where the project keeps the code its nodes run: the folder most ``run:`` use."""
    from collections import Counter

    folders: "Counter[str]" = Counter()
    pipelines = root / PIPELINES_DIR
    files = (
        sorted(f for f in pipelines.rglob("*.y*ml") if visible_in(f, pipelines))
        if pipelines.is_dir()
        else []
    )
    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for module in _RUN.findall(text):
            parts = module.split(".")
            if len(parts) > 1 and all(parts):
                folders[parts[0]] += 1
    for folder, _ in folders.most_common():
        if (root / folder).is_dir():
            return folder
    return "src"


def where_code_goes(root: Path) -> str:
    """The prompt section that names the project's code folder."""
    folder = code_folder(root)
    return (
        "# Where code goes\n"
        f"New modules go in `{folder}/`, like the project's existing code: write "
        f"```python file={folder}/<module>.py and set `run: {folder}.<module>:<function>`."
    )


def _modules_run_by(root: Path, pipeline_text: str) -> Set[str]:
    """Project-relative ``.py`` paths a pipeline file's ``run:`` references name."""
    from ducta.api.services.code_index import module_file

    return {
        module_file(root, module).relative_to(root).as_posix()
        for module in _RUN.findall(pipeline_text)
        if all(module.split("."))  # not "src..m" nor ".m"
    }


def _new_modules(root: Path, answer: ParsedAnswer) -> Set[str]:
    """Modules the answer's pipeline runs that do not exist yet."""
    out: Set[str] = set()
    for rel, text in answer.files.items():
        if _is_pipeline(rel):
            out |= {m for m in _modules_run_by(root, text) if not (root / m).exists()}
    return out


def _place_unnamed(root: Path, answer: ParsedAnswer, scope: Scope = NEW) -> List[str]:
    """Give unnamed blocks the file their content implies; why not, for the rest."""
    problems: List[str] = []
    python: List[str] = []
    for lang, body in answer.unnamed:
        if lang in ("python", "py"):
            python.append(body)
            continue
        try:
            data = yaml.safe_load(body)
        except yaml.YAMLError:
            data = None
        if isinstance(data, dict) and isinstance(data.get("nodes"), dict) and data["nodes"]:
            if not any(_is_pipeline(r) for r in answer.files):
                own = sorted(r for r in scope.editable if _is_pipeline(r))
                first = next(iter(data["nodes"]))
                answer.files[own[0] if own else f"{PIPELINES_DIR}/{first}.yaml"] = body
            continue
        if isinstance(data, dict) and data and all("." in str(k) for k in data):
            answer.catalog = ((answer.catalog or "") + "\n" + body).strip() + "\n"
            continue
        problems.append(
            "A ```" + (lang or "") + " block has no file name: start every block with "
            "```yaml file=pipelines/<name>.yaml, ```yaml catalog or "
            f"```python file={code_folder(root)}/<module>.py"
        )
    if python:
        targets = sorted(_new_modules(root, answer)) or sorted(
            r for r in scope.editable if r.endswith(".py")
        )
        if len(targets) == 1:
            answer.files[targets[0]] = "\n\n".join(python)
        else:
            folder = code_folder(root)
            problems.append(
                "The Python block has no file name and the pipeline's `run:` does not point to "
                "exactly one NEW module. Put new functions in a new module, set `run: "
                f"{folder}.<new_module>:<function>`, and start the block with "
                f"```python file={folder}/<new_module>.py"
            )
    return problems


def assemble(
    root: Path, ctx: ProjectContext, answer: ParsedAnswer, scope: Scope = NEW
) -> Assembled:
    """The files a parsed answer amounts to, with everything not allowed rejected."""
    out = Assembled()
    out.rejected += _place_unnamed(root, answer, scope)
    pipeline = scope.pipeline or _pipeline_name(answer.files) or "ai_draft"
    for rel, text in answer.files.items():
        why = _check_path(root, rel, scope)
        if why:
            out.rejected.append(why)
        else:
            current = _read(root / rel)
            if rel in scope.editable and text == current:
                continue  # returned unchanged: not part of the draft
            out.files[rel] = text
            out.base[rel] = _sha(current)

    if scope.kind == "new":
        pipelines = [r for r in out.files if _is_pipeline(r)]
        if not pipelines:
            out.rejected.append("The answer has no ```yaml file=pipelines/<name>.yaml block")
        for extra in pipelines[1:]:
            del out.files[extra]
            out.rejected.append(
                f"{extra}: a draft is ONE new pipeline; put every node in {pipelines[0]}"
            )

    if answer.catalog:
        try:
            entries = yaml.safe_load(answer.catalog)
        except yaml.YAMLError as e:
            out.rejected.append(f"The catalog block is not valid YAML: {e}")
            return out
        if not isinstance(entries, dict):
            out.rejected.append("The catalog block must be a mapping of dataset name → entry")
            return out
        again = [name for name in entries if name in ctx.catalog]
        if again:
            out.rejected.append(f"Already in the catalog, do not redeclare: {', '.join(again)}")
        new = {k: v for k, v in entries.items() if k not in ctx.catalog}
        bad = _catalog_problems(new, _outputs_of(out.files), ctx.locations)
        out.rejected += bad.values()
        new = {k: v for k, v in new.items() if k not in bad}
        if new:
            out.new_datasets = list(new)
            rel, text, base = _catalog_with(root, new, pipeline)
            out.files[rel] = text
            out.base[rel] = base

    if scope.kind == "fix" and not out.files and not out.rejected:
        out.rejected.append("The answer changes nothing; return the corrected files")
    return out


def _outputs_of(files: Dict[str, str]) -> Set[str]:
    """Datasets the draft's pipeline files write."""
    out: Set[str] = set()
    for rel, text in files.items():
        if not _is_pipeline(rel):
            continue
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError:
            continue
        nodes = data.get("nodes") if isinstance(data, dict) else None
        for node in (nodes or {}).values() if isinstance(nodes, dict) else []:
            if isinstance(node, dict) and isinstance(node.get("outputs"), list):
                out |= {str(o) for o in node["outputs"]}
    return out


def _catalog_problems(
    entries: Dict[str, Any], outputs: Set[str], locations: Dict[str, str]
) -> Dict[str, str]:
    """Why each of these new catalog entries may not be added, by dataset name."""
    taken_paths = {k: v for k, v in locations.items() if not k.startswith("table:")}
    out: Dict[str, str] = {}
    for name, spec in entries.items():
        if not isinstance(spec, dict):
            out[name] = f"Catalog entry {name} must be a mapping (format, description, …)"
            continue
        unknown = sorted(set(spec) - _CATALOG_KEYS)
        if unknown:
            out[name] = f"Catalog entry {name}: unknown key(s) {', '.join(unknown)}"
            continue
        if spec.get("table") and f"table:{spec['table']}" in locations:
            other = locations[f"table:{spec['table']}"]
            out[name] = f"Catalog entry {name}: table {spec['table']} is already {other}; reuse it"
            continue
        if not spec.get("path"):
            continue
        path = normalize_location(spec["path"])
        clash = next(
            (
                other
                for where, other in taken_paths.items()
                if path == where or path.startswith(where + "/") or where.startswith(path + "/")
            ),
            None,
        )
        if clash:
            out[name] = (
                f"Catalog entry {name}: path {spec['path']} is where {clash} lives; reuse "
                f"{clash}, or give {name} its own path"
            )
        elif name in outputs and (
            PurePosixPath(path).is_absolute()
            or ".." in PurePosixPath(path).parts
            or re.match(r"^[a-zA-Z][\w+.-]*://", path)
        ):
            out[name] = (
                f"Catalog entry {name}: a dataset the pipeline writes needs a path inside the "
                "project (or none, for the conventional location) — not an absolute path, "
                "'..' or a URI"
            )
    return out


def _catalog_with(
    root: Path, entries: Dict[str, Any], pipeline: str
) -> Tuple[str, str, Optional[str]]:
    """Where new catalog entries go, that file's full text with them, and the hash it had."""
    addition = yaml.safe_dump(entries, sort_keys=False, allow_unicode=True, width=100)
    location = catalog_location(root)
    if location.is_dir() or location.name == CATALOG_DIR:
        target = root / CATALOG_DIR / f"{pipeline.replace('/', '_')}.yaml"
    else:
        target = location
    if target.suffix not in (".yaml", ".yml"):
        raise AIConfigError(
            f"The catalog is {target.name}; drafts can only append to a YAML catalog"
        )
    rel = target.relative_to(root).as_posix()
    header = f"# Added by `ducta ai` for pipeline {pipeline}\n"
    current = _read(target)
    if current is None:
        return rel, header + addition, None
    return rel, current.rstrip("\n") + "\n\n" + header + addition, _sha(current)


# ── drafts ──────────────────────────────────────────────────────────────────


@dataclass
class Attempt:
    number: int
    files: List[str]
    #: Errors the draft is responsible for (see :func:`_judge`).
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

    @property
    def errors(self) -> List[Dict[str, Any]]:
        return [p for p in self.problems if p.get("severity") == "error"]

    def diff(self, root: Path) -> str:
        chunks: List[str] = []
        for rel, text in self.files.items():
            before = _read(root / rel) or ""
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
        data["attempts"] = [Attempt(**a) for a in data.get("attempts") or []]
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items() if k in known})


_DRAFT_ID = re.compile(r"^[0-9A-Za-z-]{1,64}$")


def drafts_dir(root: Path) -> Path:
    return Path(root) / ".ducta" / "ai" / "drafts"


def save_draft(root: Path, draft: Draft) -> Path:
    path = drafts_dir(root) / f"{draft.id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(draft.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    return path


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
    if not _DRAFT_ID.match(draft_id):
        raise AIConfigError(f"'{draft_id}' is not a draft id")
    folder = drafts_dir(root)
    matches = sorted(folder.glob(f"{draft_id}*.json")) if folder.is_dir() else []
    if not matches:
        raise AINotFoundError(f"No draft '{draft_id}' in {folder}")
    if len(matches) > 1:
        raise AIConfigError(f"'{draft_id}' matches {len(matches)} drafts; give more of the id")
    return Draft.from_dict(json.loads(matches[0].read_text(encoding="utf-8")))


def delete_draft(root: Path, draft_id: str) -> None:
    draft = load_draft(root, draft_id)
    (drafts_dir(root) / f"{draft.id}.json").unlink()


def apply_draft(root: Path, draft: Draft, *, force: bool = False) -> List[str]:
    """Write *draft*'s files, refusing if any changed since the draft was made.

    Unless *force*, the draft must also validate against the project as it is
    now: other files may have changed since (a node or dataset of the same name).
    """
    root = Path(root).resolve()
    if draft.applied_at:
        raise AIConflictError(f"Draft {draft.id} was already applied at {draft.applied_at}")
    # The draft is a file on disk: check its paths again rather than trust it.
    unsafe = [why for why in (_outside(root, rel) for rel in draft.files) if why]
    if unsafe:
        raise AIConflictError(f"Draft {draft.id} cannot be applied: {'; '.join(unsafe)}")
    changed = [rel for rel, sha in draft.base.items() if _sha(_read(root / rel)) != sha]
    if changed:
        raise AIConflictError(
            f"These files changed after the draft was made: {', '.join(changed)}. "
            "Generate it again."
        )
    if not force:
        if not draft.ok:
            raise AIConfigError("The draft does not validate; force it to write it anyway")
        blocking = _recheck(root, draft)
        if blocking:
            raise AIConfigError(
                "The draft no longer validates against the project as it is now: "
                + "; ".join(_describe(p) for p in blocking[:5])
                + ". Revise it or generate it again (or force it)."
            )
    # Every file is written in full before any is replaced, so a failure (a full
    # disk, a read-only folder) leaves the project as it was.
    staged: List[Tuple[Path, Path]] = []
    try:
        for rel, text in draft.files.items():
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(f".{target.name}.{draft.id}.tmp")
            staged.append((tmp, target))
            tmp.write_text(text, encoding="utf-8")
            if target.exists():
                shutil.copymode(target, tmp)
    except OSError as e:
        for tmp, _ in staged:
            tmp.unlink(missing_ok=True)
        raise AIEnvironmentError(f"Could not write draft {draft.id}: {e}", cause=e) from e
    for tmp, target in staged:
        os.replace(tmp, target)
    draft.applied_at = _now()
    if (drafts_dir(root) / f"{draft.id}.json").exists():
        save_draft(root, draft)
    return list(draft.files)


def _recheck(root: Path, draft: Draft) -> List[Dict[str, Any]]:
    """The errors *draft* is responsible for, judged now."""
    if draft.kind == "fix":
        editable = frozenset(rel for rel in draft.files if draft.base.get(rel))
        scope = Scope(kind="fix", editable=editable, pipeline=draft.pipeline)
    else:
        scope = NEW
    baseline = {_key(p) for p in _validate(root, {}) if p.get("severity") == "error"}
    return _judge(_validate(root, draft.files), baseline, scope)


def _pipeline_name(files: Dict[str, str]) -> Optional[str]:
    for rel in files:
        if _is_pipeline(rel):
            return PurePosixPath(rel).stem
    return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── validation ──────────────────────────────────────────────────────────────


def _validate(root: Path, files: Dict[str, str]) -> List[Dict[str, Any]]:
    try:
        from ducta.api.repositories.v2_store import V2ProjectStore
        from ducta.api.services.draft_validation import validate_draft
    except ImportError as e:
        raise AIEnvironmentError(
            "Validating drafts needs Ducta's API extra: pip install 'ducta[api,ai]'"
        ) from e
    store = V2ProjectStore.detect(root)
    if store is None:
        raise AIConfigError(f"{root} is not a format-2 Ducta project (no ducta.yaml)")
    return [p.to_dict() for p in validate_draft(store, files)]


def _key(p: Dict[str, Any]) -> Tuple[Any, ...]:
    return (p.get("code"), p.get("file"), p.get("node"), p.get("message"))


def _concerns(p: Dict[str, Any], scope: Scope) -> bool:
    """Whether problem *p* is on the pipeline a fix is about."""
    if scope.kind != "fix":
        return False
    return p.get("pipeline") == scope.pipeline or p.get("file") in scope.editable


def _judge(
    problems: List[Dict[str, Any]], baseline: Set[Tuple[Any, ...]], scope: Scope
) -> List[Dict[str, Any]]:
    """The errors a draft is responsible for: new ones, and (a fix) those left on its pipeline."""
    return [
        p
        for p in problems
        if p.get("severity") == "error" and (_key(p) not in baseline or _concerns(p, scope))
    ]


#: How the model is asked to answer again, after problems or a change request.
AGAIN = "answer again with ALL the blocks (complete files, not just the changes)."


def _feedback(
    assembled: Assembled, blocking: List[Dict[str, Any]], truncated: bool, again: str = AGAIN
) -> str:
    lines = [f"Ducta's validator rejected the draft. Fix every point and {again}"]
    if truncated:
        lines.append("- Your answer was cut off by the output limit: be more concise.")
    lines += [f"- {r}" for r in assembled.rejected]
    lines += [f"- {_describe(p)}" for p in blocking]
    return "\n".join(lines)


def _describe(p: Dict[str, Any]) -> str:
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


def _run(
    root: Path,
    provider: LLMProvider,
    *,
    system: str,
    first_message: str,
    scope: Scope,
    request: str,
    ctx: ProjectContext,
    max_attempts: Optional[int],
    on_attempt: Optional[Callable[[Attempt], None]],
    prior: Sequence[ChatMessage] = (),
    seen: Optional[Dict[str, Optional[str]]] = None,
    current: Optional[List[Dict[str, Any]]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
    assembler: Optional[Callable[[ParsedAnswer], Assembled]] = None,
    again: str = AGAIN,
) -> Draft:
    """Ask, validate, send the problems back; *seen* hashes the files the prompt showed."""
    seen = dict(seen or {})
    if current is None:
        current = _validate(root, {})
    baseline = {_key(p) for p in current if p.get("severity") == "error"}
    attempts = max_attempts or provider.config.max_attempts
    messages = [ChatMessage("user", first_message), *prior]
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
        assembled = assembler(answer) if assembler else assemble(root, ctx, answer, scope)
        assembled.base.update({rel: sha for rel, sha in seen.items() if rel in assembled.files})
        problems = _validate(root, assembled.files) if assembled.files else []
        blocking = _judge(problems, baseline, scope)
        attempt = Attempt(
            number=number,
            files=list(assembled.files),
            errors=len(blocking),
            warnings=sum(1 for p in problems if p.get("severity") == "warning"),
            rejected=list(assembled.rejected),
            usage=completion.usage,
            messages=(list(assembled.rejected) + [_describe(p) for p in blocking])[:5],
        )
        history.append(attempt)
        if on_attempt:
            on_attempt(attempt)
        if assembled.files and not blocking and not assembled.rejected:
            break
        messages += [
            ChatMessage("assistant", completion.text),
            ChatMessage("user", _feedback(assembled, blocking, completion.truncated, again)),
        ]

    rejected = [{"severity": "error", "message": r, "source": "ai"} for r in assembled.rejected]
    return Draft(
        id=datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6],
        request=request,
        provider=provider.config.provider,
        model=(completion.model if completion else provider.config.model) or "",
        created_at=_now(),
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
    )


def generate(
    root: Path,
    request: str,
    provider: LLMProvider,
    *,
    max_attempts: Optional[int] = None,
    on_attempt: Optional[Callable[[Attempt], None]] = None,
    context: Optional[ProjectContext] = None,
    should_stop: Optional[Callable[[], bool]] = None,
) -> Draft:
    """A validated draft of a new pipeline for *request* — or the last one, with its problems."""
    root = Path(root).resolve()
    if not request.strip():
        raise AIConfigError("Describe the pipeline to build")
    ctx = context or build_context(root)
    if ctx.config_error:
        raise AIConfigError(
            "The project does not validate now, so a draft could not be checked: "
            f"{ctx.config_error}. Fix it first (`ducta ai fix <pipeline>` can help)."
        )
    return _run(
        root,
        provider,
        system=SYSTEM_PROMPT,
        first_message=f"{ctx.render()}\n\n{where_code_goes(root)}\n\n# Request\n{request.strip()}",
        scope=NEW,
        request=request.strip(),
        ctx=ctx,
        max_attempts=max_attempts,
        on_attempt=on_attempt,
        should_stop=should_stop,
    )


def _pipeline_file(root: Path, pipeline: str) -> Path:
    if not pipeline or "/" in pipeline or "\\" in pipeline:
        raise AINotFoundError(f"No pipeline '{pipeline}' in {root / PIPELINES_DIR}")
    for suffix in (".yaml", ".yml"):
        candidate = root / PIPELINES_DIR / f"{pipeline}{suffix}"
        if candidate.is_file():
            return candidate
    path: Optional[Path]
    try:
        from ducta.setting.project_loader import read_project

        path = read_project(root).pipeline_files.get(pipeline)
    except Exception:  # noqa: BLE001 — a project that does not parse has no index
        path = None
    if path is None or not path.is_file():
        raise AINotFoundError(f"No pipeline '{pipeline}' in {root / PIPELINES_DIR}")
    if not path.resolve().is_relative_to(Path(root).resolve()):
        raise AINotFoundError(f"No pipeline '{pipeline}' in {root / PIPELINES_DIR}")
    if path.suffix not in (".yaml", ".yml"):
        raise AIConfigError(f"{path.name}: only YAML pipeline files can be fixed")
    return path


def fix_scope(root: Path, pipeline: str) -> Scope:
    """The pipeline's file and the existing modules its nodes run."""
    root = Path(root).resolve()
    path = _pipeline_file(root, pipeline)
    modules = {
        m for m in _modules_run_by(root, path.read_text(encoding="utf-8")) if (root / m).is_file()
    }
    return Scope(
        kind="fix",
        editable=frozenset({path.relative_to(root).as_posix(), *modules}),
        pipeline=pipeline,
    )


def fix(
    root: Path,
    pipeline: str,
    provider: LLMProvider,
    *,
    note: str = "",
    error: str = "",
    max_attempts: Optional[int] = None,
    on_attempt: Optional[Callable[[Attempt], None]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
) -> Draft:
    """A draft that fixes *pipeline*: its validation problems, a run's *error*, or a *note*."""
    root = Path(root).resolve()
    scope = fix_scope(root, pipeline)
    problems = _validate(root, {})
    current = [p for p in problems if p.get("severity") == "error" and _concerns(p, scope)]
    if not current and not error.strip() and not note.strip():
        raise AIConfigError(
            f"Pipeline '{pipeline}' validates and no error or note was given: nothing to fix"
        )
    ctx = build_context(root)
    parts = [f"# Pipeline to fix: {pipeline}", "Editable files, as they are now:"]
    seen: Dict[str, Optional[str]] = {}
    for rel in sorted(scope.editable):
        lang = "python" if rel.endswith(".py") else "yaml"
        text = _read(root / rel)
        seen[rel] = _sha(text)
        found = find_secrets(text or "")
        if found and not provider.config.is_local:
            # The model answers with whole files: what it is not shown, it would
            # write back as "***" over the real value. So it is not sent at all.
            raise AIConfigError(
                f"{rel} contains what looks like a credential ({found[0]}). Move it to an "
                "environment variable or the source configuration before sending this file "
                f"to {provider.config.endpoint}, or use a local model."
            )
        parts.append(f"```{lang} file={rel}\n{(text or '').rstrip()}\n```")
    if current:
        parts.append(
            "# What the validator reports\n" + "\n".join(f"- {_describe(p)}" for p in current)
        )
    if error.strip():
        parts.append(
            "# The error a run of this pipeline failed with\n```\n"
            + redact(error.strip()[-6000:])
            + "\n```"
        )
    if note.strip():
        parts.append("# What the user says\n" + note.strip())
    # The files must go whole; the project context is what gives way to them.
    own = sum(len(x) + 2 for x in parts)
    if own > _MAX_EDITABLE_CHARS:
        raise AIConfigError(
            f"Pipeline '{pipeline}' and its modules are too large to send whole "
            f"({own:,} characters; the limit is {_MAX_EDITABLE_CHARS:,}). Split its modules "
            "or fix it by hand."
        )
    parts.insert(
        0, ctx.render(max(MAX_CHARS // 4, MAX_CHARS - own)) + "\n\n" + where_code_goes(root)
    )
    request = note.strip() or (f"Fix pipeline {pipeline}")
    return _run(
        root,
        provider,
        system=FIX_PROMPT,
        first_message="\n\n".join(parts),
        scope=scope,
        request=request,
        ctx=ctx,
        max_attempts=max_attempts,
        on_attempt=on_attempt,
        seen=seen,
        current=problems,
        should_stop=should_stop,
    )


def revise(
    root: Path,
    draft: Draft,
    note: str,
    provider: LLMProvider,
    *,
    max_attempts: Optional[int] = None,
    on_attempt: Optional[Callable[[Attempt], None]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
) -> Draft:
    """A new draft that asks for *note* on top of *draft* — the same conversation, continued."""
    root = Path(root).resolve()
    if not note.strip():
        raise AIConfigError("Say what to change")
    if draft.applied_at:
        raise AIConflictError(f"Draft {draft.id} was already applied; draft a new one instead")
    if not draft.prompt or not draft.raw_answer:
        raise AIConfigError(f"Draft {draft.id} predates revisions; generate it again")
    assembler: Optional[Callable[[ParsedAnswer], Assembled]] = None
    again = AGAIN
    if draft.kind == "fix":
        scope = fix_scope(root, draft.pipeline or "")
        system = FIX_PROMPT
    elif draft.kind in ("quality", "docs"):
        from ducta.ai.proposals import proposal_setup

        scope, system, assembler, again = proposal_setup(root, draft)
    else:
        scope, system = NEW, SYSTEM_PROMPT

    seen = draft.seen or {r: sha for r, sha in draft.base.items() if r in scope.editable}
    changed = sorted(rel for rel, sha in seen.items() if _sha(_read(root / rel)) != sha)
    if changed:
        raise AIConflictError(
            f"These files changed after draft {draft.id} was made: {', '.join(changed)}. "
            "Draft the fix again."
        )
    prior = [
        ChatMessage("assistant", draft.raw_answer),
        ChatMessage(
            "user",
            "# Change requested\n"
            + note.strip()
            + f"\n\nKeep everything else as it is, and {again}",
        ),
    ]
    revised = _run(
        root,
        provider,
        system=system,
        first_message=draft.prompt,
        scope=scope,
        request=f"{draft.request} — {note.strip()}",
        ctx=build_context(root),
        max_attempts=max_attempts,
        on_attempt=on_attempt,
        prior=prior,
        seen=seen,
        should_stop=should_stop,
        assembler=assembler,
        again=again,
    )
    revised.revision_of = draft.id
    revised.env = draft.env
    if draft.kind == "quality":
        from ducta.ai.proposals import quality_evidence

        revised.evidence = quality_evidence(root, revised)
    return revised
