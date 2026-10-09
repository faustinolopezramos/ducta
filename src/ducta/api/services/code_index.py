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

Which function each node runs, and where it is.

The UI moves between a node and its code in one step — from the canvas to
the line of its function, and from a function back to its node. That needs
the mapping ``node → (file, line)`` and its reverse, for the whole project.
It is read from the configuration and from each source file's syntax tree;
no project module is imported, so nothing of the project's code runs.
"""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ducta.api.repositories.v2_store import V2ProjectStore


@dataclass
class FunctionEntry:
    name: str
    line: int
    params: List[str] = field(default_factory=list)
    docstring: Optional[str] = None
    #: Parameters without a default (other than *args/**kwargs).
    required: List[str] = field(default_factory=list)
    #: Takes **kwargs: any input name is accepted.
    varkw: bool = False


@dataclass
class NodeCodeEntry:
    node: str
    pipeline: Optional[str]
    module: str
    function: str
    #: Relative to the project root (POSIX).
    file: str
    #: Relative to the workspace root (POSIX) — what /workspace/files takes.
    workspace_file: str
    line: Optional[int]
    exists: bool
    params: List[str] = field(default_factory=list)
    inputs: Dict[str, str] = field(default_factory=dict)


def module_file(project_root: Path, module: str) -> Path:
    """``src.silver`` → ``src/silver.py``, or the package's ``__init__.py``."""
    rel = Path(*module.split("."))
    as_file = project_root / rel.with_suffix(".py")
    if as_file.exists():
        return as_file
    package = project_root / rel / "__init__.py"
    return package if package.exists() else as_file


def top_level_functions(source: str) -> List[FunctionEntry]:
    """Every top-level ``def`` with its line and parameters; [] if it does not parse."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    out = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args
            positional = [*args.posonlyargs, *args.args]
            params = [a.arg for a in [*positional, *args.kwonlyargs]]
            # Defaults apply to the last positional parameters.
            no_default = positional[: len(positional) - len(args.defaults)]
            required = [a.arg for a in no_default] + [
                a.arg for a, d in zip(args.kwonlyargs, args.kw_defaults) if d is None
            ]
            out.append(
                FunctionEntry(
                    name=node.name,
                    line=node.lineno,
                    params=params,
                    docstring=ast.get_docstring(node),
                    required=required,
                    varkw=args.kwarg is not None,
                )
            )
    return out


def _inputs(spec: Dict[str, Any]) -> Dict[str, str]:
    raw = spec.get("input") or {}
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items()}
    if isinstance(raw, str):
        return {raw: raw}
    return {str(v): str(v) for v in raw}


def build_code_index(store: V2ProjectStore, workspace_root: Path) -> Dict[str, Any]:
    """``{"nodes": [...], "files": {file: [functions]}}`` for one project."""
    root = store.root
    owner: Dict[str, str] = {}
    for pname, pspec in store.pipelines().items():
        for nname in (pspec or {}).get("nodes") or []:
            owner.setdefault(nname, pname)

    parsed: Dict[Path, List[FunctionEntry]] = {}
    entries: List[NodeCodeEntry] = []
    for name, spec in store.nodes().items():
        module, function = spec.get("module"), spec.get("function")
        if not module or not function:
            continue  # ingestion and built-in nodes run no project code
        path = module_file(root, module)
        if path not in parsed:
            parsed[path] = (
                top_level_functions(path.read_text(encoding="utf-8")) if path.exists() else []
            )
        fn = next((f for f in parsed[path] if f.name == function), None)
        entries.append(
            NodeCodeEntry(
                node=name,
                pipeline=owner.get(name),
                module=module,
                function=function,
                file=path.relative_to(root).as_posix(),
                workspace_file=_relative(path, workspace_root),
                line=fn.line if fn else None,
                exists=path.exists(),
                params=fn.params if fn else [],
                inputs=_inputs(spec),
            )
        )
    files = {
        path.relative_to(root).as_posix(): [asdict(f) for f in funcs]
        for path, funcs in parsed.items()
        if path.exists()
    }
    return {"nodes": [asdict(e) for e in entries], "files": files}


def _relative(path: Path, base: Path) -> str:
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return path.as_posix()
