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

import functools
import os
import re
import shutil
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Dict, FrozenSet, List, Optional, Set, Tuple

import yaml  # type: ignore[import-untyped]

from ducta.ai.context import (
    MAX_CHARS,
    SKIP_DIRS,
    ProjectContext,
    build_context,
    find_secrets,
    is_yaml_file,
    normalize_location,
    redact,
)
from ducta.ai.drafts import (
    Attempt,
    Draft,
    delete_draft,
    drafts_dir,
    list_drafts,
    load_draft,
    read_text,
    save_draft,
    text_sha,
    utc_now,
)
from ducta.ai.errors import AIConfigError, AIConflictError, AIEnvironmentError, AINotFoundError
from ducta.ai.loop import (
    AGAIN,
    MIN_CONTEXT_CHARS,
    NEW,
    Assembled,
    ParsedAnswer,
    Scope,
    concerns,
    describe_problem,
    judge_problems,
    message_budget,
    parse_answer,
    problem_key,
    run_loop,
    too_large,
    validate_files,
)
from ducta.ai.providers import ChatMessage, LLMProvider
from ducta.setting.project.loader import (
    CATALOG_DIR,
    PIPELINES_DIR,
    catalog_location,
    visible_in,
)

BASE_PROMPT = """\
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

SYSTEM_PROMPT = BASE_PROMPT + NEW_RULES
FIX_PROMPT = BASE_PROMPT + FIX_RULES

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
MAX_EDITABLE_CHARS = 60_000


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


def is_pipeline_file(rel: str) -> bool:
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
    from ducta.project_store.code_index import module_file

    return {
        module_file(root, module).relative_to(root).as_posix()
        for module in _RUN.findall(pipeline_text)
        if all(module.split("."))  # not "src..m" nor ".m"
    }


def _new_modules(root: Path, answer: ParsedAnswer) -> Set[str]:
    """Modules the answer's pipeline runs that do not exist yet."""
    out: Set[str] = set()
    for rel, text in answer.files.items():
        if is_pipeline_file(rel):
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
            if not any(is_pipeline_file(r) for r in answer.files):
                own = sorted(r for r in scope.editable if is_pipeline_file(r))
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
            current = read_text(root / rel)
            if rel in scope.editable and text == current:
                continue  # returned unchanged: not part of the draft
            out.files[rel] = text
            out.base[rel] = text_sha(current)

    if scope.kind == "new":
        pipelines = [r for r in out.files if is_pipeline_file(r)]
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
            rel, text, base = catalog_with(root, new, pipeline)
            out.files[rel] = text
            out.base[rel] = base

    if scope.kind == "fix" and not out.files and not out.rejected:
        out.rejected.append("The answer changes nothing; return the corrected files")
    return out


def default_assembler(
    root: Path, ctx: ProjectContext, scope: Scope
) -> Callable[[ParsedAnswer], Assembled]:
    """How ``new`` and ``fix`` answers become a draft: :func:`assemble`, plus the code review.

    The code the draft adds is held to the same review as an extension's or
    Architect's (what was already in a file is not the draft's).
    """
    from ducta.ai.extend import new_code_problems

    def assembler(answer: ParsedAnswer) -> Assembled:
        assembled = assemble(root, ctx, answer, scope)
        assembled.rejected += new_code_problems(root, assembled.files)
        return assembled

    return assembler


def _outputs_of(files: Dict[str, str]) -> Set[str]:
    """Datasets the draft's pipeline files write."""
    out: Set[str] = set()
    for rel, text in files.items():
        if not is_pipeline_file(rel):
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


def catalog_with(
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
    current = read_text(target)
    if current is None:
        return rel, header + addition, None
    return rel, current.rstrip("\n") + "\n\n" + header + addition, text_sha(current)


def apply_draft(root: Path, draft: Draft, *, force: bool = False) -> List[str]:
    """Write *draft*'s files, refusing if any changed since the draft was made.

    Unless *force*, the draft must also validate against the project as it is
    now: other files may have changed since (a node or dataset of the same name).
    """
    root = Path(root).resolve()
    if draft.applied_at:
        raise AIConflictError(f"Draft {draft.id} was already applied at {draft.applied_at}")
    if draft.kind == "blueprint":
        # Its modules are stubs: what is applied is what `architect build` makes of it.
        raise AIConflictError(
            f"Draft {draft.id} is a blueprint: build it first (`ducta ai architect build "
            f"{draft.id}`), then apply that draft"
        )
    # The draft is a file on disk anyone could edit: hold its paths to the rules
    # a draft of its kind was made under, rather than trust them.
    unsafe = _unwritable(root, draft)
    if not unsafe and draft.kind == "extend":
        # New nodes only: asked again of the files as they are, even with force.
        from ducta.ai.extend import existing_changes

        unsafe = existing_changes(root, draft.pipeline or "", draft.files)
    if unsafe:
        raise AIConflictError(f"Draft {draft.id} cannot be applied: {'; '.join(unsafe[:5])}")
    changed = [rel for rel, sha in draft.base.items() if text_sha(read_text(root / rel)) != sha]
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
                + "; ".join(describe_problem(p) for p in blocking[:5])
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
    try:
        for tmp, target in staged:
            os.replace(tmp, target)
    except OSError as e:
        for tmp, _ in staged:
            tmp.unlink(missing_ok=True)
        raise AIEnvironmentError(f"Could not write draft {draft.id}: {e}", cause=e) from e
    draft.applied_at = utc_now()
    if (drafts_dir(root) / f"{draft.id}.json").exists():
        save_draft(root, draft)
    return list(draft.files)


def _is_catalog_target(root: Path, rel: str) -> bool:
    """Whether *rel* is where :func:`catalog_with` puts new catalog entries."""
    location = catalog_location(root)
    if location.is_dir() or location.name == CATALOG_DIR:
        p = PurePosixPath(rel)
        return len(p.parts) == 2 and p.parts[0] == CATALOG_DIR and is_yaml_file(rel)
    try:
        return rel == location.relative_to(root).as_posix()
    except ValueError:
        return False


def _apply_scope(root: Path, draft: Draft) -> Scope:
    """What a draft of *draft*'s kind may touch, worked out again from the project."""
    if draft.kind == "fix":
        return fix_scope(root, draft.pipeline or "")
    if draft.kind == "extend":
        from ducta.ai.extend import extend_scope

        return extend_scope(root, draft.pipeline or "")
    if draft.kind == "quality":
        rel = find_pipeline_file(root, draft.pipeline or "").relative_to(root).as_posix()
        return Scope(kind="proposal", editable=frozenset({rel}), purpose="quality")
    if draft.kind == "docs":
        from ducta.setting.project.loader import read_project

        located = read_project(root, expand=False)
        files = {*located.catalog_files.values(), *located.pipeline_files.values()}
        return Scope(
            kind="proposal",
            editable=frozenset(
                f.relative_to(root).as_posix() for f in files if is_yaml_file(f.name)
            ),
            purpose="docs",
        )
    # ``new`` and ``architect`` (several new pipelines from a blueprint) only add.
    return NEW


def _unwritable(root: Path, draft: Draft) -> List[str]:
    """Why each of *draft*'s files may not be written, if any may not."""
    try:
        scope = _apply_scope(root, draft)
    except Exception as e:  # noqa: BLE001 — the pipeline is gone, the project does not load
        return [f"what it may change cannot be worked out now ({e})"]
    out: List[str] = []
    for rel in draft.files:
        why: Optional[str]
        if rel not in draft.base:
            # Without it, "changed since the draft was made" cannot be checked.
            why = f"{rel}: the draft does not record the file it was made from"
        elif scope.kind == "proposal":
            why = _outside(root, rel) or (
                None
                if rel in scope.editable
                else f"{rel}: a {draft.kind} draft only edits the project's YAML files"
            )
        elif _is_catalog_target(root, rel):
            why = _outside(root, rel)
        else:
            why = _check_path(root, rel, scope)
        if why:
            out.append(why)
    return out


def _recheck(root: Path, draft: Draft) -> List[Dict[str, Any]]:
    """The errors *draft* is responsible for, judged now."""
    if draft.kind == "fix":
        editable = frozenset(rel for rel in draft.files if draft.base.get(rel))
        scope = Scope(kind="fix", editable=editable, pipeline=draft.pipeline)
    else:
        scope = NEW
    baseline = {problem_key(p) for p in validate_files(root, {}) if p.get("severity") == "error"}
    return judge_problems(validate_files(root, draft.files), baseline, scope)


def _pipeline_name(files: Dict[str, str]) -> Optional[str]:
    for rel in files:
        if is_pipeline_file(rel):
            return PurePosixPath(rel).stem
    return None


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
    tail = f"\n\n{where_code_goes(root)}\n\n# Request\n{request.strip()}"
    room = MAX_CHARS
    budget = message_budget(provider.config, SYSTEM_PROMPT)
    if budget is not None:
        # The project's context is what gives way to a small window.
        room = min(room, budget - len(tail))
        if room < MIN_CONTEXT_CHARS:
            raise too_large(provider.config, MIN_CONTEXT_CHARS + len(tail))
    return run_loop(
        root,
        provider,
        system=SYSTEM_PROMPT,
        first_message=ctx.render(room) + tail,
        scope=NEW,
        request=request.strip(),
        assembler=default_assembler(root, ctx, NEW),
        max_attempts=max_attempts,
        on_attempt=on_attempt,
        should_stop=should_stop,
    )


def find_pipeline_file(root: Path, pipeline: str) -> Path:
    if not pipeline or "/" in pipeline or "\\" in pipeline:
        raise AINotFoundError(f"No pipeline '{pipeline}' in {root / PIPELINES_DIR}")
    for suffix in (".yaml", ".yml"):
        candidate = root / PIPELINES_DIR / f"{pipeline}{suffix}"
        if candidate.is_file():
            return candidate
    path: Optional[Path]
    try:
        from ducta.setting.project.loader import read_project

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
    path = find_pipeline_file(root, pipeline)
    modules = {
        m for m in _modules_run_by(root, path.read_text(encoding="utf-8")) if (root / m).is_file()
    }
    return Scope(
        kind="fix",
        editable=frozenset({path.relative_to(root).as_posix(), *modules}),
        pipeline=pipeline,
    )


def refuse_credentials(rel: str, text: Optional[str], provider: LLMProvider) -> None:
    """Raise when *rel*, sent whole, would hand a remote model a credential.

    The model answers with whole files: what it is not shown, it would write
    back as ``***`` over the real value. So such a file is not sent at all.
    """
    if provider.config.is_local:
        return
    found = find_secrets(text or "", yaml=is_yaml_file(rel))
    if found:
        raise AIConfigError(
            f"{rel} contains what looks like a credential ({found[0]}). Move it to an "
            "environment variable or the source configuration before sending this file "
            f"to {provider.config.endpoint}, or use a local model."
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
    problems = validate_files(root, {})
    current = [p for p in problems if p.get("severity") == "error" and concerns(p, scope)]
    if not current and not error.strip() and not note.strip():
        raise AIConfigError(
            f"Pipeline '{pipeline}' validates and no error or note was given: nothing to fix"
        )
    ctx = build_context(root)
    parts = [f"# Pipeline to fix: {pipeline}", "Editable files, as they are now:"]
    seen: Dict[str, Optional[str]] = {}
    for rel in sorted(scope.editable):
        lang = "python" if rel.endswith(".py") else "yaml"
        text = read_text(root / rel)
        seen[rel] = text_sha(text)
        refuse_credentials(rel, text, provider)
        parts.append(f"```{lang} file={rel}\n{(text or '').rstrip()}\n```")
    if current:
        parts.append(
            "# What the validator reports\n"
            + "\n".join(f"- {describe_problem(p)}" for p in current)
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
    if own > MAX_EDITABLE_CHARS:
        raise AIConfigError(
            f"Pipeline '{pipeline}' and its modules are too large to send whole "
            f"({own:,} characters; the limit is {MAX_EDITABLE_CHARS:,}). Split its modules "
            "or fix it by hand."
        )
    where = "\n\n" + where_code_goes(root)
    room = max(MIN_CONTEXT_CHARS, MAX_CHARS - own)
    budget = message_budget(provider.config, FIX_PROMPT)
    if budget is not None:
        room = min(room, budget - own - len(where) - 2)
        if room < MIN_CONTEXT_CHARS:
            raise too_large(provider.config, own + MIN_CONTEXT_CHARS)
    parts.insert(0, ctx.render(room) + where)
    request = note.strip() or (f"Fix pipeline {pipeline}")
    return run_loop(
        root,
        provider,
        system=FIX_PROMPT,
        first_message="\n\n".join(parts),
        scope=scope,
        request=request,
        assembler=default_assembler(root, ctx, scope),
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
    if draft.kind == "architect":
        # Built module by module from a blueprint: there is no one conversation to continue.
        raise AIConfigError(
            f"Draft {draft.id} was built from blueprint {draft.target or '?'}: revise the "
            "blueprint (`ducta ai revise <blueprint>`), then build it again"
        )
    if not draft.prompt or not draft.raw_answer:
        raise AIConfigError(f"Draft {draft.id} predates revisions; generate it again")
    assembler: Optional[Callable[[ParsedAnswer], Assembled]] = None
    again = AGAIN
    if draft.kind == "fix":
        scope = fix_scope(root, draft.pipeline or "")
        system = FIX_PROMPT
    elif draft.kind == "extend":
        from ducta.ai.extend import extend_setup

        scope, system, assembler, again = extend_setup(root, draft)
    elif draft.kind in ("quality", "docs"):
        from ducta.ai.proposals import proposal_setup

        scope, system, assembler, again = proposal_setup(root, draft)
    elif draft.kind == "blueprint":
        from ducta.ai.agents.architect.design import blueprint_setup

        scope, system, assembler, again = blueprint_setup(root, draft)
    else:
        scope, system = NEW, SYSTEM_PROMPT

    seen = draft.seen or {r: sha for r, sha in draft.base.items() if r in scope.editable}
    changed = sorted(rel for rel, sha in seen.items() if text_sha(read_text(root / rel)) != sha)
    if changed:
        raise AIConflictError(
            f"These files changed after draft {draft.id} was made: {', '.join(changed)}. "
            "Draft the fix again."
        )
    # A fix's (or an extension's) prompt holds its files whole and is re-sent as it
    # was made: drafted with a local model, a file may hold a credential this
    # provider must not get.
    if draft.kind in ("fix", "extend"):
        for rel in sorted(seen):
            refuse_credentials(rel, read_text(root / rel), provider)
    prior = [
        ChatMessage("assistant", draft.raw_answer),
        ChatMessage(
            "user",
            "# Change requested\n"
            + note.strip()
            + f"\n\nKeep everything else as it is, and {again}",
        ),
    ]
    revised = run_loop(
        root,
        provider,
        system=system,
        first_message=draft.prompt,
        scope=scope,
        request=f"{draft.request} — {note.strip()}",
        assembler=assembler or default_assembler(root, build_context(root), scope),
        max_attempts=max_attempts,
        on_attempt=on_attempt,
        prior=prior,
        seen=seen,
        should_stop=should_stop,
        again=again,
    )
    revised.revision_of = draft.id
    revised.env = draft.env
    if draft.kind == "quality":
        from ducta.ai.proposals import quality_evidence

        revised.evidence = quality_evidence(root, revised)
    return revised


#: The drafting API. Drafts and the loop live in :mod:`ducta.ai.drafts` and
#: :mod:`ducta.ai.loop`; their public names are re-exported here, where the
#: documentation has always pointed.
__all__ = [
    "NEW",
    "Attempt",
    "Draft",
    "Scope",
    "apply_draft",
    "assemble",
    "code_folder",
    "default_assembler",
    "delete_draft",
    "fix",
    "fix_scope",
    "generate",
    "list_drafts",
    "load_draft",
    "parse_answer",
    "revise",
    "save_draft",
    "where_code_goes",
]
