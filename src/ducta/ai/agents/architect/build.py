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

Ducta Architect, step two: a blueprint built into one draft.

Ducta writes every YAML file from the blueprint itself (:func:`render`); the
model writes only the bodies of the functions, one pipeline's module per
request, in dependency order — small enough for a local model's window. A
module is accepted only with exactly the functions and parameters the
blueprint implies, and without what Ducta's own review flags anywhere in it —
helpers and module-level code included (I/O of its own, ``collect()``, a
credential); then the whole project is validated with it.
"""

from __future__ import annotations

import ast
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ducta.ai.agents.architect.blueprint import (
    Blueprint,
    Existing,
    PipelineSpec,
    check_blueprint,
    is_stub,
    module_path,
    render,
)
from ducta.ai.builder import (
    NEW,
    Assembled,
    Attempt,
    Draft,
    ParsedAnswer,
    Scope,
    _judge,
    _key,
    _now,
    _run,
    _validate,
    build_context,
)
from ducta.ai.errors import AIConfigError, AIConflictError
from ducta.ai.providers import LLMProvider

BUILD_PROMPT = """\
You write the Python functions of ONE pipeline that Ducta Architect designed. \
Ducta already wrote the pipeline's YAML and catalog entries; you write only \
the module its nodes run.

Answer with ONE fenced block holding the COMPLETE module, then at most three \
short lines:
```python file=<the module path you are given>
...
```
Rules:
- Define every function listed, with EXACTLY the signature given (same names, \
in the same order, ending with **kwargs). Each returns the DataFrame written to \
its output. Private helpers (names starting with _) are fine.
- Implement the logic as written; make the output have the listed columns.
- Use the same DataFrame library and style as the project's example function.
- Pure functions: no reads or writes of files or tables, no connections, no \
collect()/toPandas(), no prints, no credentials.
"""

AGAIN_MODULE = "answer again with the complete module block."


def _columns(bp: Blueprint, dataset: str) -> str:
    spec = bp.datasets.get(dataset)
    if spec is None or not spec.columns:
        return ""
    cols = ", ".join(f"{c} {t}" for c, t in spec.columns.items())
    keys = f"; keys: {', '.join(spec.keys)}" if spec.keys else ""
    return f" — columns: {cols}{keys}"


def signature(pipe: PipelineSpec, node: Any) -> str:
    params = list(node.inputs) + (["start_date", "end_date"] if pipe.requires_dates else [])
    return f"def {node.function}({', '.join(params + ['**kwargs'])})"


def module_request(root: Path, bp: Blueprint, pipe: PipelineSpec, rel: str, ctx: Any) -> str:
    """What the model is told to write one pipeline's module."""
    parts = [
        f"# Blueprint {bp.name}: {bp.goal}".rstrip(": "),
        f"# Pipeline {pipe.name}" + (f" — {pipe.description}" if pipe.description else ""),
        f"Write the module `{rel}` with these functions:",
    ]
    for node in pipe.nodes.values():
        if node.kind != "transform":
            continue
        lines = [f"## `{signature(pipe, node)}`"]
        if node.description:
            lines.append(node.description)
        if node.logic:
            lines.append(f"Logic: {node.logic}")
        for param, ds in node.inputs.items():
            lines.append(f"- `{param}` receives {ds}{_columns(bp, ds)}")
        for out in node.outputs:
            lines.append(f"- returns {out}{_columns(bp, out)}")
        parts.append("\n".join(lines))
    if bp.assumptions:
        parts.append("# Assumptions\n" + "\n".join(f"- {a}" for a in bp.assumptions))
    if ctx.example_function:
        if "pyspark" in ctx.example_function:
            parts.append(
                "# DataFrame library\nNode functions take and return PySpark DataFrames "
                "(pyspark.sql). Do not use pandas."
            )
        parts.append(
            "# Example node function from this project (house style)\n```python\n"
            + ctx.example_function
            + "\n```"
        )
    return "\n\n".join(parts)


def module_problems(source: str, rel: str, pipe: PipelineSpec) -> List[str]:
    """Why a module the model wrote for *pipe* is not accepted (empty: accepted)."""
    from ducta.ai.review import ReviewFacts, _code_findings

    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return [f"{rel}: not valid Python (line {e.lineno}: {e.msg})"]
    defined = {
        n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    problems: List[str] = []
    lines = source.splitlines()
    for node in pipe.nodes.values():
        if node.kind != "transform":
            continue
        want = list(node.inputs) + (["start_date", "end_date"] if pipe.requires_dates else [])
        fn = defined.get(node.function)
        if fn is None:
            problems.append(f"{rel}: `{signature(pipe, node)}` is missing")
            continue
        args = fn.args
        names = [a.arg for a in [*args.posonlyargs, *args.args, *args.kwonlyargs]]
        if names[: len(want)] != want or args.kwarg is None:
            problems.append(f"{rel}: write the signature exactly as `{signature(pipe, node)}`")
            continue
        required_extra = [a.arg for a in args.args[len(want) : len(args.args) - len(args.defaults)]]
        if required_extra:
            problems.append(
                f"{rel}: {node.function}() also requires {', '.join(required_extra)}, "
                "which no input gives"
            )
        if is_stub(ast.get_source_segment(source, fn) or ""):
            problems.append(f"{rel}: {node.function}() still raises NotImplementedError")
    # The whole module, not only the node functions: a helper, or code at module
    # level (it runs on import), is held to the same rules.
    facts = ReviewFacts(pipe.name, "", "", "dev", {}, {}, {})
    facts.function = {"file": rel, "line": 1, "function": ""}
    facts.code_lines = lines
    problems += [f"{rel}:{f.line or 1}: {f.title} — {f.suggestion}" for f in _code_findings(facts)]
    return problems


def module_assembler(
    root: Path,
    bp: Blueprint,
    pipe: PipelineSpec,
    rel: str,
    existing: Existing,
    built: Dict[str, str],
) -> Callable[[ParsedAnswer], Assembled]:
    def assemble(answer: ParsedAnswer) -> Assembled:
        out = Assembled()
        source = answer.files.get(rel)
        if source is None:
            python = [b for lang, b in answer.unnamed if lang in ("python", "py")]
            python += [t for r, t in answer.files.items() if r.endswith(".py")]
            source = python[0] if len(python) == 1 else None
        others = [r for r in answer.files if r != rel]
        if others:
            out.rejected.append(f"Only {rel} is yours to write; leave out {', '.join(others)}")
        if source is None:
            out.rejected.append(f"The answer has no ```python file={rel} block")
            return out
        out.rejected += module_problems(source, rel, pipe)
        if out.rejected:
            return out
        out.files, out.base = render(root, bp, existing, {**built, rel: source})
        return out

    return assemble


def scaffold(root: Path, text: str) -> Draft:
    """A blueprint file made into a draft with stub functions — no model.

    For whoever writes the code themselves (a person, another assistant): apply
    it, then fill in each function (they raise ``NotImplementedError``).
    """
    from ducta.ai.agents.architect.design import check

    root = Path(root).resolve()
    report = check(root, text)
    bp = report.blueprint
    problems = [{"severity": "error", "message": e, "source": "architect"} for e in report.errors]
    files: Dict[str, str] = {}
    base: Dict[str, Optional[str]] = {}
    if report.ok and bp is not None:
        files, base = render(root, bp, Existing.of(root, build_context(root)))
    return Draft(
        id=datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6],
        request=(bp.goal or bp.name) if bp else "blueprint",
        provider="",
        model="",
        created_at=_now(),
        ok=report.ok,
        files=files,
        base=base,
        problems=problems
        + [{"severity": "warning", "message": w, "source": "architect"} for w in report.warnings],
        notes="Scaffolded without a model: every function raises NotImplementedError until written.",
        new_datasets=list(bp.datasets) if bp else [],
        raw_answer=json.dumps(bp.to_dict(), ensure_ascii=False) if bp else "",
        kind="architect",
        evidence="Checked by Ducta without a model",
        blocking=problems,
    )


def build(
    root: Path,
    bp: Blueprint,
    provider: LLMProvider,
    *,
    blueprint_id: Optional[str] = None,
    max_attempts: Optional[int] = None,
    on_attempt: Optional[Callable[..., None]] = None,
    on_module: Optional[Callable[[str, bool], None]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
) -> Draft:
    """One draft (kind ``architect``) with every file *bp* amounts to, code included."""
    root = Path(root).resolve()
    ctx = build_context(root)
    if ctx.config_error:
        raise AIConfigError(f"The project does not validate now: {ctx.config_error}")
    existing = Existing.of(root, ctx)
    errors, _ = check_blueprint(root, bp, existing)
    if errors:
        raise AIConflictError(
            "The blueprint no longer fits the project: "
            + "; ".join(errors[:5])
            + ". Revise it (`ducta ai revise`) and build again."
        )
    current = _validate(root, {})
    baseline = {_key(p) for p in current if p.get("severity") == "error"}
    built: Dict[str, str] = {}
    attempts: List[Attempt] = []
    notes: List[str] = []
    failed: Optional[Draft] = None
    for name in bp.order():
        pipe = bp.pipelines[name]
        if not any(n.kind == "transform" for n in pipe.nodes.values()):
            continue
        rel = module_path(root, pipe)

        def tagged(attempt: Attempt, rel: str = rel) -> None:
            # Numbered across the whole build, and naming the module it wrote.
            attempt.number = len(attempts) + attempt.number
            attempt.files = [rel]
            if on_attempt:
                on_attempt(attempt)

        part = _run(
            root,
            provider,
            system=BUILD_PROMPT,
            first_message=module_request(root, bp, pipe, rel, ctx),
            scope=Scope(kind="new", purpose="architect"),
            request=f"{bp.name}: module of {name}",
            ctx=ctx,
            max_attempts=max_attempts,
            on_attempt=tagged,
            current=current,
            should_stop=should_stop,
            assembler=module_assembler(root, bp, pipe, rel, existing, built),
            again=AGAIN_MODULE,
        )
        attempts.extend(part.attempts)
        if on_module:
            on_module(rel, part.ok)
        if not part.ok or rel not in part.files:
            failed = part
            break
        built[rel] = part.files[rel]
        if part.notes:
            notes.append(f"{rel}: {part.notes}")

    files, base = render(root, bp, existing, built)
    problems = _validate(root, files)
    blocking = _judge(problems, baseline, NEW)
    rejected: List[Dict[str, Any]] = []
    if failed is not None:
        rejected = [p for p in failed.blocking if p not in blocking]
        missing = [
            module_path(root, p)
            for p in bp.pipelines.values()
            if any(n.kind == "transform" for n in p.nodes.values())
            and module_path(root, p) not in built
        ]
        rejected.append(
            {
                "severity": "error",
                "source": "ai",
                "message": "Not built yet (still stubs): " + ", ".join(sorted(set(missing))),
            }
        )
    return Draft(
        id=datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6],
        request=bp.goal or bp.name,
        provider=provider.config.provider,
        model=(failed.model if failed else provider.config.model) or "",
        created_at=_now(),
        ok=failed is None and not blocking,
        files=files,
        base=base,
        problems=problems + rejected,
        notes="\n".join(notes),
        new_datasets=list(bp.datasets),
        attempts=attempts,
        raw_answer=json.dumps(bp.to_dict(), ensure_ascii=False),
        kind="architect",
        target=blueprint_id,
        evidence=f"Built from blueprint {blueprint_id or bp.name}",
        blocking=blocking + rejected,
    )
