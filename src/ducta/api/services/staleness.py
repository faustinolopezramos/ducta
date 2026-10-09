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

Which nodes no longer match their last successful run.

A node is **stale** when its function's source changed since the certificate
of its pipeline's last successful run in that environment, or when a node it
reads from is stale. It is **never** run when no such certificate names it,
and **fresh** otherwise. The function's hash is computed from the syntax tree
exactly as the certificate computed it at run time (``inspect.getsource``:
decorators through the last line), so nothing of the project is imported.
"""

from __future__ import annotations

import ast
import hashlib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ducta.api.repositories.v2_store import V2ProjectStore
from ducta.api.services.code_index import module_file


@dataclass
class NodeFreshness:
    node: str
    pipeline: Optional[str]
    state: str  # fresh | stale | never
    reasons: List[str] = field(default_factory=list)
    last_run_id: Optional[str] = None
    last_run_at: Optional[str] = None


def function_source_hash(source: str, function: str) -> Optional[str]:
    """``sha256:<hex>`` of a top-level function's source, as the certificate records it."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    lines = source.splitlines(keepends=True)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function:
            start = min([d.lineno for d in node.decorator_list] + [node.lineno])
            text = "".join(lines[start - 1 : node.end_lineno])
            return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
    return None


def node_freshness(
    store: V2ProjectStore, last_ok: Dict[str, Dict[str, Any]]
) -> Dict[str, NodeFreshness]:
    """Per node: fresh, stale (and why) or never run, against ``last_ok`` (pipeline → certificate)."""
    owner: Dict[str, str] = {}
    for pname, pspec in store.pipelines().items():
        for nname in (pspec or {}).get("nodes") or []:
            owner.setdefault(nname, pname)
    nodes = store.nodes()
    producers: Dict[str, str] = {}
    for name, spec in nodes.items():
        for ds in spec.get("output") or []:
            producers.setdefault(str(ds), name)

    sources: Dict[Path, str] = {}
    out: Dict[str, NodeFreshness] = {}
    for name, spec in nodes.items():
        pipeline = owner.get(name)
        cert = last_ok.get(pipeline or "")
        ran = cert is not None and any(n.get("name") == name for n in cert.get("nodes") or [])
        if not ran:
            out[name] = NodeFreshness(name, pipeline, "never")
            continue
        assert cert is not None
        state = NodeFreshness(
            name,
            pipeline,
            "fresh",
            last_run_id=cert.get("run_id"),
            last_run_at=cert.get("started_at"),
        )
        module, function = spec.get("module"), spec.get("function")
        if module and function:
            recorded = ((cert.get("code") or {}).get("nodes") or {}).get(
                f"{module}.{function}"
            ) or {}
            path = module_file(store.root, module)
            if path not in sources:
                sources[path] = path.read_text(encoding="utf-8") if path.exists() else ""
            now = function_source_hash(sources[path], function)
            if recorded.get("source_hash") and now != recorded["source_hash"]:
                state.state = "stale"
                state.reasons.append(f"{function}() changed since the last successful run")
        out[name] = state

    # Stale flows downstream: a node reading a stale node's output is stale too.
    changed = True
    while changed:
        changed = False
        for name, spec in nodes.items():
            if out[name].state != "fresh":
                continue
            raw = spec.get("input") or []
            reads = list(raw.values()) if isinstance(raw, dict) else list(raw)
            for ds in reads:
                up = producers.get(str(ds))
                if up and up != name and out.get(up) and out[up].state == "stale":
                    out[name].state = "stale"
                    out[name].reasons.append(f"reads {ds}, from {up}, which is stale")
                    changed = True
                    break
    return out


def freshness_dicts(result: Dict[str, NodeFreshness]) -> List[Dict[str, Any]]:
    return [asdict(v) for v in sorted(result.values(), key=lambda f: f.node)]
