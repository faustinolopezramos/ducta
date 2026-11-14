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

Which nodes of a pipeline a run covers — the whole of it, some of its nodes,
everything downstream of one, or only what changed since the last good run.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def _reads(spec: Dict[str, Any]) -> List[str]:
    raw = spec.get("input") or []
    if isinstance(raw, dict):
        return [str(v) for v in raw.values()]
    if isinstance(raw, str):
        return [raw]
    return [str(v) for v in raw]


def downstream_of(start: str, members: List[str], nodes: Dict[str, Dict[str, Any]]) -> List[str]:
    """*start* and every node of *members* that reads, transitively, what it writes."""
    produced_by: Dict[str, str] = {}
    for name in members:
        for ds in (nodes.get(name) or {}).get("output") or []:
            produced_by[str(ds)] = name
    picked = {start}
    changed = True
    while changed:
        changed = False
        for name in members:
            if name in picked:
                continue
            spec = nodes.get(name) or {}
            deps = {produced_by.get(ds) for ds in _reads(spec)} | set(
                spec.get("dependencies") or []
            )
            if deps & picked:
                picked.add(name)
                changed = True
    return [n for n in members if n in picked]


def upstream_of(target: str, members: List[str], nodes: Dict[str, Dict[str, Any]]) -> List[str]:
    """*target* and every node of *members* it needs, transitively — a run that
    stops right after *target* (a data breakpoint)."""
    produced_by: Dict[str, str] = {}
    for name in members:
        for ds in (nodes.get(name) or {}).get("output") or []:
            produced_by[str(ds)] = name
    picked = {target}
    stack = [target]
    while stack:
        spec = nodes.get(stack.pop()) or {}
        deps = {produced_by.get(ds) for ds in _reads(spec)} | set(spec.get("dependencies") or [])
        for dep in deps:
            if dep and dep in members and dep not in picked:
                picked.add(dep)
                stack.append(dep)
    return [n for n in members if n in picked]


def resolve_scope(
    scope: Optional[str],
    requested: Optional[List[str]],
    members: List[str],
    nodes: Dict[str, Dict[str, Any]],
    not_fresh: Optional[List[str]] = None,
) -> Optional[List[str]]:
    """The nodes to run, in pipeline order; None for the whole pipeline."""
    requested = list(requested or [])
    unknown = [n for n in requested if n not in members]
    if unknown:
        raise ValueError(f"Not nodes of this pipeline: {', '.join(unknown)}")
    if scope in (None, "", "pipeline"):
        return requested or None
    if scope == "selected":
        if not requested:
            raise ValueError("scope 'selected' needs `nodes`")
        return [n for n in members if n in set(requested)]
    if scope == "from":
        if len(requested) != 1:
            raise ValueError("scope 'from' needs exactly one node in `nodes`")
        return downstream_of(requested[0], members, nodes)
    if scope == "after":
        if len(requested) != 1:
            raise ValueError("scope 'after' needs exactly one node in `nodes`")
        rest = [n for n in downstream_of(requested[0], members, nodes) if n != requested[0]]
        if not rest:
            raise ValueError(f"Nothing in this pipeline runs after {requested[0]}")
        return rest
    if scope == "until":
        if len(requested) != 1:
            raise ValueError("scope 'until' needs exactly one node in `nodes`")
        return upstream_of(requested[0], members, nodes)
    if scope == "stale":
        picked = [n for n in members if n in set(not_fresh or [])]
        if not picked:
            raise ValueError("Nothing in this pipeline changed since its last successful run")
        return picked
    raise ValueError(f"Unknown scope '{scope}' (pipeline, selected, from, after, until, stale)")
