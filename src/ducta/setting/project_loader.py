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

Load a format-2 project and compile it to the engine's five documents.

``ducta.yaml`` + ``catalog.yaml`` + ``pipelines/**/*.yaml``  →
``global_config``, ``pipelines_config``, ``nodes_config``, ``input_config``,
``output_config`` — the documents the engine, preflight and certificates read
(``config_fingerprint`` hashes them).

Steps: read the files (remembering where each key came from), apply the
environment's overrides, validate against ``project_schema``, check the
cross-file references, compile.
"""

from __future__ import annotations

import copy
import difflib
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional, Tuple, cast

import yaml  # type: ignore[import-untyped]
from loguru import logger
from pydantic import ValidationError

from ducta.setting.exceptions import ConfigurationError

if TYPE_CHECKING:
    from ducta.setting.contexts import Context
from ducta.setting import project_files as pf
from ducta.setting.project_defaults import apply_defaults, resolve_extends
from ducta.setting.project_schema import (
    PROJECT_FORMAT_VERSION,
    CatalogEntry,
    ChecksBlock,
    IngestNode,
    PipelineFile,
    ProjectFile,
    StreamNode,
    TransformNode,
)

PROJECT_FILE = "ducta.yaml"
CATALOG_FILE = "catalog.yaml"
PIPELINES_DIR = "pipelines"

#: format-2 placeholders → the names the engine's interpolator resolves.
_PLACEHOLDERS = {
    "${paths.input}": "${input_path}",
    "${paths.output}": "${output_path}",
    "${env}": "${environment}",
}


class ProjectConfigError(ConfigurationError):
    """One or more problems in a format-2 project, each located as file:line."""

    def __init__(self, problems: List[str]) -> None:
        self.problems = problems
        bullet = "\n  - "
        super().__init__(
            f"Invalid project configuration ({len(problems)} problem(s)):{bullet}"
            + bullet.join(problems)
        )


# ── detection ────────────────────────────────────────────────────────────────


def find_project_root(start: Path) -> Optional[Path]:
    """The directory holding a ``ducta.yaml`` / ``.toml`` / ``.json`` with ``version: 2``
    (``start`` or its ``config/``)."""
    for candidate in (start, start / "config"):
        if any(_declares_v2(f) for f in pf.find_files(candidate, "ducta")):
            return candidate
    return None


def project_file(root: Path) -> Path:
    """The project's ``ducta.*`` file (``ducta.yaml`` when there is none yet)."""
    found = pf.find_files(Path(root), "ducta")
    return found[0] if found else Path(root) / PROJECT_FILE


def _declares_v2(path: Path) -> bool:
    try:
        data = pf.load(path)
    except Exception:  # noqa: BLE001 — not ours to diagnose here
        return False
    return isinstance(data, dict) and data.get("version") == PROJECT_FORMAT_VERSION


# ── reading, with positions ──────────────────────────────────────────────────


@dataclass
class _Located:
    """Parsed documents plus where each key path was written."""

    project: Dict[str, Any]
    catalog: Dict[str, Any]
    pipelines: Dict[str, Dict[str, Any]]
    #: ("catalog", "silver.orders", "path") → "catalog.yaml:12"
    where: Dict[Tuple[str, ...], str] = field(default_factory=dict)
    pipeline_files: Dict[str, Path] = field(default_factory=dict)


def _read(
    path: Path, prefix: Tuple[str, ...], where: Dict[Tuple[str, ...], str], root: Path
) -> Any:
    text = path.read_text(encoding="utf-8")
    rel = str(path.relative_to(root))
    try:
        data = pf.parse(path, text)
        pf.index(path, text, prefix, where, rel)
    except ValueError as e:
        raise ProjectConfigError([f"{rel}: {e}"]) from e
    except yaml.YAMLError as e:
        raise ProjectConfigError([f"{rel}: not valid YAML — {e}"]) from e
    return data


def read_project(root: Path, *, expand: bool = True) -> _Located:
    """Read ``ducta.*``, ``catalog.*`` and every ``pipelines/**/*.*`` (YAML, TOML or JSON).

    ``expand=False`` leaves ``extends`` and ``defaults`` unresolved, which is how
    ``ducta config explain`` tells a value written in a file from one it inherited.
    """
    root = Path(root)
    where: Dict[Tuple[str, ...], str] = {}
    problems: List[str] = []
    singles: Dict[str, Path] = {}
    for stem in ("ducta", "catalog"):
        found = pf.find_files(root, stem)
        if len(found) > 1:
            names = " and ".join(f.name for f in found)
            problems.append(f"{names}: a project keeps one {stem} file; remove all but one")
        if found:
            singles[stem] = found[0]
    if problems:
        raise ProjectConfigError(problems)
    project = _read(singles.get("ducta", root / PROJECT_FILE), ("project",), where, root)
    catalog = _read(singles["catalog"], ("catalog",), where, root) if "catalog" in singles else {}
    pipelines: Dict[str, Dict[str, Any]] = {}
    files: Dict[str, Path] = {}
    pipeline_dir = root / PIPELINES_DIR
    candidates = (
        sorted(p for p in pipeline_dir.rglob("*") if p.suffix.lower() in pf.SUFFIXES)
        if pipeline_dir.is_dir()
        else []
    )
    for path in candidates:
        if not path.is_file():
            continue
        name = path.stem
        if name in pipelines:
            problems.append(
                f"{path.relative_to(root)}: pipeline '{name}' is already defined in "
                f"{files[name].relative_to(root)} — pipeline names come from file names "
                "and must be unique"
            )
            continue
        pipelines[name] = _read(path, ("pipelines", name), where, root)
        files[name] = path
    if problems:
        raise ProjectConfigError(problems)
    if not expand:
        return _Located(project, catalog, pipelines, where, files)
    pipelines, problems = resolve_extends(
        root, pipelines, lambda path: _read(path, ("templates", path.stem), where, root)
    )
    if problems:
        raise ProjectConfigError(problems)
    catalog, pipelines = apply_defaults(project, catalog, pipelines)
    return _Located(project, catalog, pipelines, where, files)


# ── environments ─────────────────────────────────────────────────────────────


def _deep_merge(base: Any, override: Any) -> Any:
    if isinstance(base, dict) and isinstance(override, dict):
        merged = dict(base)
        for key, value in override.items():
            merged[key] = _deep_merge(base.get(key), value) if key in base else copy.deepcopy(value)
        return merged
    return copy.deepcopy(override)  # scalars and lists replace


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


def environment_overrides(
    located: _Located, env: Optional[str], tree: Optional[Dict[str, Any]] = None
) -> Tuple[Optional[str], Dict[str, Any]]:
    """``(environment name, its overrides as a nested tree)``; ``(None, {})`` when it has none."""
    from ducta.setting.environments import get_base_environment, normalize_environment

    environments = located.project.get("environments") or {}
    if not env or not environments:
        return None, {}
    tree = tree if tree is not None else project_tree(located)
    active = normalize_environment(env) or env
    candidates = [active, get_base_environment(active)]
    name = next((c for c in candidates if isinstance(environments.get(c), dict)), None)
    if name is None:
        if active != "base":
            logger.info("No overrides for environment '{}' — using the base project", active)
        return None, {}
    overrides: Dict[str, Any] = {}
    for key, value in environments[name].items():
        if "." in key:
            overrides = _deep_merge(overrides, _expand_dotted(tree, key, value))
        else:
            overrides = _deep_merge(overrides, {key: value})
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


def apply_environment(located: _Located, env: Optional[str]) -> Dict[str, Any]:
    """The project tree ({settings, paths, catalog, pipelines, ...}) for ``env``."""
    tree = project_tree(located)
    name, overrides = environment_overrides(located, env, tree)
    if name is None:
        return tree
    logger.info("Applied '{}' environment overrides", name)
    return cast(Dict[str, Any], _deep_merge(tree, overrides))


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
        # Drop the discriminated-union tag pydantic inserts ('transform', ...):
        # it is not a key anyone wrote.
        loc = [p for p in err["loc"] if p not in ("transform", "ingest", "stream")]
        dotted = ".".join(str(p) for p in loc)
        msg = err["msg"].removeprefix("Value error, ")
        if err["type"] == "extra_forbidden" and loc:
            key = str(loc[-1])
            close = difflib.get_close_matches(key, _schema_keys(), n=1, cutoff=0.5)
            msg = f"unknown key '{key}'" + (f" — did you mean '{close[0]}'?" if close else "")
        out.append(
            f"{_locate(where, prefix, err['loc'])} {label}{'.' + dotted if dotted else ''}: {msg}"
        )
    return out


def validate_project(root: Path, env: Optional[str] = None) -> Project:
    """Read, apply ``env`` and validate; every problem is reported, not just the first."""
    root = Path(root)
    located = read_project(root)
    tree = apply_environment(located, env)
    where = located.where
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
        if dataset.checks is not None:
            scan(dataset.checks, ("catalog", dname, "checks"), f"catalog.{dname}.checks")
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


def _schema_keys() -> List[str]:
    """Every key the format-2 files accept, for suggesting a replacement for a typo."""
    from pydantic import BaseModel

    from ducta.setting import project_schema

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
                        f"{at} node '{nname}' reads '{ds}', which is not in catalog.yaml"
                        + _suggest(ds, catalog)
                    )
            for ds in node.outputs:
                if ds not in catalog:
                    problems.append(
                        f"{at} node '{nname}' writes '{ds}', which is not in catalog.yaml"
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
    problems += _path_checks(catalog, pipelines, where)
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


# ── compilation ──────────────────────────────────────────────────────────────


def _placeholders(value: Any) -> Any:
    if isinstance(value, str):
        for new, old in _PLACEHOLDERS.items():
            value = value.replace(new, old)
        return value
    if isinstance(value, dict):
        return {k: _placeholders(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_placeholders(v) for v in value]
    return value


def _drop_empty(d: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None and v != {} and v != []}


def _conventional_path(name: str) -> Optional[str]:
    parts = [p for p in name.replace("/", ".").split(".") if p]
    if len(parts) != 3:
        return None
    return "${output_path}/${environment}/" + "/".join(parts)


def _compile_dataset(name: str, entry: CatalogEntry, *, as_input: bool) -> Dict[str, Any]:
    out: Dict[str, Any] = {"format": entry.format}
    path = entry.path
    if path is None and as_input:
        # A dataset one node writes and another reads, declared once, without a
        # path: read it where the writer puts it by convention.
        path = _conventional_path(name)
    out.update(
        _drop_empty(
            {
                "filepath": path,
                "table_name": entry.table,
                "description": entry.description,
                "options": dict(entry.options) or None,
                "schema": entry.schema_def,
                "incremental": entry.incremental.model_dump() if entry.incremental else None,
            }
        )
    )
    if entry.read:
        out.update(
            _drop_empty({"versionAsOf": entry.read.version, "timestampAsOf": entry.read.timestamp})
        )
    if entry.write and not as_input:
        w = entry.write
        if w.options is not None:
            if w.options:
                out["options"] = dict(w.options)
            else:
                out.pop("options", None)
        out.update(
            _drop_empty(
                {
                    "write_mode": w.mode,
                    "merge": w.merge.model_dump(exclude_unset=True) if w.merge else None,
                    "partition": w.partition,
                    "overwrite_strategy": w.overwrite_strategy,
                    "partition_col": w.partition_col,
                    "replace_predicate": w.replace_predicate,
                    "overwrite_schema": w.overwrite_schema,
                }
            )
        )
    out.update(copy.deepcopy(entry.model_extra or {}))
    return cast(Dict[str, Any], _placeholders(out))


def _gate(gate: Any) -> Dict[str, Any]:
    d = gate.model_dump(exclude_unset=True)
    if "on_fail" in d:
        d["behavior"] = d.pop("on_fail")
    return cast(Dict[str, Any], d)


def _checks(block: ChecksBlock, gate_key: str) -> Dict[str, Any]:
    out = _drop_empty(
        {
            "fail_fast": block.fail_fast,
            "profile": block.profile,
            "dataset_name": block.dataset_name,
            "output": block.output,
            "checks": block.checks,
        }
    )
    if not block.enabled:
        out["enabled"] = False
    if block.gate is not None:
        out[gate_key] = _gate(block.gate)
    return out


def _compile_node(name: str, node: Any, catalog: Dict[str, CatalogEntry]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    common = {
        "description": node.description,
        "output": list(node.outputs) or None,
        "dependencies": list(node.after) or None,
        "retry": node.retry or None,
        "timeout": node.timeout_seconds,
        "on_missing_input": node.on_missing_input,
        "fail_fast": node.fail_fast,
    }
    if isinstance(node, TransformNode):
        module, _, function = node.run.partition(":")
        out.update({"module": module.strip(), "function": function.strip()})
        out["input"] = dict(node.inputs) if isinstance(node.inputs, dict) else list(node.inputs)
        out.update(
            _drop_empty(
                {
                    "run_in_process": node.run_in_process or None,
                    "execution_mode": node.execution_mode,
                    "execution_mode_max_rows": node.execution_mode_max_rows,
                    "ml_stage": node.ml_stage,
                    "split": node.split,
                    "hyperparams": node.hyperparams,
                    "model_version": node.model_version,
                    "metrics": node.metrics,
                }
            )
        )
        contracts = _input_contracts(node, catalog)
        if contracts:
            out["sanity_checks"] = {"inputs": contracts}
    elif isinstance(node, IngestNode):
        out["type"] = "ingestion"
        out.update(_drop_empty(node.ingest.model_dump(exclude_unset=True)))
    elif isinstance(node, StreamNode):
        out["type"] = "streaming"
        spec = node.stream.model_dump(exclude_unset=True, by_alias=True)
        if "transform" in spec:
            spec["function"] = spec.pop("transform")
        out.update(_drop_empty(spec))
    out.update(_drop_empty(common))
    if node.quality is not None:
        out["data_quality"] = _checks(node.quality, "quality_gate")
    return cast(Dict[str, Any], _placeholders(out))


def _input_contracts(node: TransformNode, catalog: Dict[str, CatalogEntry]) -> Dict[str, Any]:
    """Catalog contracts of the datasets this node reads, plus its own input_checks.

    Keyed by dataset. A node's own ``input_checks`` for a dataset replace that
    dataset's catalog contract for this node only.
    """
    params = node.inputs if isinstance(node.inputs, dict) else {}
    contracts: Dict[str, Any] = {}
    for ds in _node_inputs(node):
        entry = catalog.get(ds)
        if entry is not None and entry.checks is not None:
            contracts[ds] = _checks(entry.checks, "gate")
    for target, block in node.input_checks.items():
        ds = params.get(target, target)
        contracts[ds] = _checks(block, "gate")
    return contracts


def compile_project(project: Project) -> Dict[str, Dict[str, Any]]:
    """The five engine documents for a validated project."""
    settings = copy.deepcopy(project.project.settings)
    global_config = {
        "mode": "local",  # GlobalConfigSchema's default; the engine requires the key
        **settings,
        "project_name": project.project.project,
        "input_path": project.project.paths.input,
        "output_path": project.project.paths.output,
    }
    if project.project.metadata:
        global_config["metadata"] = copy.deepcopy(project.project.metadata)

    consumed: set = set()
    produced: set = set()
    nodes_config: Dict[str, Any] = {}
    pipelines_config: Dict[str, Any] = {}
    for pname, pipeline in project.pipelines.items():
        for nname, node in pipeline.nodes.items():
            consumed.update(_node_inputs(node))
            produced.update(node.outputs)
            nodes_config[nname] = _compile_node(nname, node, project.catalog)
        pipelines_config[pname] = _drop_empty(
            {
                "type": pipeline.type,
                "description": pipeline.description,
                "nodes": list(pipeline.nodes),
                "requires_dates": pipeline.requires_dates,
                "depends_on": list(pipeline.depends_on) or None,
                "reuse_if_materialized": pipeline.reuse_if_materialized,
                "spark_config": pipeline.spark_config,
                "split": pipeline.split,
                "hyperparams": pipeline.hyperparams,
                "hyperparams_config": pipeline.hyperparams_config,
                "model_version": pipeline.model_version,
            }
        )

    input_config: Dict[str, Any] = {}
    output_config: Dict[str, Any] = {}
    for name, entry in project.catalog.items():
        if name in produced:
            output_config[name] = _compile_dataset(name, entry, as_input=False)
        if name in consumed or name not in produced:
            input_config[name] = _compile_dataset(name, entry, as_input=True)

    return {
        "global_config": _placeholders(global_config),
        "pipelines_config": pipelines_config,
        "nodes_config": nodes_config,
        "input_config": input_config,
        "output_config": output_config,
    }


def load_project_v2(root: Path, env: Optional[str], allow_python_config: bool = True) -> "Context":
    """A :class:`Context` for the format-2 project at ``root``.

    ``allow_python_config`` gates importing ``quality.extensions`` modules,
    (the API server passes False).
    """
    from ducta.setting.contexts import Context

    project = validate_project(root, env)
    docs = compile_project(project)
    context = Context(
        global_config=docs["global_config"],
        pipelines_config=docs["pipelines_config"],
        nodes_config=docs["nodes_config"],
        input_config=docs["input_config"],
        output_config=docs["output_config"],
        env=env,
        allow_python_config=allow_python_config,
    )
    # Where the configuration came from, plus the format marker.
    setattr(context, "_config_file_path", str(project_file(root).resolve()))
    setattr(context, "config_paths", {})
    setattr(context, "project_format", PROJECT_FORMAT_VERSION)
    load_context_quality_extensions(context, allow_python_config)
    logger.info(
        "Loaded project '{}' (format 2): {} pipeline(s), {} dataset(s)",
        project.project.project,
        len(project.pipelines),
        len(project.catalog),
    )
    return context


def load_project(
    path: Optional[Any] = None, env: Optional[str] = None, allow_python_config: bool = True
) -> "Context":
    """The :class:`Context` of the project containing ``path`` (default: the cwd).

    ``path`` is the project directory, any directory or file inside it; the
    project is the nearest ``ducta.yaml`` with ``version: 2`` at or above it,
    as the CLI finds it. ``env`` applies that environment's overrides (default:
    the base project). Relative ``paths`` resolve against the working
    directory, as in a CLI run started from the project root.
    """
    start = Path(path) if path is not None else Path.cwd()
    if start.is_file():
        start = start.parent
    start = start.resolve()
    for directory in (start, *start.parents):
        root = find_project_root(directory)
        if root is not None:
            return load_project_v2(root, env, allow_python_config)
    raise ConfigurationError(
        f"No Ducta project found at or above {start} (looked for {PROJECT_FILE}, "
        "ducta.toml or ducta.json with `version: 2`). Create one with `ducta template`."
    )


def load_context_quality_extensions(ctx: Any, allow_python_config: bool) -> None:
    """Import the custom check modules named in ``quality.extensions``.

    Shared by every way a Context is built. It imports
    arbitrary Python modules named in config — the same trust boundary as
    PythonConfigLoader — so it must not run when ``allow_python_config`` is
    False (the API server's setting).
    """
    extensions = (ctx.global_config.get("quality") or {}).get("extensions") or []
    if extensions and not allow_python_config:
        logger.warning(
            "Skipping {} quality extension(s): allow_python_config is False, "
            "which forbids importing arbitrary Python modules from config.",
            len(extensions),
        )
    elif extensions:
        try:
            from ducta.check.core import load_quality_extensions

            load_quality_extensions(extensions)
        except Exception as exc:  # pragma: no cover
            logger.warning("Failed to load quality extensions: {}", exc)
