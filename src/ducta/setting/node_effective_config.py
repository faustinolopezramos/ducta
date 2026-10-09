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

A node's settings as they apply, in every environment, and where each comes
from: the node itself, its pipeline's ``defaults.node``, the project's
``defaults.node``, or the framework's default. Precedence, as the loader
applies it: project < pipeline < node < environment.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ducta.setting.project_loader import apply_environment, read_project
from ducta.setting.project_schema import TransformNode

BASE = "base"
KEYS: Tuple[str, ...] = ("retry", "timeout_seconds", "on_missing_input", "fail_fast", "metadata")


def _framework_default(key: str) -> Any:
    field = TransformNode.model_fields.get(key)
    if field is None:
        return None
    default = field.get_default(call_default_factory=True)
    return None if default in ({}, []) else default


def _defaults_node(doc: Any) -> Dict[str, Any]:
    d = doc.get("defaults") if isinstance(doc, dict) else None
    node = d.get("node") if isinstance(d, dict) else None
    return node if isinstance(node, dict) else {}


def _template_body(root: Path, ndoc: Any) -> Dict[str, Any]:
    """The node a ``use:`` instance gets from its template, parameters filled; {} if none."""
    from ducta.setting.project_defaults import (
        NODE_TEMPLATES_DIR,
        _param_values,
        _substitute,
    )
    from ducta.setting.project_files import load, with_a_suffix

    ref = ndoc.get("use") if isinstance(ndoc, dict) else None
    if not isinstance(ref, str):
        return {}
    try:
        template = load(with_a_suffix(root, f"{NODE_TEMPLATES_DIR}/{ref}"))
        values = {**_param_values(template.get("params") or {}), **(ndoc.get("with") or {})}
        body = _substitute(template.get("node") or {}, values)
    except Exception:  # noqa: BLE001 — the loader reports a broken template; here it adds nothing
        return {}
    return body if isinstance(body, dict) else {}


def _resolve(
    tree: Dict[str, Any], pipeline: str, node: str, key: str, root: Path = Path(".")
) -> Tuple[Any, str]:
    pdoc = (tree.get("pipelines") or {}).get(pipeline) or {}
    ndoc = (pdoc.get("nodes") or {}).get(node) or {}
    if isinstance(ndoc, dict) and ndoc.get(key) is not None:
        return ndoc[key], "node"
    from_template = _template_body(root, ndoc)
    if from_template.get(key) is not None:
        return from_template[key], f"template {ndoc.get('use')}"
    if _defaults_node(pdoc).get(key) is not None:
        return _defaults_node(pdoc)[key], "pipeline defaults"
    if _defaults_node(tree).get(key) is not None:
        return _defaults_node(tree)[key], "project defaults"
    return _framework_default(key), "framework default"


def effective_node_config(root: Path, pipeline: str, node: str) -> Dict[str, Any]:
    """``{"environments": [...], "rows": [{key, values, sources, overridden}]}``."""
    # Unexpanded: `defaults` still sit where they were written, so the origin of
    # each value can be told apart from the value itself.
    located = read_project(Path(root), expand=False)
    envs: List[str] = list((located.project.get("environments") or {}).keys())
    names = [BASE, *envs]
    trees = {n: apply_environment(located, None if n == BASE else n) for n in names}
    pdoc = (trees[BASE].get("pipelines") or {}).get(pipeline)
    if not isinstance(pdoc, dict) or node not in (pdoc.get("nodes") or {}):
        raise KeyError(f"node '{node}' is not in pipeline '{pipeline}'")
    rows = []
    for key in KEYS:
        resolved = {n: _resolve(trees[n], pipeline, node, key, Path(root)) for n in names}
        values: Dict[str, Optional[Any]] = {n: v for n, (v, _s) in resolved.items()}
        rows.append(
            {
                "key": key,
                "values": values,
                "sources": {n: s for n, (_v, s) in resolved.items()},
                "overridden": {n: values[n] != values[BASE] for n in envs},
            }
        )
    return {"environments": names, "rows": rows}
