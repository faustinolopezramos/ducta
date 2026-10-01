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

Say a value once: pipeline templates and defaults.

Both run on the raw files, before validation, so everything downstream sees
ordinary, fully written-out pipelines and datasets:

* ``extends`` / ``params`` — a pipeline file can build on a template (a
  pipeline written once, with ``${params.name}`` placeholders). The template's
  keys sit *under* the file's own; mappings merge, lists and scalars replace.
  Substitution is plain: a placeholder is replaced by the parameter's value,
  with no conditionals and no loops.
* ``defaults`` — values datasets and nodes get unless they set their own.
  Precedence, lowest first: project ``defaults`` < pipeline ``defaults`` <
  the dataset or node itself < the active environment's overrides.
"""

from __future__ import annotations

import copy
import difflib
import fnmatch
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

from ducta.setting.project_files import with_a_suffix

#: How a template declares a required parameter where there is no null (TOML).
REQUIRED = "<required>"

_PARAM = re.compile(r"\$\{params\.([A-Za-z_]\w*)\}")

#: Keys that belong to the extending file, not to the pipeline it produces.
_EXTENDS_KEYS = ("extends", "params")


def _merge(base: Any, override: Any) -> Any:
    """``override`` over ``base``: mappings merge, anything else replaces."""
    if isinstance(base, dict) and isinstance(override, dict):
        merged = dict(base)
        for key, value in override.items():
            merged[key] = _merge(base[key], value) if key in base else copy.deepcopy(value)
        return merged
    return copy.deepcopy(override)


# ── pipeline templates ───────────────────────────────────────────────────────


def _substitute(value: Any, params: Dict[str, Any]) -> Any:
    if isinstance(value, str):
        whole = _PARAM.fullmatch(value.strip())
        if whole:  # the value keeps its type: 0.2 stays a float, [a, b] a list
            return copy.deepcopy(params[whole.group(1)])
        return _PARAM.sub(lambda m: str(params[m.group(1)]), value)
    if isinstance(value, dict):
        return {k: _substitute(v, params) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute(v, params) for v in value]
    return value


def _placeholders(value: Any) -> List[str]:
    if isinstance(value, str):
        return _PARAM.findall(value)
    if isinstance(value, dict):
        return [name for v in value.values() for name in _placeholders(v)]
    if isinstance(value, list):
        return [name for v in value for name in _placeholders(v)]
    return []


def resolve_extends(
    root: Path,
    pipelines: Dict[str, Dict[str, Any]],
    read_template: Callable[[Path], Any],
) -> Tuple[Dict[str, Dict[str, Any]], List[str]]:
    """Expand every ``extends`` in ``pipelines``; returns the pipelines and the problems found.

    ``read_template`` reads one template file (a mapping), so the loader can
    keep its own error reporting.
    """
    problems: List[str] = []
    out: Dict[str, Dict[str, Any]] = {}
    for name, doc in pipelines.items():
        ref = doc.get("extends") if isinstance(doc, dict) else None
        if ref is None:
            out[name] = doc
            continue
        at = f"pipelines/{name}"
        if not isinstance(ref, str) or not ref.strip():
            problems.append(f"{at}: extends must name a template file, e.g. 'templates/etl'")
            out[name] = doc
            continue
        path = with_a_suffix(root, ref)
        if root.resolve() not in path.resolve().parents:
            problems.append(f"{at}: extends '{ref}' points outside the project")
            continue
        if not path.is_file():
            problems.append(f"{at}: extends '{ref}', but {path.relative_to(root)} does not exist")
            continue
        template = read_template(path)
        if not isinstance(template, dict):
            problems.append(f"{at}: template '{ref}' must be a mapping")
            continue
        if "extends" in template:
            problems.append(
                f"{at}: template '{ref}' extends another template; templates cannot chain"
            )
            continue
        declared = template.get("params") or {}
        supplied = doc.get("params") or {}
        if not isinstance(declared, dict) or not isinstance(supplied, dict):
            problems.append(f"{at}: params must be a mapping")
            continue
        bad = False
        for key in supplied:
            if key not in declared:
                close = difflib.get_close_matches(str(key), [str(k) for k in declared], n=1)
                hint = f" — did you mean '{close[0]}'?" if close else ""
                problems.append(f"{at}: template '{ref}' has no parameter '{key}'{hint}")
                bad = True
        values = {**declared, **supplied}
        body = {k: v for k, v in template.items() if k != "params"}
        for key in dict.fromkeys(_placeholders(body)):
            if key not in values:
                problems.append(
                    f"{at}: template '{ref}' uses ${{params.{key}}}, which it does not declare"
                )
                bad = True
        for key, value in values.items():
            if value is None or value == REQUIRED:
                problems.append(f"{at}: template '{ref}' needs the parameter '{key}'")
                bad = True
        if bad:
            continue
        own = {k: v for k, v in doc.items() if k not in _EXTENDS_KEYS}
        out[name] = _merge(_substitute(body, values), own)
    return out, problems


# ── defaults ─────────────────────────────────────────────────────────────────


def apply_defaults(
    project: Dict[str, Any],
    catalog: Dict[str, Any],
    pipelines: Dict[str, Dict[str, Any]],
) -> Tuple[Dict[str, Any], Dict[str, Dict[str, Any]]]:
    """The catalog and pipelines with ``defaults`` written into every dataset and node.

    Malformed ``defaults`` are left for the schema to report.
    """
    defaults = project.get("defaults") if isinstance(project, dict) else None
    defaults = defaults if isinstance(defaults, dict) else {}

    patterns = defaults.get("catalog")
    if isinstance(patterns, dict) and patterns:
        expanded: Dict[str, Any] = {}
        for name, entry in catalog.items():
            base: Dict[str, Any] = {}
            for pattern, keys in patterns.items():
                if isinstance(keys, dict) and fnmatch.fnmatchcase(str(name), str(pattern)):
                    base = _merge(base, keys)
            expanded[name] = _merge(base, entry or {}) if isinstance(entry or {}, dict) else entry
        catalog = expanded

    result: Dict[str, Dict[str, Any]] = {}
    for pname, doc in pipelines.items():
        result[pname] = _pipeline_with_defaults(doc, defaults)
    return catalog, result


def _pipeline_with_defaults(doc: Any, project_defaults: Dict[str, Any]) -> Any:
    if not isinstance(doc, dict) or not isinstance(doc.get("nodes"), dict):
        return doc
    own = _dict(doc.get("defaults"))
    node_base = _merge(_dict(project_defaults.get("node")), _dict(own.get("node")))
    stream_base = _merge(_dict(project_defaults.get("stream")), _dict(own.get("stream")))
    if not node_base and not stream_base:
        return doc
    nodes: Dict[str, Any] = {}
    for nname, node in doc["nodes"].items():
        if not isinstance(node, dict):
            nodes[nname] = node
            continue
        base = dict(node_base)
        if "quality" not in node:
            base.pop("quality", None)  # a default gate does not create a quality block
        merged = _merge(base, node)
        if node.get("kind") == "stream" and stream_base:
            merged["stream"] = _merge(stream_base, _dict(node.get("stream")))
        nodes[nname] = merged
    return {**doc, "nodes": nodes}


def _dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}
