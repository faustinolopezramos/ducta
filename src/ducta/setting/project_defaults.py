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
  in values *and* in keys (so one template names its nodes and datasets per copy:
  ``${params.layer}.clean_orders``), with no conditionals and no loops.
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


def _substitute_key(key: Any, params: Dict[str, Any]) -> Any:
    """A key with its placeholders filled: ``${params.layer}.clean`` → ``silver.clean``.

    Only plain values can be part of a name; a list or a mapping cannot.
    """
    if not isinstance(key, str):
        return key

    def fill(match: "re.Match[str]") -> str:
        value = params[match.group(1)]
        if isinstance(value, (dict, list)):
            raise ValueError(
                f"parameter '{match.group(1)}' is used inside the key '{key}', so it must be "
                f"a plain value (text or a number), not a {type(value).__name__}"
            )
        return str(value)

    return _PARAM.sub(fill, key)


def _substitute(value: Any, params: Dict[str, Any]) -> Any:
    if isinstance(value, str):
        whole = _PARAM.fullmatch(value.strip())
        if whole:  # the value keeps its type: 0.2 stays a float, [a, b] a list
            return copy.deepcopy(params[whole.group(1)])
        return _PARAM.sub(lambda m: str(params[m.group(1)]), value)
    if isinstance(value, dict):
        # Keys too: this is how one template writes nodes or datasets whose names
        # differ per copy. Two keys that become the same name are an error, never a
        # silent overwrite.
        out: Dict[Any, Any] = {}
        for key, inner in value.items():
            name = _substitute_key(key, params)
            if name in out:
                raise ValueError(
                    f"the keys '{key}' and another one both become '{name}' with these parameters"
                )
            out[name] = _substitute(inner, params)
        return out
    if isinstance(value, list):
        return [_substitute(v, params) for v in value]
    return value


def _placeholders(value: Any) -> List[str]:
    if isinstance(value, str):
        return _PARAM.findall(value)
    if isinstance(value, dict):
        return [
            name for key, v in value.items() for name in [*_placeholders(key), *_placeholders(v)]
        ]
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
        try:
            expanded = _substitute(body, values)
        except ValueError as e:
            problems.append(f"{at}: template '{ref}': {e}")
            continue
        out[name] = _merge(expanded, own)
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


# ── node templates (use / with) ──────────────────────────────────────────────

#: Where node templates live: ``templates/nodes/<name>.yaml``.
NODE_TEMPLATES_DIR = "templates/nodes"

#: Keys that belong to the instance, not to the node it produces.
_USE_KEYS = ("use", "with")


def _param_values(declared: Dict[str, Any]) -> Dict[str, Any]:
    """A template's params as name → default: ``{type, default}`` specs or a bare default."""
    out: Dict[str, Any] = {}
    for key, spec in declared.items():
        if isinstance(spec, dict) and (set(spec) <= {"type", "default", "description"}):
            out[key] = spec.get("default", REQUIRED)
        else:
            out[key] = spec
    return out


def node_template_names(root: Path) -> List[str]:
    folder = root / NODE_TEMPLATES_DIR
    if not folder.is_dir():
        return []
    return sorted(p.stem for p in folder.iterdir() if p.suffix.lower() in (".yaml", ".yml"))


def resolve_node_templates(
    root: Path,
    pipelines: Dict[str, Dict[str, Any]],
    read_template: Callable[[Path], Any],
    locate: Callable[[Tuple[str, ...]], str] = lambda _p: "?",
) -> Tuple[Dict[str, Dict[str, Any]], List[str]]:
    """Expand every node's ``use`` + ``with`` (ADR 0001 §3); returns the pipelines and problems.

    The template's ``node`` body, with ``${params.x}`` filled, is the base; keys set on
    the instance win. Problems point at the instance (``file:line``) and name the template.
    """
    problems: List[str] = []
    cache: Dict[str, Any] = {}
    out: Dict[str, Dict[str, Any]] = {}
    for pname, doc in pipelines.items():
        nodes = doc.get("nodes") if isinstance(doc, dict) else None
        if not isinstance(nodes, dict) or not any(
            isinstance(n, dict) and "use" in n for n in nodes.values()
        ):
            out[pname] = doc
            continue
        new_nodes: Dict[str, Any] = {}
        for nname, node in nodes.items():
            if not isinstance(node, dict) or "use" not in node:
                new_nodes[nname] = node
                continue
            at = f"{locate(('pipelines', pname, 'nodes', nname, 'use'))} node '{nname}'"
            ref = node.get("use")
            if not isinstance(ref, str) or not ref.strip() or "/" in ref or ".." in ref:
                problems.append(f"{at}: use must name a template in {NODE_TEMPLATES_DIR}/")
                continue
            path = with_a_suffix(root, f"{NODE_TEMPLATES_DIR}/{ref}")
            if not path.is_file():
                known = node_template_names(root)
                close = difflib.get_close_matches(ref, known, n=1)
                hint = f" — did you mean '{close[0]}'?" if close else ""
                problems.append(
                    f"{at}: uses '{ref}', but {NODE_TEMPLATES_DIR}/{ref}.yaml does not exist{hint}"
                )
                continue
            if ref not in cache:
                cache[ref] = read_template(path)
            template = cache[ref]
            if not isinstance(template, dict) or not isinstance(template.get("node"), dict):
                problems.append(f"{at}: template '{ref}' must be a mapping with a 'node' block")
                continue
            if "use" in template["node"]:
                problems.append(
                    f"{at}: template '{ref}' uses another template; templates cannot chain"
                )
                continue
            declared = template.get("params") or {}
            supplied = node.get("with") or {}
            if not isinstance(declared, dict) or not isinstance(supplied, dict):
                problems.append(f"{at}: 'with' and the template's params must be mappings")
                continue
            values = {**_param_values(declared), **supplied}
            bad = False
            for key in supplied:
                if key not in declared:
                    close = difflib.get_close_matches(str(key), [str(k) for k in declared], n=1)
                    hint = f" — did you mean '{close[0]}'?" if close else ""
                    problems.append(f"{at}: template '{ref}' has no parameter '{key}'{hint}")
                    bad = True
            for key in dict.fromkeys(_placeholders(template["node"])):
                if key not in values:
                    problems.append(
                        f"{at}: template '{ref}' uses ${{params.{key}}}, which it does not declare"
                    )
                    bad = True
            for key, value in values.items():
                if value is None or value == REQUIRED:
                    problems.append(
                        f"{at}: template '{ref}' needs the parameter '{key}' (in 'with')"
                    )
                    bad = True
            if bad:
                continue
            try:
                body = _substitute(template["node"], values)
            except ValueError as e:
                problems.append(f"{at}: template '{ref}': {e}")
                continue
            own = {k: v for k, v in node.items() if k not in _USE_KEYS}
            new_nodes[nname] = _merge(body, own)
        out[pname] = {**doc, "nodes": new_nodes}
    return out, problems


# ── subpipelines (use: pipeline:<name>) ──────────────────────────────────────

#: Where subpipelines live: ``templates/pipelines/<name>.yaml``.
PIPELINE_TEMPLATES_DIR = "templates/pipelines"
PIPELINE_PREFIX = "pipeline:"


def pipeline_template_names(root: Path) -> List[str]:
    folder = root / PIPELINE_TEMPLATES_DIR
    if not folder.is_dir():
        return []
    return sorted(p.stem for p in folder.iterdir() if p.suffix.lower() in (".yaml", ".yml"))


def resolve_pipeline_uses(
    root: Path,
    pipelines: Dict[str, Dict[str, Any]],
    catalog: Dict[str, Any],
    read_template: Callable[[Path], Any],
    locate: Callable[[Tuple[str, ...]], str] = lambda _p: "?",
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any], List[str]]:
    """Expand every ``use: pipeline:<name>`` node into the subpipeline's nodes.

    The subpipeline (``templates/pipelines/<name>.yaml``: ``params``, ``nodes`` and
    an optional ``catalog`` for the datasets it writes) is filled with the
    instance's ``with`` and takes the instance's place, in order. Its catalog
    entries join the project's; an entry that clashes with a different one is a
    problem, never a silent overwrite.
    """
    problems: List[str] = []
    cache: Dict[str, Any] = {}
    catalog = dict(catalog)
    out: Dict[str, Dict[str, Any]] = {}
    for pname, doc in pipelines.items():
        nodes = doc.get("nodes") if isinstance(doc, dict) else None
        if not isinstance(nodes, dict) or not any(
            isinstance(n, dict) and str(n.get("use", "")).startswith(PIPELINE_PREFIX)
            for n in nodes.values()
        ):
            out[pname] = doc
            continue
        new_nodes: Dict[str, Any] = {}
        for iname, node in nodes.items():
            if not (
                isinstance(node, dict) and str(node.get("use", "")).startswith(PIPELINE_PREFIX)
            ):
                if iname in new_nodes:
                    problems.append(
                        f"{locate(('pipelines', pname, 'nodes', iname))} node '{iname}' is defined twice"
                    )
                new_nodes[iname] = node
                continue
            at = f"{locate(('pipelines', pname, 'nodes', iname, 'use'))} node '{iname}'"
            ref = str(node["use"])[len(PIPELINE_PREFIX) :].strip()
            extra = sorted(set(node) - {"use", "with", "description"})
            if extra:
                problems.append(
                    f"{at}: a subpipeline instance takes only use and with, not {', '.join(extra)}"
                )
                continue
            if not ref or "/" in ref or ".." in ref:
                problems.append(f"{at}: use must name a subpipeline in {PIPELINE_TEMPLATES_DIR}/")
                continue
            path = with_a_suffix(root, f"{PIPELINE_TEMPLATES_DIR}/{ref}")
            if not path.is_file():
                close = difflib.get_close_matches(ref, pipeline_template_names(root), n=1)
                hint = f" — did you mean '{close[0]}'?" if close else ""
                problems.append(
                    f"{at}: uses 'pipeline:{ref}', but {PIPELINE_TEMPLATES_DIR}/{ref}.yaml does not exist{hint}"
                )
                continue
            if ref not in cache:
                cache[ref] = read_template(path)
            template = cache[ref]
            if not isinstance(template, dict) or not isinstance(template.get("nodes"), dict):
                problems.append(f"{at}: subpipeline '{ref}' must be a mapping with 'nodes'")
                continue
            if any(
                isinstance(n, dict) and str(n.get("use", "")).startswith(PIPELINE_PREFIX)
                for n in template["nodes"].values()
            ):
                problems.append(
                    f"{at}: subpipeline '{ref}' uses another subpipeline; they cannot nest"
                )
                continue
            declared = template.get("params") or {}
            supplied = node.get("with") or {}
            if not isinstance(declared, dict) or not isinstance(supplied, dict):
                problems.append(f"{at}: 'with' and the subpipeline's params must be mappings")
                continue
            values = {**_param_values(declared), **supplied}
            bad = False
            for key in supplied:
                if key not in declared:
                    close = difflib.get_close_matches(str(key), [str(k) for k in declared], n=1)
                    hint = f" — did you mean '{close[0]}'?" if close else ""
                    problems.append(f"{at}: subpipeline '{ref}' has no parameter '{key}'{hint}")
                    bad = True
            body = {k: template.get(k) for k in ("nodes", "catalog") if template.get(k) is not None}
            for key in dict.fromkeys(_placeholders(body)):
                if key not in values:
                    problems.append(
                        f"{at}: subpipeline '{ref}' uses ${{params.{key}}}, which it does not declare"
                    )
                    bad = True
            for key, value in values.items():
                if value is None or value == REQUIRED:
                    problems.append(
                        f"{at}: subpipeline '{ref}' needs the parameter '{key}' (in 'with')"
                    )
                    bad = True
            if bad:
                continue
            try:
                expanded = _substitute(body, values)
            except ValueError as e:
                problems.append(f"{at}: subpipeline '{ref}': {e}")
                continue
            for name, entry in (expanded.get("catalog") or {}).items():
                if name in catalog and catalog[name] != entry:
                    problems.append(
                        f"{at}: subpipeline '{ref}' declares dataset '{name}', which the catalog "
                        "already declares differently"
                    )
                    bad = True
                else:
                    catalog[name] = entry
            for name, sub in expanded["nodes"].items():
                if name in new_nodes or name in nodes and name != iname:
                    problems.append(
                        f"{at}: subpipeline '{ref}' adds node '{name}', which the pipeline already has"
                    )
                    bad = True
                    continue
                new_nodes[name] = sub
        out[pname] = {**doc, "nodes": new_nodes}
    return out, catalog, problems
