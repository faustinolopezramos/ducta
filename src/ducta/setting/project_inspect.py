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

See what a project resolves to, and why: show, explain, diff, convert.

A project is built from layers: the files, the pipeline templates they extend,
``defaults``, and the active environment's overrides. These functions run the
same steps as the loader and report each layer, so "why is
``max_parallel_nodes`` 8 in prod?" has an answer with a file and a line.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml  # type: ignore[import-untyped]

from ducta.setting import project_files as pf
from ducta.setting.project_defaults import resolve_extends
from ducta.setting.project_loader import (
    PIPELINES_DIR,
    ProjectConfigError,
    apply_environment,
    environment_overrides,
    project_tree,
    read_project,
    resolve_path,
)

#: Marks "no such key", which is different from a key whose value is null.
MISSING = object()

#: Keys of ``ducta.yaml`` that are consumed while loading and mean nothing after it.
_CONSUMED = ("defaults",)


# ── show ─────────────────────────────────────────────────────────────────────


def resolved_tree(root: Path, env: Optional[str], pipeline: Optional[str] = None) -> Dict[str, Any]:
    """The project for ``env`` with templates, defaults and overrides applied.

    With ``pipeline``: only that pipeline, and only the datasets its nodes touch.
    """
    tree = copy.deepcopy(apply_environment(read_project(root), env))
    for key in _CONSUMED:
        tree.pop(key, None)
    for doc in tree["pipelines"].values():
        if isinstance(doc, dict):
            doc.pop("defaults", None)
    if pipeline is None:
        return tree
    if pipeline not in tree["pipelines"]:
        known = ", ".join(sorted(tree["pipelines"])) or "none"
        raise ProjectConfigError([f"no pipeline '{pipeline}' (defined: {known})"])
    doc = tree["pipelines"][pipeline]
    tree["pipelines"] = {pipeline: doc}
    touched = _datasets_of(doc)
    tree["catalog"] = {k: v for k, v in tree["catalog"].items() if k in touched}
    return tree


def _datasets_of(pipeline: Dict[str, Any]) -> set:
    names: set = set()
    for node in (pipeline.get("nodes") or {}).values():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs") or []
        names.update(inputs.values() if isinstance(inputs, dict) else inputs)
        names.update(node.get("outputs") or [])
    return names


def dump(data: Any, fmt: str, schema: Optional[str] = None) -> str:
    """``data`` as ``yaml``, ``toml`` or ``json`` text (``schema``: the editor schema to name)."""
    if fmt == "json":
        body = {"$schema": schema, **data} if schema and isinstance(data, dict) else data
        return json.dumps(body, indent=2, ensure_ascii=False, default=str) + "\n"
    if fmt == "toml":
        import tomli_w

        header = f"#:schema {schema}\n" if schema else ""
        return header + tomli_w.dumps(_without_none(data))
    header = f"# yaml-language-server: $schema={schema}\n" if schema else ""
    text: str = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, default_flow_style=False)
    return header + text


def _without_none(value: Any, key: str = "") -> Any:
    """TOML has no null: a key set to null is the same as a key left out.

    The exception is a template's required parameter, which is declared as null
    and is written as ``"<required>"`` instead.
    """
    from ducta.setting.project_defaults import REQUIRED

    if isinstance(value, dict):
        return {
            k: (REQUIRED if v is None and key == "params" else _without_none(v, k))
            for k, v in value.items()
            if v is not None or key == "params"
        }
    if isinstance(value, list):
        return [_without_none(v) for v in value if v is not None]
    return value


# ── diff ─────────────────────────────────────────────────────────────────────


def _leaves(value: Any, prefix: Tuple[str, ...] = ()) -> Dict[Tuple[str, ...], Any]:
    if isinstance(value, dict) and value:
        out: Dict[Tuple[str, ...], Any] = {}
        for key, child in value.items():
            out.update(_leaves(child, (*prefix, str(key))))
        return out
    return {prefix: value}


def diff_trees(a: Dict[str, Any], b: Dict[str, Any]) -> List[Tuple[str, Any, Any]]:
    """``(path, value in a, value in b)`` for every leaf that differs (``MISSING`` when absent)."""
    left, right = _leaves(a), _leaves(b)
    changes = []
    for path in sorted(set(left) | set(right)):
        before, after = left.get(path, MISSING), right.get(path, MISSING)
        if before != after:
            changes.append((".".join(path), before, after))
    return changes


# ── explain ──────────────────────────────────────────────────────────────────


@dataclass
class Layer:
    """One step in how a value came to be."""

    name: str
    value: Any
    at: Optional[str] = None


@dataclass
class Explanation:
    path: List[str]
    found: bool
    value: Any = None
    layers: List[Layer] = field(default_factory=list)


def _get(tree: Any, path: List[str]) -> Any:
    node = tree
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return MISSING
        node = node[key]
    return node


def _where(where: Dict[Tuple[str, ...], str], path: List[str]) -> Optional[str]:
    """The best known ``file:line`` for ``path`` in the base files."""
    if not path:
        return None
    head, rest = path[0], path[1:]
    keys = (("catalog", *rest),) if head == "catalog" else None
    if head == "pipelines":
        keys = (("pipelines", *rest),)
    candidates = keys[0] if keys else ("project", *path)
    # the position of the deepest prefix of the path that the file names
    for end in range(len(candidates), 0, -1):
        found = where.get(tuple(candidates[:end]))
        if found:
            return found
    return None


def explain(root: Path, dotted: str, env: Optional[str] = None) -> Explanation:
    """Where the value at ``dotted`` (e.g. ``settings.max_parallel_nodes``) comes from."""
    root = Path(root)
    raw = read_project(root, expand=False)
    expanded = read_project(root)
    base_raw = project_tree(raw)
    expanded_tree = project_tree(expanded)

    templated, _ = resolve_extends(root, copy.deepcopy(raw.pipelines), pf.load)
    templated_tree = {**base_raw, "pipelines": templated}
    final = apply_environment(expanded, env)
    path = resolve_path(final, dotted)

    explanation = Explanation(path=path, found=_get(final, path) is not MISSING)
    explanation.value = None if not explanation.found else _get(final, path)

    name, overrides = environment_overrides(expanded, env, expanded_tree)
    stages: List[Tuple[str, Dict[str, Any], Optional[str]]] = [
        ("file", base_raw, _where(raw.where, path)),
        ("template", templated_tree, None),
        ("defaults", expanded_tree, None),
    ]
    if name is not None:
        stages.append(
            (f"environments.{name}", final, _override_position(expanded, name, path, expanded_tree))
        )

    previous: Any = MISSING
    for label, tree, at in stages:
        value = _get(tree, path)
        if value is MISSING or value == previous:
            continue
        if label == "template":
            ref = (raw.pipelines.get(path[1]) or {}).get("extends") if len(path) > 1 else None
            label = f"template {ref}" if ref else "template"
        explanation.layers.append(Layer(label, value, at))
        previous = value
    return explanation


def _override_position(
    located: Any, env_name: str, path: List[str], tree: Dict[str, Any]
) -> Optional[str]:
    """The line of the ``environments.<env>`` key that sets ``path`` (or one above it)."""
    block = (located.project.get("environments") or {}).get(env_name) or {}
    for key in block:
        target = resolve_path(tree, key) if "." in key else [key]
        if path[: len(target)] == target or target[: len(path)] == path:
            at = located.where.get(("project", "environments", env_name, key))
            return str(at) if at else None
    at = located.where.get(("project", "environments", env_name))
    return str(at) if at else None


# ── convert ──────────────────────────────────────────────────────────────────


def convert_project(root: Path, target: Path, fmt: str) -> List[Path]:
    """Write the project's configuration files to ``target`` as ``fmt``.

    Only ``ducta.*``, ``catalog.*``, ``pipelines/`` and ``templates/`` are
    converted (their comments cannot be carried over); the Python and the data
    stay where they are. The editor schemas are written next to them.
    """
    from ducta.setting.project_decompile import write_schemas

    root, target = Path(root), Path(target)
    if target.exists() and any(target.iterdir()):
        raise ProjectConfigError([f"{target} is not empty; convert into a new directory"])
    ext = f".{fmt}"
    written: List[Path] = []
    schemas = ".ducta/schema"
    sources: List[Tuple[Path, str]] = []
    for stem, kind in (("ducta", "project"), ("catalog", "catalog")):
        sources += [(f, kind) for f in pf.find_files(root, stem)]
    for folder, kind in ((PIPELINES_DIR, "pipeline"), ("templates", "pipeline")):
        base = root / folder
        if base.is_dir():
            sources += [
                (p, kind)
                for p in sorted(base.rglob("*"))
                if p.is_file() and p.suffix.lower() in pf.SUFFIXES
            ]
    for source, kind in sources:
        relative = source.relative_to(root).with_suffix(ext)
        depth = "../" * (len(relative.parts) - 1)
        out = target / relative
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            dump(pf.load(source), fmt, f"{depth}{schemas}/{kind}.json"), encoding="utf-8"
        )
        written.append(out)
    write_schemas(target)
    return written
