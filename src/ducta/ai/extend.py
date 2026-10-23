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

New nodes for an existing pipeline: the model continues it, Ducta keeps the
rest as it is.

The model sees the pipeline's file and the modules its nodes run, whole, and
answers with them complete plus what it adds. :func:`existing_changes` —
without a model — compares the answer with the files as they are: every
existing node, every top-level key of the pipeline (``depends_on`` may only
grow) and every statement of the existing modules must be there unchanged.
What it finds goes back to the model like a validation error; ``apply_draft``
asks it again, so even a hand-edited draft cannot change an existing node. The
code it adds is held to Ducta's review (:func:`new_code_problems`: no I/O of
its own, no ``collect()``, no credential), as Architect's modules are.

The pipeline file in the draft is Ducta's: the new nodes (and new
``depends_on`` entries) are added to the file as it is, with
:func:`ducta.ai.yaml_edit.edit_yaml` — its comments and layout kept, so the
diff shows only what was added.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import yaml  # type: ignore[import-untyped]

from ducta.ai.builder import (
    _BASE_PROMPT,
    _MAX_EDITABLE_CHARS,
    _MIN_CONTEXT_CHARS,
    MAX_CHARS,
    Assembled,
    Attempt,
    Draft,
    ParsedAnswer,
    Scope,
    _is_pipeline,
    _read,
    _refuse_credentials,
    _run,
    _sha,
    _too_large,
    assemble,
    build_context,
    fix_scope,
    message_budget,
    where_code_goes,
)
from ducta.ai.errors import AIConfigError
from ducta.ai.providers import LLMProvider

EXTEND_RULES = """Rules — you are EXTENDING an existing pipeline with NEW nodes:
- Answer with the COMPLETE pipeline file: every existing node exactly as it is \
(same name, same keys, same values), plus the new nodes. Do not change the \
pipeline's other keys; you may only ADD pipelines to `depends_on`.
- New node names are unique in the whole project. New nodes may read any \
dataset of this pipeline or of the catalog.
- New functions go in a module this pipeline already runs (answer with that \
module COMPLETE, every existing function and import unchanged — you may add \
imports) or in a NEW module in the project's code folder.
- New datasets go in a ```yaml catalog block; never redeclare an existing one.
- Explain what you added in one or two lines, in the language of the request.
"""

EXTEND_PROMPT = _BASE_PROMPT + EXTEND_RULES
AGAIN_EXTEND = (
    "answer again with the COMPLETE pipeline file (existing nodes unchanged, plus the new "
    "ones) and every module you add to."
)


def extend_scope(root: Path, pipeline: str) -> Scope:
    """The pipeline's file and its modules may change — by additions only."""
    base = fix_scope(root, pipeline)
    return Scope(kind="fix", editable=base.editable, pipeline=pipeline, purpose="extend")


def _nodes(doc: Any) -> Dict[str, Any]:
    nodes = doc.get("nodes") if isinstance(doc, dict) else None
    return nodes if isinstance(nodes, dict) else {}


def _pipeline_changes(rel: str, before: str, after: str) -> Tuple[List[str], List[str]]:
    """What changed in an existing pipeline file, and the nodes it adds."""
    try:
        old = yaml.safe_load(before) or {}
        new = yaml.safe_load(after) or {}
    except yaml.YAMLError as e:
        return [f"{rel} is not valid YAML: {e}"], []
    if not isinstance(new, dict):
        return [f"{rel} must be a mapping with `nodes`"], []
    out: List[str] = []
    old_nodes, new_nodes = _nodes(old), _nodes(new)
    for name, spec in old_nodes.items():
        if name not in new_nodes:
            out.append(f"{rel}: node {name} is missing; keep every existing node as it is")
        elif new_nodes[name] != spec:
            out.append(f"{rel}: node {name} changed; keep existing nodes exactly as they are")
    for key in set(old) | set(new):
        if key == "nodes":
            continue
        if key == "depends_on":
            before_deps = set(old.get("depends_on") or [])
            after_deps = set(new.get("depends_on") or [])
            if not before_deps <= after_deps:
                out.append(f"{rel}: depends_on lost {', '.join(sorted(before_deps - after_deps))}")
        elif old.get(key) != new.get(key):
            out.append(f"{rel}: `{key}` changed; only new nodes (and depends_on) may be added")
    added = [n for n in new_nodes if n not in old_nodes]
    return out, added


def _statements(source: str) -> Optional[List[str]]:
    try:
        return [ast.dump(node) for node in ast.parse(source).body]
    except SyntaxError:
        return None


def _name_of(node: ast.stmt) -> str:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return f"{node.name}()" if not isinstance(node, ast.ClassDef) else f"class {node.name}"
    return "a statement at module level"


def _root_name(node: ast.AST) -> Optional[str]:
    """``a`` for ``a``, ``a.b`` and ``a[0].b``."""
    while isinstance(node, (ast.Attribute, ast.Subscript)):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _touched(node: ast.AST) -> Set[str]:
    """The names a top-level statement binds or mutates, apart from what a function or class
    body does inside itself: ``def f`` / ``class C`` bind their name, ``x = …`` / ``import y as x``
    bind ``x``, and ``x.attr = …`` / ``x[k] = …`` change the object ``x`` names."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {node.name}
    out: Set[str] = set()
    if isinstance(node, ast.Import):
        out |= {(a.asname or a.name.split(".")[0]) for a in node.names}
    elif isinstance(node, ast.ImportFrom):
        out |= {(a.asname or a.name) for a in node.names}
    elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
        out.add(node.id)
    elif isinstance(node, (ast.Attribute, ast.Subscript)) and isinstance(
        node.ctx, (ast.Store, ast.Del)
    ):
        root = _root_name(node)
        if root:
            out.add(root)
    for child in ast.iter_child_nodes(node):
        out |= _touched(child)
    return out


def _module_changes(rel: str, before: str, after: str) -> List[str]:
    """What changed in an existing module: every statement it had must still be there,
    and nothing added may bind or mutate a name the module already had (a later ``def``
    or assignment would replace the original when the module is imported)."""
    new_nodes: List[ast.stmt]
    try:
        new_nodes = ast.parse(after).body
        old_nodes = ast.parse(before).body
    except SyntaxError:
        return []  # not Python (the validator says so), or an existing module that does not parse
    old_dumps = [ast.dump(n) for n in old_nodes]
    out: List[str] = []
    # Statement by statement: each old one must be matched by one of the new.
    unmatched = [(ast.dump(n), n) for n in new_nodes]
    for node, dumped in zip(old_nodes, old_dumps):
        found = next((i for i, (d, _n) in enumerate(unmatched) if d == dumped), None)
        if found is None:
            out.append(
                f"{rel}: {_name_of(node)} changed or is missing; keep existing code as it is "
                "and add new functions"
            )
        else:
            del unmatched[found]
    added = [n for _d, n in unmatched]
    taken: Set[str] = set()
    for node in old_nodes:
        taken |= _touched(node)
    taken.discard("__all__")
    known_imports = set(old_dumps)
    for node in added:
        if isinstance(node, (ast.Import, ast.ImportFrom)) and ast.dump(node) in known_imports:
            continue  # the same import again
        clash = sorted(_touched(node) & taken)
        if clash:
            out.append(
                f"{rel}: {', '.join(clash)} already exist{'s' if len(clash) == 1 else ''} in this "
                "module and the draft binds or changes "
                f"{'it' if len(clash) == 1 else 'them'} again; keep existing code as it is and "
                "give new functions and constants new names"
            )
    return out


def existing_changes(root: Path, pipeline: str, files: Dict[str, str]) -> List[str]:
    """Why *files* are not a pure extension of *pipeline* (empty: they are)."""
    root = Path(root).resolve()
    scope = extend_scope(root, pipeline)
    out: List[str] = []
    added: List[str] = []
    pipeline_rel = next((r for r in scope.editable if _is_pipeline(r)), None)
    for rel, text in files.items():
        if rel not in scope.editable:
            continue
        before = _read(root / rel) or ""
        if rel == pipeline_rel:
            problems, added = _pipeline_changes(rel, before, text)
            out += problems
        elif rel.endswith(".py"):
            out += _module_changes(rel, before, text)
    if pipeline_rel and pipeline_rel not in files and not out:
        out.append(f"The answer has no ```yaml file={pipeline_rel} block with the new nodes")
    elif pipeline_rel in files and not added and not out:
        out.append(f"{pipeline_rel}: no new node; add at least one")
    return out


def new_code_problems(root: Path, files: Dict[str, str]) -> List[str]:
    """What Ducta's review flags (I/O, ``collect()``, credentials) in the code the draft adds."""
    from ducta.ai.review import ReviewFacts, _code_findings

    out: List[str] = []
    for rel, text in files.items():
        if not rel.endswith(".py"):
            continue
        old_source = _read(root / rel) or ""
        before = set(_statements(old_source) or [])
        # A line the file already had is not the draft's: a fix that touches a function
        # which reads a file does not have to take that read out.
        old_lines = {line.strip() for line in old_source.splitlines()}
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue  # the validator says so
        lines = text.splitlines()
        for node in tree.body:
            if ast.dump(node) in before:
                continue  # was there already
            first = node.lineno
            last = getattr(node, "end_lineno", None) or first
            facts = ReviewFacts("", "", "", "dev", {}, {}, {})
            facts.function = {"file": rel, "line": first, "function": ""}
            facts.code_lines = lines[first - 1 : last]
            out += [
                f"{rel}:{f.line or first}: {f.title} — {f.suggestion}"
                for f in _code_findings(facts)
                if not (f.code and f.code in old_lines)
            ]
    return out


def extension_summary(root: Path, draft: Draft) -> Dict[str, Any]:
    """What an extension adds, read from its files: nodes (with what they read and
    write), functions and datasets — for the person reviewing it."""
    root = Path(root).resolve()
    nodes: List[Dict[str, Any]] = []
    functions: List[str] = []
    for rel, text in draft.files.items():
        if _is_pipeline(rel):
            try:
                old = _nodes(yaml.safe_load(_read(root / rel) or "") or {})
                new = _nodes(yaml.safe_load(text) or {})
            except yaml.YAMLError:
                continue
            for name, spec in new.items():
                if name in old or not isinstance(spec, dict):
                    continue
                inputs = spec.get("inputs") or {}
                nodes.append(
                    {
                        "name": str(name),
                        "inputs": [
                            str(v)
                            for v in (inputs.values() if isinstance(inputs, dict) else inputs)
                        ],
                        "outputs": [str(o) for o in spec.get("outputs") or []],
                        "description": str(spec.get("description") or ""),
                    }
                )
        elif rel.endswith(".py"):
            before = {n.name for n in _top_level_functions(_read(root / rel) or "")}
            functions += [
                f"{rel}: {n.name}()" for n in _top_level_functions(text) if n.name not in before
            ]
    return {"nodes": nodes, "functions": functions, "datasets": list(draft.new_datasets)}


def _top_level_functions(source: str) -> List[ast.FunctionDef]:
    try:
        return [n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)]
    except SyntaxError:
        return []


def _with_additions(before: str, after: str) -> str:
    """*before* with the nodes and ``depends_on`` entries *after* adds — nothing else touched."""
    from ducta.ai.yaml_edit import edit_yaml, mapping

    old, new = yaml.safe_load(before) or {}, yaml.safe_load(after) or {}
    added = {k: v for k, v in _nodes(new).items() if k not in _nodes(old)}
    deps = [d for d in new.get("depends_on") or [] if d not in (old.get("depends_on") or [])]

    def edit(doc: Any) -> None:
        if deps:
            if doc.get("depends_on") is None:
                doc["depends_on"] = mapping(list(deps))
            else:
                doc["depends_on"].extend(deps)
        if doc.get("nodes") is None:
            doc["nodes"] = mapping({})
        for name, spec in added.items():
            doc["nodes"][name] = mapping(spec)

    return edit_yaml(before, edit)


def extend_assembler(root: Path, ctx: Any, scope: Scope) -> Callable[[ParsedAnswer], Assembled]:
    """The usual assembly, then :func:`existing_changes` on what it amounts to."""

    def assemble_extension(answer: ParsedAnswer) -> Assembled:
        out = assemble(root, ctx, answer, scope)
        changes = existing_changes(root, scope.pipeline or "", out.files)
        out.rejected += changes + new_code_problems(root, out.files)
        if not changes:
            for rel in [r for r in out.files if _is_pipeline(r) and r in scope.editable]:
                out.files[rel] = _with_additions(_read(root / rel) or "", out.files[rel])
        return out

    return assemble_extension


def extend(
    root: Path,
    pipeline: str,
    request: str,
    provider: LLMProvider,
    *,
    max_attempts: Optional[int] = None,
    on_attempt: Optional[Callable[[Attempt], None]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
) -> Draft:
    """A draft (kind ``extend``) that adds what *request* asks for to *pipeline*."""
    root = Path(root).resolve()
    if not request.strip():
        raise AIConfigError("Say what the new nodes should do")
    scope = extend_scope(root, pipeline)
    ctx = build_context(root)
    if ctx.config_error:
        raise AIConfigError(
            f"The project does not validate now, so new nodes could not be checked: "
            f"{ctx.config_error}. Fix it first (`ducta ai fix {pipeline}` can help)."
        )
    parts = [f"# Pipeline to extend: {pipeline}", "Its files, as they are now:"]
    seen: Dict[str, Optional[str]] = {}
    for rel in sorted(scope.editable):
        lang = "python" if rel.endswith(".py") else "yaml"
        text = _read(root / rel)
        seen[rel] = _sha(text)
        _refuse_credentials(rel, text, provider)
        parts.append(f"```{lang} file={rel}\n{(text or '').rstrip()}\n```")
    parts.append("# What to add\n" + request.strip())
    own = sum(len(x) + 2 for x in parts)
    if own > _MAX_EDITABLE_CHARS:
        raise AIConfigError(
            f"Pipeline '{pipeline}' and its modules are too large to send whole "
            f"({own:,} characters; the limit is {_MAX_EDITABLE_CHARS:,}). Add the nodes in a "
            "new pipeline that reads its outputs (`ducta ai new`)."
        )
    where = "\n\n" + where_code_goes(root)
    room = max(_MIN_CONTEXT_CHARS, MAX_CHARS - own)
    budget = message_budget(provider.config, EXTEND_PROMPT)
    if budget is not None:
        room = min(room, budget - own - len(where) - 2)
        if room < _MIN_CONTEXT_CHARS:
            raise _too_large(provider.config, own + _MIN_CONTEXT_CHARS)
    parts.insert(0, ctx.render(room) + where)
    return _run(
        root,
        provider,
        system=EXTEND_PROMPT,
        first_message="\n\n".join(parts),
        scope=scope,
        request=request.strip(),
        ctx=ctx,
        max_attempts=max_attempts,
        on_attempt=on_attempt,
        seen=seen,
        should_stop=should_stop,
        assembler=extend_assembler(root, ctx, scope),
        again=AGAIN_EXTEND,
    )


def extend_setup(
    root: Path, draft: Draft
) -> Tuple[Scope, str, Callable[[ParsedAnswer], Assembled], str]:
    """What :func:`ducta.ai.builder.revise` needs to continue an extension's conversation."""
    scope = extend_scope(root, draft.pipeline or "")
    return scope, EXTEND_PROMPT, extend_assembler(root, build_context(root), scope), AGAIN_EXTEND


__all__ = [
    "EXTEND_PROMPT",
    "existing_changes",
    "extend",
    "extend_scope",
    "extend_setup",
    "extension_summary",
    "new_code_problems",
]
