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

Apply an environment's overrides to a project's raw tree.
"""

from __future__ import annotations

import difflib
from typing import Any, Dict, List, Optional, Tuple, cast

from loguru import logger

from ducta.setting.project.reader import PROJECT_FILE, ProjectConfigError, _Located
from ducta.setting.utils import deep_merge

# ── environments ─────────────────────────────────────────────────────────────


def resolve_path(tree: Dict[str, Any], dotted: str) -> List[str]:
    """Split 'pipelines.etl.nodes.load.retry' into the keys it names.

    Dataset and pipeline names may contain dots themselves ("silver.orders"),
    so each step takes the *longest* run of segments that names an existing
    key at that level.
    """
    segments = dotted.split(".")
    path: List[str] = []
    node: Any = tree
    i = 0
    while i < len(segments):
        chosen = segments[i]
        step = 1
        if isinstance(node, dict):
            for j in range(len(segments), i, -1):
                candidate = ".".join(segments[i:j])
                if candidate in node:
                    chosen, step = candidate, j - i
                    break
        path.append(chosen)
        node = node.get(chosen) if isinstance(node, dict) else None
        i += step
    return path


def _expand_dotted(tree: Dict[str, Any], dotted: str, value: Any) -> Dict[str, Any]:
    """Turn 'pipelines.etl.nodes.load.retry' into a nested override."""
    nested: Any = value
    for key in reversed(resolve_path(tree, dotted)):
        nested = {key: nested}
    return cast(Dict[str, Any], nested)


def project_tree(located: _Located) -> Dict[str, Any]:
    """The base project as one tree: ``{settings, paths, ..., catalog, pipelines}``."""
    return {
        **{k: v for k, v in located.project.items() if k != "environments"},
        "catalog": located.catalog,
        "pipelines": located.pipelines,
    }


#: Containers whose children are named things: an override addressing a child that
#: is not there is a typo (or a stale name), not a request to create one.


_ENTITY_KINDS = {"pipelines": "pipeline", "nodes": "node", "catalog": "dataset"}


def _missing_entity(tree: Dict[str, Any], path: List[str]) -> Optional[str]:
    """Why a dotted override cannot apply: the pipeline, node or dataset it names is not there."""
    node: Any = tree
    for index, key in enumerate(path):
        if not isinstance(node, dict):
            return None
        container = path[index - 1] if index else None
        if key not in node:
            kind = _ENTITY_KINDS.get(container or "")
            if kind is None:
                return None  # a new setting or an optional key: the schema judges it
            near = difflib.get_close_matches(key, list(node), n=1, cutoff=0.6)
            if container == "nodes" and index >= 2:
                where = f"pipeline '{path[index - 2]}'"
            else:
                where = "the catalog" if container == "catalog" else "the project"
            hint = f" — did you mean '{near[0]}'?" if near else ""
            return f"there is no {kind} '{key}' in {where}{hint}"
        node = node[key]
    return None


def _environment_block(environments: Dict[str, Any], active: str) -> Optional[str]:
    """The key of ``environments`` that holds ``active``'s overrides, as the user spelled it.

    A block written as ``production`` or ``Prod`` serves ``--env prod``, and
    ``sandbox`` serves every ``sandbox_<dev>``: keys are compared by their
    normalized name, the exact match first.
    """
    from ducta.setting.environments import get_base_environment, normalize_environment

    by_normalized: Dict[str, str] = {}
    for key, block in environments.items():
        if isinstance(block, dict):
            by_normalized.setdefault(normalize_environment(str(key)) or str(key), str(key))
    for candidate in (active, get_base_environment(active)):
        if candidate in by_normalized:
            return by_normalized[candidate]
    return None


#: (project, environment) already warned about in this process: a run loads the project
#: more than once, and one warning is enough.
_WARNED_UNDECLARED: set = set()


def undeclared_environment_message(active: str, environments: Dict[str, Any]) -> str:
    """What to say when ``--env`` names none of the project's ``environments``."""
    declared = sorted(str(k) for k, v in environments.items() if isinstance(v, dict))
    close = difflib.get_close_matches(active, declared, n=1)
    hint = f" Did you mean '{close[0]}'?" if close else ""
    return (
        f"Environment '{active}' is not declared in ducta.yaml (declared: "
        f"{', '.join(declared) or 'none'}): running with the base project, writing under "
        f"its own folder.{hint}"
    )


def _warn_undeclared(project: Any, active: str, environments: Dict[str, Any]) -> None:
    """A typo in ``--env`` runs the base project; say so once, where it shows."""
    key = (str(project), active)
    if key in _WARNED_UNDECLARED:
        return
    _WARNED_UNDECLARED.add(key)
    logger.warning(undeclared_environment_message(active, environments))


def environment_overrides(
    located: _Located, env: Optional[str], tree: Optional[Dict[str, Any]] = None
) -> Tuple[Optional[str], Dict[str, Any]]:
    """``(environment name, its overrides as a nested tree)``; ``(None, {})`` when it has none.

    The name is the key as written in ``environments``.
    """
    from ducta.setting.environments import normalize_environment

    environments = located.project.get("environments") or {}
    if not env or not environments:
        return None, {}
    tree = tree if tree is not None else project_tree(located)
    active = normalize_environment(env) or env
    name = _environment_block(environments, active)
    if name is None:
        if active != "base":
            _warn_undeclared(located.project.get("project"), active, environments)
        return None, {}
    overrides: Dict[str, Any] = {}
    unreachable: List[str] = []
    for key, value in environments[name].items():
        if "." in key:
            missing = _missing_entity(tree, resolve_path(tree, key))
            if missing:
                at = located.where.get(("project", "environments", name, key), PROJECT_FILE)
                unreachable.append(f"{at} environments.{name}: '{key}' — {missing}")
                continue
            overrides = deep_merge(overrides, _expand_dotted(tree, key, value))
        else:
            overrides = deep_merge(overrides, {key: value})
    if unreachable:
        raise ProjectConfigError(unreachable)
    unknown = sorted(set(overrides) - {"settings", "paths", "catalog", "pipelines", "metadata"})
    if unknown:
        raise ProjectConfigError(
            [
                f"{located.where.get(('project', 'environments', name), PROJECT_FILE)}: "
                f"environments.{name} can override settings, paths, catalog and pipelines, "
                f"not {unknown}"
            ]
        )
    return name, overrides


_UNRESOLVED: Any = object()


def override_positions(
    located: _Located, env: Optional[str], tree: Dict[str, Any], name: Any = _UNRESOLVED
) -> Dict[Tuple[str, ...], str]:
    """Where, in ``ducta.yaml``, each value an environment overrides was written.

    Errors about a merged value are located through these, so a typo in
    ``environments.prod`` is reported at ``ducta.yaml``, not at the pipeline
    file whose key it addressed. ``name`` is the block ``apply_environment_named``
    already resolved; left out, it is resolved again.
    """
    environments = located.project.get("environments") or {}
    if name is _UNRESOLVED:
        name, _ = environment_overrides(located, env, tree)
    if name is None:
        return {}
    block = environments[name]
    found: Dict[Tuple[str, ...], str] = {}

    def keyed(path: Tuple[str, ...]) -> Tuple[str, ...]:
        # ducta.yaml's own sections are filed under ("project", ...).
        return ("project", *path) if path[0] in ("settings", "paths", "metadata") else path

    def mark(path: Tuple[str, ...], at: str) -> None:
        # The value itself always comes from here. A step on the way is claimed only
        # when it exists nowhere else (a whole new node), never taken from the file
        # that really declares it.
        for end in range(1, len(path) + 1):
            key = keyed(path[:end])
            if end == len(path) or key not in located.where:
                found[key] = at

    def walk(path: Tuple[str, ...], value: Any, source: Tuple[str, ...]) -> None:
        at = located.where.get(("project", "environments", name, *source), PROJECT_FILE)
        # A mapping the project also declares (`settings:`) stays where it is written: an
        # unknown key inside it was reported at the environment's `settings:` line.
        if not isinstance(value, dict) or keyed(path) not in located.where:
            mark(path, at)
        if isinstance(value, dict):
            for key, inner in value.items():
                walk((*path, str(key)), inner, (*source, str(key)))

    for key, value in block.items():
        path = tuple(resolve_path(tree, key)) if "." in key else (key,)
        walk(path, value, (key,))
    return found


def apply_environment_named(
    located: _Located, env: Optional[str], base: Optional[Dict[str, Any]] = None
) -> Tuple[Optional[str], Dict[str, Any]]:
    """``(block applied, project tree)`` for ``env``; ``base`` is ``project_tree(located)`` if known."""
    tree = base if base is not None else project_tree(located)
    name, overrides = environment_overrides(located, env, tree)
    if name is None:
        return None, tree
    logger.debug("Applied '{}' environment overrides", name)
    return name, cast(Dict[str, Any], deep_merge(tree, overrides))


def apply_environment(located: _Located, env: Optional[str]) -> Dict[str, Any]:
    """The project tree ({settings, paths, catalog, pipelines, ...}) for ``env``."""
    return apply_environment_named(located, env)[1]
