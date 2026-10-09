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

Validate a project as it would be — with unsaved edits — without writing it.

Two layers, both cheap enough to run while someone types:

* **config** — the format-2 loader on a scratch copy of the project with the
  drafts laid over it, in every environment: unknown keys, datasets not in the
  catalog, two writers of one dataset, cycles.
* **code** — each node's ``run:`` against its source file's syntax tree: the
  file and the function exist, every input is a parameter the function takes,
  every parameter it requires is given. No project module is imported.

The deep preflight (imports, connections) stays a separate, explicit step.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Dict, List

from ducta.api.repositories.v2_store import V2ProjectStore
from ducta.api.services.code_index import module_file, top_level_functions
from ducta.setting.problems import Problem, parse_problems
from ducta.setting.project_loader import ProjectConfigError, validate_project

#: Directories that hold data or state, never configuration or code.
_SKIP = {".git", ".ducta", "data", "logs", "models", "lib", "node_modules", "__pycache__", ".venv"}
#: Passed by the engine, not by an input.
_INJECTED = {"start_date", "end_date", "ml_context", "spark", "context", "kwargs"}


def _copy_project(root: Path, dest: Path) -> None:
    shutil.copytree(
        root,
        dest,
        ignore=lambda _d, names: [n for n in names if n in _SKIP],
        dirs_exist_ok=True,
    )


def config_problems(root: Path) -> List[Problem]:
    try:
        project = validate_project(root)
        for env in project.project.environments:
            validate_project(root, env)
    except ProjectConfigError as e:
        return parse_problems(e.problems, source="config")
    return []


def _governance(store: V2ProjectStore) -> List[Problem]:
    """Missing owners and contracts, pointed at the pipeline file or catalog entry."""
    from ducta.api.services.governance import governance_problems

    try:
        project = store.project()
    except Exception:  # noqa: BLE001 — config problems were already reported
        return []
    out = governance_problems(project)
    root = store.root
    for p in out:
        if p.pipeline:
            path = store.pipeline_path(p.pipeline)
            p.file = path.relative_to(root).as_posix() if path.exists() else None
    return out


def code_problems(store: V2ProjectStore) -> List[Problem]:
    """Each node's ``run:`` checked against its source file, without importing it."""
    root = store.root
    owner: Dict[str, str] = {}
    files: Dict[str, str] = {}
    for pname, pspec in store.pipelines().items():
        for nname in (pspec or {}).get("nodes") or []:
            owner.setdefault(nname, pname)
    for pname in store.pipelines():
        path = store.pipeline_path(pname)
        files[pname] = (
            path.relative_to(root).as_posix() if path.exists() else f"pipelines/{pname}.yaml"
        )

    parsed: Dict[Path, list] = {}
    out: List[Problem] = []
    for name, spec in store.nodes().items():
        module, function = spec.get("module"), spec.get("function")
        if not module or not function:
            continue
        pipeline = owner.get(name)
        where = dict(node=name, pipeline=pipeline, file=files.get(pipeline or ""), source="code")
        path = module_file(root, module)
        rel = path.relative_to(root).as_posix()
        if not path.exists():
            out.append(
                Problem(
                    severity="error",
                    code="function_not_found",
                    message=f"Node '{name}' runs {module}:{function}, but {rel} does not exist",
                    **where,
                )
            )
            continue
        if path not in parsed:
            parsed[path] = top_level_functions(path.read_text(encoding="utf-8"))
        fn = next((f for f in parsed[path] if f.name == function), None)
        if fn is None:
            out.append(
                Problem(
                    severity="error",
                    code="function_not_found",
                    message=f"Node '{name}' runs {function}(), which {rel} does not define",
                    **where,
                )
            )
            continue
        raw = spec.get("input") or {}
        aliases = list(raw.keys()) if isinstance(raw, dict) else []
        if aliases and not fn.varkw:
            for alias in aliases:
                if alias not in fn.params:
                    out.append(
                        Problem(
                            severity="error",
                            code="input_not_a_parameter",
                            message=f"Node '{name}' passes input '{alias}', but {function}() "
                            f"has no parameter of that name ({', '.join(fn.params) or 'none'})",
                            **where,
                        )
                    )
        if aliases:
            missing = [p for p in fn.required if p not in aliases and p not in _INJECTED]
            for param in missing:
                out.append(
                    Problem(
                        severity="warning",
                        code="parameter_not_given",
                        message=f"{function}() requires '{param}', and node '{name}' gives no "
                        f"input of that name",
                        **where,
                    )
                )
    return out


def validate_draft(store: V2ProjectStore, drafts: Dict[str, str]) -> List[Problem]:
    """Problems of the project with *drafts* (project-relative path → text) applied."""
    root = store.root.resolve()
    with tempfile.TemporaryDirectory(prefix="ducta-draft-") as tmp:
        scratch = Path(tmp) / "project"
        _copy_project(root, scratch)
        for rel, text in drafts.items():
            target = (scratch / rel).resolve()
            if scratch.resolve() not in target.parents:
                raise ValueError(f"'{rel}' is outside the project")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        problems = config_problems(scratch)
        if not any(p.severity == "error" for p in problems):
            draft_store = V2ProjectStore.detect(scratch)
            if draft_store is not None:
                problems += code_problems(draft_store)
                problems += _governance(draft_store)
        return problems
