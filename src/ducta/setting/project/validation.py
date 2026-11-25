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

Validate a project: its schema, the references between files and the engine's constraints,
each problem located as ``file:line``.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from pydantic import ValidationError

from ducta.setting.project.overlay import (
    apply_environment_named,
    override_positions,
    project_tree,
)
from ducta.setting.project.reader import (
    CATALOG_FILE,
    ProjectConfigError,
    _conventional_path,
    read_project,
)
from ducta.setting.project.schema import (
    CatalogEntry,
    ChecksBlock,
    PipelineFile,
    ProjectFile,
    TransformNode,
)

# ── validation ───────────────────────────────────────────────────────────────


@dataclass
class Project:
    """A validated, environment-resolved format-2 project."""

    root: Path
    env: Optional[str]
    project: ProjectFile
    catalog: Dict[str, CatalogEntry]
    pipelines: Dict[str, PipelineFile]


def _locate(where: Dict[Tuple[str, ...], str], prefix: Tuple[str, ...], loc: Iterable[Any]) -> str:
    """Best file:line for a pydantic error location under ``prefix``."""
    path = list(prefix)
    best = where.get(tuple(path))
    for part in loc:
        candidate = tuple([*path, str(part)])
        if candidate in where:
            path.append(str(part))
            best = where[candidate]
        # union tags ('transform') and model names are not keys in the file
    return best or "?"


def _errors(
    e: ValidationError, where: Dict[Tuple[str, ...], str], prefix: Tuple[str, ...], label: str
) -> List[str]:
    out = []
    for err in e.errors():
        loc, node_kind = _without_union_tag(err["loc"])
        dotted = ".".join(str(p) for p in loc)
        msg = err["msg"].removeprefix("Value error, ")
        if err["type"] == "extra_forbidden" and loc:
            key = str(loc[-1])
            # A key written directly on a node is compared with that node
            # kind's keys: from every key in the schema, 'inputz' matched
            # 'input' (a key of another model), not 'inputs'.
            known = _node_keys(node_kind) if node_kind else _schema_keys()
            if key in known:
                # Valid somewhere else (a node's `inputs` written on the pipeline):
                # suggesting the key itself would read "did you mean 'inputs'?".
                msg = f"'{key}' is not valid at this level"
            else:
                close = difflib.get_close_matches(key, known, n=1, cutoff=0.5)
                msg = f"unknown key '{key}'" + (f" — did you mean '{close[0]}'?" if close else "")
        out.append(
            f"{_locate(where, prefix, err['loc'])} {label}{'.' + dotted if dotted else ''}: {msg}"
        )
    return out


def validate_project(root: Path, env: Optional[str] = None) -> Project:
    """Read, apply ``env`` and validate; every problem is reported, not just the first."""
    root = Path(root)
    located = read_project(root)
    base = project_tree(located)
    block, tree = apply_environment_named(located, env, base)
    where = {**located.where, **override_positions(located, env, base, block)}
    problems: List[str] = []

    project_doc = {k: v for k, v in tree.items() if k not in ("catalog", "pipelines")}
    project_doc["environments"] = located.project.get("environments") or {}
    project: Optional[ProjectFile] = None
    try:
        project = ProjectFile.model_validate(project_doc)
    except ValidationError as e:
        problems += _errors(e, where, ("project",), "")

    catalog: Dict[str, CatalogEntry] = {}
    for name, entry in (tree.get("catalog") or {}).items():
        try:
            catalog[name] = CatalogEntry.model_validate(entry or {})
        except ValidationError as e:
            problems += _errors(e, where, ("catalog", name), f"catalog.{name}")

    pipelines: Dict[str, PipelineFile] = {}
    for name, doc in (tree.get("pipelines") or {}).items():
        try:
            pipelines[name] = PipelineFile.model_validate(doc or {})
        except ValidationError as e:
            problems += _errors(e, where, ("pipelines", name), f"pipelines/{name}")

    if not problems and project is not None:
        problems += _check_params(project, catalog, pipelines, where)
        problems += _cross_checks(catalog, pipelines, where)
    if problems:
        raise ProjectConfigError(problems)
    assert project is not None
    return Project(root, env, project, catalog, pipelines)


def _first_known(where: Dict[Tuple[str, ...], str], *paths: Tuple[str, ...]) -> str:
    return next((where[p] for p in paths if p in where), "?")


def _check_params(
    project: ProjectFile,
    catalog: Dict[str, CatalogEntry],
    pipelines: Dict[str, PipelineFile],
    where: Dict[Tuple[str, ...], str],
) -> List[str]:
    """Unknown checks, unknown parameters and parameters of the wrong type, located.

    A block can list its checks under ``checks:`` or directly, so a check is
    looked up at both places in the positions index.
    """
    from ducta.check import checks as _builtin_checks  # noqa: F401  registers the built-ins
    from ducta.check.core import COMMON_CHECK_PARAMS, QUALITY_CHECKS_REGISTRY
    from ducta.check.params import problems_in, schema_for

    extensions = (project.settings.get("quality") or {}).get("extensions") or []
    found: List[str] = []

    def scan(block: ChecksBlock, base: Tuple[str, ...], label: str) -> None:
        for cname, entry in block.checks.items():
            at = _first_known(where, (*base, "checks", cname), (*base, cname), base)
            name = entry.get("type") or cname
            check_class = QUALITY_CHECKS_REGISTRY.get(name)
            here = f"{at} {label}.{cname}"
            if check_class is None:
                # A custom check may be registered by code this loader never
                # imports, so only a near miss of a built-in is called a typo.
                close = difflib.get_close_matches(name, list(QUALITY_CHECKS_REGISTRY), 1, 0.75)
                if close and not extensions:
                    found.append(f"{here}: unknown check — did you mean '{close[0]}'?")
                continue
            declared = schema_for(name, check_class)
            known = set(declared or ()) | set(COMMON_CHECK_PARAMS)
            declared_keys = getattr(check_class, "CONFIG_PARAMS", None)
            if declared_keys is not None:
                known |= set(declared_keys)
            elif declared is None:
                continue  # declares nothing: accepted as before
            for key, value in entry.items():
                if key.startswith("_"):
                    continue
                if key not in known:
                    found.append(f"{here}: unknown parameter '{key}'{_suggest(key, known)}")
                elif declared and key in declared:
                    found.extend(f"{here}: {m}" for m in problems_in(value, declared[key], key))

    for dname, dataset in catalog.items():
        if dataset.quality is not None:
            scan(dataset.quality, ("catalog", dname, "quality"), f"catalog.{dname}.quality")
    for pname, pipeline in pipelines.items():
        for nname, node in pipeline.nodes.items():
            base = ("pipelines", pname, "nodes", nname)
            label = f"pipelines/{pname}.nodes.{nname}"
            if node.quality is not None:
                scan(node.quality, (*base, "quality"), f"{label}.quality")
            for target, block in getattr(node, "input_checks", {}).items():
                scan(block, (*base, "input_checks", target), f"{label}.input_checks.{target}")
    return found


def _suggest(name: str, options: Iterable[str]) -> str:
    close = difflib.get_close_matches(name, list(options), n=1, cutoff=0.6)
    return f" (did you mean '{close[0]}'?)" if close else ""


_NODE_KINDS = ("transform", "ingest", "stream")


def _without_union_tag(loc: Iterable[Any]) -> Tuple[List[Any], Optional[str]]:
    """``loc`` without the node-kind tag pydantic inserts, and that kind when the
    error is a key written directly on the node.

    The tag is not a key anyone wrote; it sits right after the node's name
    (``nodes.<name>.<tag>.<key>``). Only that position is dropped: a node
    named ``transform`` used to lose its name too.
    """
    parts = list(loc)
    for i in range(2, len(parts)):
        if parts[i - 2] == "nodes" and parts[i] in _NODE_KINDS:
            direct = len(parts) == i + 2
            return parts[:i] + parts[i + 1 :], (str(parts[i]) if direct else None)
    return parts, None


def _node_keys(kind: str) -> List[str]:
    """The keys a node of ``kind`` accepts."""
    from pydantic import BaseModel

    from ducta.setting.project.schema import IngestNode, StreamNode

    models: Dict[str, type[BaseModel]] = {
        "transform": TransformNode,
        "ingest": IngestNode,
        "stream": StreamNode,
    }
    model = models[kind]
    return sorted(field.alias or name for name, field in model.model_fields.items())


def _schema_keys() -> List[str]:
    """Every key the format-2 files accept, for suggesting a replacement for a typo."""
    from pydantic import BaseModel

    from ducta.setting.project import schema as project_schema

    keys = set()
    for obj in vars(project_schema).values():
        if isinstance(obj, type) and issubclass(obj, BaseModel) and obj is not BaseModel:
            for name, field in obj.model_fields.items():
                keys.add(field.alias or name)
    return sorted(keys)


def _node_inputs(node: Any) -> List[str]:
    if isinstance(node, TransformNode):
        return list(node.inputs.values()) if isinstance(node.inputs, dict) else list(node.inputs)
    return []


#: Check parameters that name another catalog dataset the check reads.


_CHECK_REFERENCE_KEYS = ("reference_dataset", "reference")


def _check_references(node: Any) -> List[str]:
    """Datasets a node's output checks compare against (``prediction_drift``'s
    ``reference``, ``referential_integrity``'s ``reference_dataset``...): read at
    run time like an input, so they must be in the catalog and readable."""
    block = getattr(node, "quality", None)
    checks = getattr(block, "checks", None) or {}
    return sorted(
        {
            value
            for cfg in checks.values()
            if isinstance(cfg, dict)
            for key, value in cfg.items()
            if key in _CHECK_REFERENCE_KEYS and isinstance(value, str) and value
        }
    )


def _cross_checks(
    catalog: Dict[str, CatalogEntry],
    pipelines: Dict[str, PipelineFile],
    where: Dict[Tuple[str, ...], str],
) -> List[str]:
    problems: List[str] = []
    owner: Dict[str, str] = {}
    producers: Dict[str, str] = {}
    for pname, pipeline in pipelines.items():
        for nname, node in pipeline.nodes.items():
            at = where.get(("pipelines", pname, "nodes", nname), f"pipelines/{pname}")
            if nname in owner:
                problems.append(
                    f"{at} node '{nname}' is also defined in pipeline '{owner[nname]}' — node "
                    "names are unique across the project (certificates and the run ledger "
                    "identify nodes by name)"
                )
            owner.setdefault(nname, pname)
            for ds in _node_inputs(node):
                if ds not in catalog:
                    problems.append(
                        f"{at} node '{nname}' reads '{ds}', which is not in the catalog"
                        + _suggest(ds, catalog)
                    )
            for ds in _check_references(node):
                if ds not in catalog:
                    problems.append(
                        f"{at} node '{nname}': a quality check compares with '{ds}', which "
                        "is not in the catalog" + _suggest(ds, catalog)
                    )
            for ds in node.outputs:
                if ds not in catalog:
                    problems.append(
                        f"{at} node '{nname}' writes '{ds}', which is not in the catalog"
                        + _suggest(ds, catalog)
                    )
                elif ds in producers:
                    problems.append(
                        f"{at} '{ds}' is written by both '{producers[ds]}' and '{nname}'"
                    )
                producers.setdefault(ds, nname)
            for dep in node.after:
                if dep not in pipeline.nodes:
                    problems.append(
                        f"{at} node '{nname}': after '{dep}' is not a node of pipeline "
                        f"'{pname}'" + _suggest(dep, pipeline.nodes)
                    )
            if isinstance(node, TransformNode):
                reads = set(_node_inputs(node))
                params = set(node.inputs) if isinstance(node.inputs, dict) else set()
                for target in node.input_checks:
                    if target not in reads and target not in params:
                        problems.append(
                            f"{at} node '{nname}': input_checks '{target}' is neither an "
                            "input parameter nor a dataset it reads"
                        )
        for dep in pipeline.depends_on:
            if dep not in pipelines:
                problems.append(
                    f"{where.get(('pipelines', pname), 'pipelines/' + pname)} pipeline "
                    f"'{pname}': depends_on '{dep}' is not a pipeline" + _suggest(dep, pipelines)
                )
        problems += _retrain_checks(pname, pipeline, pipelines, where)
    problems += _cycle_checks(pipelines, producers, where)
    problems += _path_checks(catalog, pipelines, where)
    return problems


def _retrain_checks(
    pname: str,
    pipeline: PipelineFile,
    pipelines: Dict[str, PipelineFile],
    where: Dict[Tuple[str, ...], str],
) -> List[str]:
    """``retrain.run`` is another ML pipeline of the project, with no ``retrain`` of its own."""
    spec = pipeline.retrain
    if spec is None:
        return []
    at = f"{where.get(('pipelines', pname), 'pipelines/' + pname)} pipeline '{pname}': retrain"
    target = pipelines.get(spec.run)
    if target is None:
        return [f"{at} runs '{spec.run}', which is not a pipeline" + _suggest(spec.run, pipelines)]
    if spec.run == pname:
        return [f"{at} cannot run the pipeline itself"]
    problems: List[str] = []
    if target.type != "ml":
        problems.append(f"{at} runs '{spec.run}', a {target.type} pipeline; it must be type: ml")
    if target.retrain is not None:
        problems.append(
            f"{at} runs '{spec.run}', which has a retrain of its own: one retrain may not "
            "trigger another"
        )
    return problems


def _cycle_checks(
    pipelines: Dict[str, PipelineFile],
    producers: Dict[str, str],
    where: Dict[Tuple[str, ...], str],
) -> List[str]:
    """A node that (through ``after`` or the data it reads) waits for itself, or pipelines
    whose ``depends_on`` loop. Caught here so every way of loading a project catches it,
    not only the CLI's preflight."""
    from ducta.setting.dependency_resolver import GraphCycleError, detect_cycles_dfs

    problems: List[str] = []
    nodes = {
        nname: (pname, node)
        for pname, pipeline in pipelines.items()
        for nname, node in pipeline.nodes.items()
    }
    graph: Dict[str, List[str]] = {}
    for nname, (pname, node) in nodes.items():
        needs = {d for d in node.after if d in nodes}
        # Reading what you also write (an upsert) is not waiting for yourself.
        needs |= {producers[ds] for ds in _node_inputs(node) if ds in producers} - {nname}
        graph[nname] = sorted(needs)
    try:
        detect_cycles_dfs(graph)
    except GraphCycleError as e:
        first = e.cycle[0] if e.cycle else next(iter(nodes), "?")
        pname = nodes[first][0] if first in nodes else "?"
        at = where.get(("pipelines", pname, "nodes", first), f"pipelines/{pname}")
        problems.append(
            f"{at} nodes wait for each other: {' → '.join(e.cycle)} (through `after` or the "
            "datasets they read and write)"
        )
    pipeline_graph = {
        p: [d for d in pl.depends_on if d in pipelines] for p, pl in pipelines.items()
    }
    try:
        detect_cycles_dfs(pipeline_graph)
    except GraphCycleError as e:
        first = e.cycle[0] if e.cycle else "?"
        at = where.get(("pipelines", first), f"pipelines/{first}")
        problems.append(f"{at} pipelines depend on each other: {' → '.join(e.cycle)}")
    return problems


def _path_checks(
    catalog: Dict[str, CatalogEntry],
    pipelines: Dict[str, PipelineFile],
    where: Dict[Tuple[str, ...], str],
) -> List[str]:
    """Every dataset a node touches must resolve to a location."""
    touched = set()
    for pipeline in pipelines.values():
        for node in pipeline.nodes.values():
            touched.update(_node_inputs(node))
            touched.update(node.outputs)
    problems = []
    for name in sorted(touched & set(catalog)):
        entry = catalog[name]
        extras = entry.model_extra or {}
        if entry.path or entry.table or extras.get("query") or extras.get("catalog_name"):
            continue
        if _conventional_path(name) is None:
            problems.append(
                f"{where.get(('catalog', name), CATALOG_FILE)} dataset '{name}' has no 'path' "
                "and its name is not schema.sub_folder.table, so there is nowhere to derive "
                "one from — give it a path"
            )
    return problems
