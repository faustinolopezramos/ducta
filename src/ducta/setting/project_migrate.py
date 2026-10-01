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

Migrate a format-1 project to format 2 — and prove the result is equivalent.

``migrate(root)`` reads the project's raw format-1 documents for the base and
every environment, decompiles them to a format-2 tree (environments reduced to
what actually differs), then compiles that tree back with the format-2 loader
and compares it, environment by environment, with the original — after
removing only what format 2 deliberately drops (see :func:`canonical`). Any
difference aborts the migration: nothing is written that would run
differently.
"""

from __future__ import annotations

import copy
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, cast

import yaml  # type: ignore[import-untyped]

from ducta.setting.exceptions import ConfigurationError
from ducta.setting.project_loader import (
    CATALOG_FILE,
    PIPELINES_DIR,
    PROJECT_FILE,
    _conventional_path,
    compile_project,
    find_project_root,
    validate_project,
)

_DOCS = ("global_config", "pipelines_config", "nodes_config", "input_config", "output_config")
_ENV_FILES = ("environment", "settings")
_SCHEMA_DIR = ".ducta/schema"


class MigrationError(ConfigurationError):
    def __init__(self, problems: List[str]) -> None:
        self.problems = problems
        super().__init__("Cannot migrate this project to format 2:\n  - " + "\n  - ".join(problems))


@dataclass
class MigrationResult:
    project: Dict[str, Any]
    catalog: Dict[str, Any]
    pipelines: Dict[str, Dict[str, Any]]
    environments: List[str]
    #: Things the migration changed on purpose, for the summary.
    notes: List[str] = field(default_factory=list)
    legacy_files: List[Path] = field(default_factory=list)


# ── reading format 1 (raw, uninterpolated) ───────────────────────────────────


def _load(path: Path) -> Dict[str, Any]:
    from ducta.setting.loaders import ConfigLoaderFactory

    data = ConfigLoaderFactory().load_config(str(path))
    return data if isinstance(data, dict) else {}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    from ducta.setting.utils import deep_merge_dicts

    return deep_merge_dicts(base, override)


def _find_env_root(root: Path) -> Optional[Path]:
    for stem in _ENV_FILES:
        for ext in (".yaml", ".yml", ".json", ".toml"):
            candidate = root / f"{stem}{ext}"
            if candidate.is_file() and "env_config" in _load(candidate):
                return candidate
    return None


def read_format1(root: Path) -> Tuple[Dict[str, Dict[str, Dict[str, Any]]], List[Path]]:
    """``{env: {doc_name: raw_document}}`` for base and every environment, plus the files read.

    Mirrors the format-1 loader: an environment's documents *replace* the
    base's, except ``global_config``, which is deep-merged over it.
    """
    if _is_layered(root):
        raise MigrationError(
            [
                "layered projects (ducta.yaml with layers:) are not migrated automatically "
                "yet: migrate each layer's directory on its own"
            ]
        )

    env_root = _find_env_root(root)
    if env_root is not None:
        spec = _load(env_root)
        base_dir = (env_root.parent / (spec.get("base_path") or ".")).resolve()
        env_config: Dict[str, Dict[str, str]] = spec["env_config"]
        base_paths = env_config.get("base", {})
        result: Dict[str, Dict[str, Dict[str, Any]]] = {}
        files = {env_root}
        for env in env_config:
            paths = {**base_paths, **env_config.get(env, {})}
            docs: Dict[str, Dict[str, Any]] = {}
            for doc in _DOCS:
                rel = paths.get(f"{doc}_path")
                if not rel:
                    raise MigrationError([f"env_config.{env} has no {doc}_path"])
                path = base_dir / rel
                files.add(path)
                docs[doc] = _load(path) if path.is_file() else {}
            base_global = base_paths.get("global_config_path")
            env_global = env_config.get(env, {}).get("global_config_path")
            if env != "base" and base_global and env_global and base_global != env_global:
                docs["global_config"] = _deep_merge(
                    _load(base_dir / base_global), docs["global_config"]
                )
            result[env] = docs
        if "base" not in result and result:
            result["base"] = result[next(iter(result))]
        return result, sorted(files)

    bundle = _find(root, *_BUNDLE_STEMS)
    if bundle is not None:
        data = _load(bundle)
        if _is_bundle(data):
            return {"base": {doc: copy.deepcopy(data[doc]) for doc in _DOCS}}, [bundle]

    conv = _dir_convention_paths(root)
    if conv is not None:
        docs = {doc: _load(Path(conv[doc])) for doc in _DOCS}
        return {"base": docs}, sorted(Path(p) for p in conv.values())

    global_file = _find(root, "global", "global_config")
    grouped = _find(root, "pipeline")
    if global_file is not None and grouped is not None:
        g = _load(grouped)
        docs = {"global_config": _load(global_file)}
        for doc, section in _QUICKSTART_SECTIONS.items():
            docs[doc] = g.get(section, {}) or {}
        return {"base": docs}, [global_file, grouped]

    raise MigrationError([f"no format-1 configuration found in {root}"])


def _apply_inline_environments(
    docs: Dict[str, Dict[str, Any]], env: str
) -> Dict[str, Dict[str, Any]]:
    """Resolve format 1's other per-environment mechanism: global_config.environments."""
    from ducta.setting.environments import get_base_environment, normalize_environment

    docs = copy.deepcopy(docs)
    inline = docs["global_config"].pop("environments", None)
    if isinstance(inline, dict) and env != "base":
        active = normalize_environment(env) or env
        for candidate in (active, get_base_environment(active)):
            if isinstance(inline.get(candidate), dict):
                docs["global_config"] = _deep_merge(docs["global_config"], inline[candidate])
                break
    return docs


# The format-1 layouts, as far as reading them for migration needs. This module
# is the only place in Ducta that still understands them.
_CONFIG_EXTS = (".yaml", ".yml", ".json", ".toml")
_BUNDLE_STEMS = ("ducta", "config", "bundle")
_DIR_CONVENTION = {
    "global_config": ("global_config", "global"),
    "pipelines_config": ("pipelines",),
    "nodes_config": ("nodes",),
    "input_config": ("input",),
    "output_config": ("output",),
}
_QUICKSTART_SECTIONS = {
    "pipelines_config": "pipelines",
    "nodes_config": "nodes",
    "input_config": "input",
    "output_config": "output",
}
_LAYER_DIRS = ("bronze", "silver", "gold", "ml")


def _find(directory: Path, *stems: str) -> Optional[Path]:
    for stem in stems:
        for ext in _CONFIG_EXTS:
            candidate = directory / f"{stem}{ext}"
            if candidate.is_file():
                return candidate
    return None


def _is_bundle(data: Dict[str, Any]) -> bool:
    return "env_config" not in data and all(k in data for k in _DOCS)


def _dir_convention_paths(root: Path) -> Optional[Dict[str, str]]:
    result: Dict[str, str] = {}
    for doc, stems in _DIR_CONVENTION.items():
        found = next(
            (f for d in (root, root / "config") if d.is_dir() for f in [_find(d, *stems)] if f),
            None,
        )
        if found is None:
            return None
        result[doc] = str(found)
    return result


def _is_layered(root: Path) -> bool:
    """A format-1 multi-layer project: a `ducta.*` layers manifest, or
    bronze/silver/gold/ml directories each with their own configuration."""
    manifest = _find(root, "ducta")
    if manifest is not None:
        data = _load(manifest)
        project = data.get("project")
        if data.get("version") != 2 and (
            (isinstance(project, dict) and str(project.get("type", "")).lower() == "layered")
            or isinstance(data.get("layers"), dict)
        ):
            return True
    return any(
        (root / layer / "config").is_dir() and _find(root / layer, "global") is not None
        for layer in _LAYER_DIRS
    )


# ── decompiling to a format-2 tree ───────────────────────────────────────────

_PLACEHOLDERS_BACK = {
    "${input_path}": "${paths.input}",
    "${output_path}": "${paths.output}",
    "${environment}": "${env}",
}


def _back(value: Any) -> Any:
    if isinstance(value, str):
        for old, new in _PLACEHOLDERS_BACK.items():
            value = value.replace(old, new)
        return value
    if isinstance(value, dict):
        return {k: _back(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_back(v) for v in value]
    return value


def _clean(d: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None and v != [] and v != {}}


def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [str(v) for v in value.values()]
    return [str(v) for v in value]


def _gate_back(gate: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(gate, dict):
        return None
    g = dict(gate)
    if "behavior" in g:
        g["on_fail"] = g.pop("behavior")
    return g


def _block_back(
    block: Dict[str, Any], gate_key: str, problems: List[str], where: str
) -> Dict[str, Any]:
    known = {
        "enabled",
        "fail_fast",
        "profile",
        "checks",
        "dataset_name",
        "output",
        gate_key,
        "input_index",
        "run_id",
        "inputs",
    }
    for key in block:
        if key not in known:
            problems.append(f"{where}: key '{key}' has no format-2 equivalent")
    out = _clean(
        {
            "checks": block.get("checks") or None,
            "fail_fast": block.get("fail_fast"),
            "profile": block.get("profile"),
            "dataset_name": block.get("dataset_name"),
            "output": block.get("output"),
            "gate": _gate_back(block.get(gate_key)),
        }
    )
    if block.get("enabled") is False:
        out["enabled"] = False
    return out


_TRANSFORM_KEYS = {
    "description": "description",
    "retry": "retry",
    "timeout": "timeout_seconds",
    "on_missing_input": "on_missing_input",
    "fail_fast": "fail_fast",
    "run_in_process": "run_in_process",
    "execution_mode": "execution_mode",
    "execution_mode_max_rows": "execution_mode_max_rows",
    "ml_stage": "ml_stage",
    "split": "split",
    "hyperparams": "hyperparams",
    "model_version": "model_version",
    "metrics": "metrics",
}
_INGEST_KEYS = ("source", "sources", "table", "query", "columns", "where", "options")
_HANDLED = {
    "module",
    "function",
    "input",
    "output",
    "dependencies",
    "depends_on",
    "name",
    "type",
    "data_quality",
    "sanity_checks",
}


def _producers(nodes: Dict[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for name, node in nodes.items():
        for ds in _as_list((node or {}).get("output")):
            out.setdefault(ds, name)
    return out


def _decompile_node(
    name: str, node: Dict[str, Any], producers: Dict[str, str], problems: List[str]
) -> Dict[str, Any]:
    where = f"node '{name}'"
    ntype = str(node.get("type") or "batch").lower()
    reads = _as_list(node.get("input")) if ntype not in ("streaming",) else []
    inferred = {producers[ds] for ds in reads if ds in producers}
    declared = _as_list(node.get("dependencies")) + _as_list(node.get("depends_on"))
    after = [d for d in dict.fromkeys(declared) if d not in inferred]
    out: Dict[str, Any] = {}

    if ntype == "ingestion":
        out["kind"] = "ingest"
        out["ingest"] = _clean({k: node.get(k) for k in _INGEST_KEYS})
        handled = _HANDLED | set(_INGEST_KEYS) | set(_TRANSFORM_KEYS)
    elif ntype == "streaming":
        out["kind"] = "stream"
        stream = {k: v for k, v in node.items() if k not in _HANDLED and k not in _TRANSFORM_KEYS}
        if "function" in node:
            stream["transform"] = node["function"]
        stream.update({k: node[k] for k in ("input", "output") if k in node})
        out["stream"] = stream
        handled = set(node)  # the stream block carries everything else
    else:
        module, function = node.get("module"), node.get("function")
        if not isinstance(module, str) or not isinstance(function, str):
            problems.append(f"{where}: needs 'module' and 'function' strings to become 'run'")
        out["run"] = f"{module}:{function}"
        raw_input = node.get("input")
        out["inputs"] = dict(raw_input) if isinstance(raw_input, dict) else _as_list(raw_input)
        handled = _HANDLED | set(_TRANSFORM_KEYS)

    if ntype != "streaming":
        out["outputs"] = _as_list(node.get("output"))
    for old, new in _TRANSFORM_KEYS.items():
        if old in node and node[old] is not None:
            if (
                ntype != "batch"
                and ntype not in ("ml", "hybrid")
                and old
                not in (
                    "description",
                    "retry",
                    "timeout",
                    "on_missing_input",
                    "fail_fast",
                )
            ):
                continue
            out[new] = node[old]
    if out.get("retry") == 0:
        out.pop("retry")
    if after:
        out["after"] = after
    if isinstance(node.get("data_quality"), dict):
        out["quality"] = _block_back(
            node["data_quality"], "quality_gate", problems, f"{where}.data_quality"
        )

    sanity = node.get("sanity_checks")
    if isinstance(sanity, dict):
        if ntype in ("ingestion", "streaming"):
            problems.append(f"{where}: sanity_checks on a {ntype} node have no format-2 equivalent")
        elif isinstance(sanity.get("inputs"), dict):
            out["input_checks"] = {
                ds: _block_back(b, "gate", problems, f"{where}.sanity_checks.inputs.{ds}")
                for ds, b in sanity["inputs"].items()
            }
        elif reads:
            idx = int(sanity.get("input_index", 0) or 0)
            if idx >= len(reads):
                idx = 0  # what the engine falls back to
            out["input_checks"] = {
                reads[idx]: _block_back(sanity, "sanity_gate", problems, f"{where}.sanity_checks")
            }

    for key in node:
        if key not in handled and key not in ("timeout",):
            problems.append(f"{where}: key '{key}' is not a node setting Ducta reads")
    return cast(Dict[str, Any], _back(out))


def _decompile_dataset(
    name: str, inp: Optional[Dict[str, Any]], outp: Optional[Dict[str, Any]], problems: List[str]
) -> Dict[str, Any]:
    from ducta.setting.project_schema import DATASET_ENGINE_KEYS

    where = f"dataset '{name}'"
    inp, outp = inp or {}, outp or {}
    fmt_in = _fmt(inp.get("format"))
    fmt_out = _fmt(outp.get("format"))
    if fmt_in and fmt_out and fmt_in != fmt_out:
        problems.append(f"{where}: read as '{fmt_in}' but written as '{fmt_out}'")
    entry: Dict[str, Any] = {"format": fmt_out or fmt_in}

    path_in, path_out = inp.get("filepath"), outp.get("filepath")
    if path_out:
        entry["path"] = path_out
        if path_in and path_in != path_out:
            problems.append(f"{where}: read from '{path_in}' but written to '{path_out}'")
    elif path_in:
        conventional = _conventional_path(name)
        if outp and conventional and path_in == conventional:
            pass  # read where the writer writes by convention: no path needed
        elif outp:
            problems.append(
                f"{where}: written to its conventional location but read from '{path_in}' — "
                "format 2 has one location per dataset"
            )
        else:
            entry["path"] = path_in

    entry.update(
        _clean(
            {
                "table": outp.get("table_name") or inp.get("table_name"),
                "description": outp.get("description") or inp.get("description"),
                "schema": inp.get("schema") or outp.get("schema"),
                "incremental": inp.get("incremental"),
            }
        )
    )
    opts_in, opts_out = inp.get("options") or {}, outp.get("options") or {}
    if opts_in:
        entry["options"] = opts_in
    read = _clean(
        {
            "version": inp.get("versionAsOf", inp.get("version")),
            "timestamp": inp.get("timestampAsOf", inp.get("timestamp")),
        }
    )
    if read:
        entry["read"] = read
    if outp:
        write = _clean(
            {
                # Format 1 appended when write_mode was unset; format 2
                # overwrites. Say it explicitly so the behaviour survives.
                "mode": outp.get("write_mode") or "append",
                "merge": outp.get("merge"),
                "partition": outp.get("partition"),
                "overwrite_strategy": outp.get("overwrite_strategy"),
                "partition_col": outp.get("partition_col"),
                "replace_predicate": outp.get("replace_predicate"),
                "overwrite_schema": outp.get("overwrite_schema"),
            }
        )
        if opts_out and opts_out != opts_in:
            write["options"] = opts_out
        elif opts_in and not opts_out:
            write["options"] = {}
        entry["write"] = write

    named = {
        "format",
        "filepath",
        "table_name",
        "description",
        "schema",
        "incremental",
        "options",
        "versionAsOf",
        "version",
        "timestampAsOf",
        "timestamp",
        "write_mode",
        "merge",
        "partition",
        "overwrite_strategy",
        "partition_col",
        "replace_predicate",
        "overwrite_schema",
    }
    for side in (inp, outp):
        for key, value in side.items():
            if key in named:
                continue
            if key in DATASET_ENGINE_KEYS:
                entry[key] = value
            else:
                problems.append(f"{where}: key '{key}' is not a dataset setting Ducta reads")
    return cast(Dict[str, Any], _back(entry))


def _fmt(value: Any) -> Optional[str]:
    if value is None:
        return None
    return str(getattr(value, "value", value)).lower()


def decompile(
    docs: Dict[str, Dict[str, Any]], project_name: str, problems: List[str], notes: List[str]
) -> Dict[str, Any]:
    """One environment's format-1 documents → a format-2 tree."""
    from ducta.setting.schemas import _RUNTIME_GLOBAL_CONFIG_KEYS, GlobalConfigSchema

    g = copy.deepcopy(docs["global_config"])
    g.pop("environments", None)
    known = set(GlobalConfigSchema.model_fields) | set(_RUNTIME_GLOBAL_CONFIG_KEYS)
    metadata = dict(g.pop("metadata", None) or {})
    settings: Dict[str, Any] = {}
    for key, value in g.items():
        if key in ("input_path", "output_path", "project_name"):
            continue
        if key in known:
            settings[key] = value
        else:
            metadata.setdefault("unrecognized_settings", {})[key] = value
            note = f"global_config.{key} is not a Ducta setting — moved to metadata.unrecognized_settings"
            if note not in notes:
                notes.append(note)

    tree: Dict[str, Any] = {
        "version": 2,
        "project": str(g.get("project_name") or project_name),
        "paths": {
            "input": str(g.get("input_path", "data")),
            "output": str(g.get("output_path", "data")),
        },
        "settings": _back(settings),
    }
    if metadata:
        tree["metadata"] = metadata

    nodes = docs["nodes_config"] or {}
    producers = _producers(nodes)
    owner: Dict[str, str] = {}
    pipelines: Dict[str, Any] = {}
    for pname, pdoc in (docs["pipelines_config"] or {}).items():
        pdoc = pdoc or {}
        members = [
            str(m)
            for m in (
                n if isinstance(n, str) else (n or {}).get("name") for n in pdoc.get("nodes", [])
            )
            if m
        ]
        pnodes: Dict[str, Any] = {}
        for nname in members:
            if nname in owner:
                problems.append(
                    f"node '{nname}' is used by pipelines '{owner[nname]}' and '{pname}' — "
                    "format 2 needs one node per pipeline; duplicate it under another name"
                )
                continue
            owner[nname] = pname
            if nname not in nodes:
                problems.append(f"pipeline '{pname}' lists node '{nname}', which is not defined")
                continue
            pnodes[nname] = _decompile_node(nname, nodes[nname] or {}, producers, problems)
        if pdoc.get("inputs") or pdoc.get("outputs"):
            note = "pipeline-level inputs/outputs dropped (nothing read them)"
            if note not in notes:
                notes.append(note)
        keys = (
            "description",
            "type",
            "requires_dates",
            "depends_on",
            "reuse_if_materialized",
            "spark_config",
            "split",
            "hyperparams",
            "hyperparams_config",
            "model_version",
        )
        pipelines[pname] = _clean({k: pdoc.get(k) for k in keys})
        pipelines[pname]["nodes"] = pnodes
        for key in pdoc:
            if key not in (*keys, "nodes", "inputs", "outputs", "name"):
                problems.append(f"pipeline '{pname}': key '{key}' is not a pipeline setting")
    for nname in nodes:
        if nname not in owner:
            notes.append(f"node '{nname}' belongs to no pipeline — not migrated")

    inputs, outputs = docs["input_config"] or {}, docs["output_config"] or {}
    catalog: Dict[str, Any] = {}
    for name in dict.fromkeys([*inputs, *outputs]):
        catalog[name] = _decompile_dataset(name, inputs.get(name), outputs.get(name), problems)

    _promote_contracts(pipelines, catalog)
    tree["catalog"] = catalog
    tree["pipelines"] = pipelines
    return tree


def _promote_contracts(pipelines: Dict[str, Any], catalog: Dict[str, Any]) -> None:
    """Input checks identical for every consumer of a dataset become its catalog contract."""
    consumers: Dict[str, List[Dict[str, Any]]] = {}
    for p in pipelines.values():
        for node in p["nodes"].values():
            reads = node.get("inputs") or []
            reads = list(reads.values()) if isinstance(reads, dict) else list(reads)
            for ds in reads:
                consumers.setdefault(ds, []).append(node)
    for ds, nodes in consumers.items():
        blocks = [n.get("input_checks", {}).get(ds) for n in nodes]
        if (
            ds in catalog
            and blocks
            and all(b is not None for b in blocks)
            and all(b == blocks[0] for b in blocks)
        ):
            catalog[ds]["checks"] = blocks[0]
            for n in nodes:
                n["input_checks"].pop(ds)
                if not n["input_checks"]:
                    n.pop("input_checks")


# ── environments as minimal overrides ────────────────────────────────────────


def _diff(base: Any, other: Any, problems: List[str], path: str) -> Any:
    """The override that turns ``base`` into ``other`` under deep merge, or _SAME."""
    if isinstance(base, dict) and isinstance(other, dict):
        out = {}
        for key in base:
            if key not in other:
                problems.append(
                    f"environment removes '{path}{key}', which an override cannot express"
                )
        for key, value in other.items():
            if key not in base:
                out[key] = value
                continue
            sub = _diff(base[key], value, problems, f"{path}{key}.")
            if sub is not _SAME:
                out[key] = sub
        return out if out else _SAME
    return _SAME if base == other else other


_SAME = object()


# ── equivalence ──────────────────────────────────────────────────────────────


def canonical(docs: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """What the engine actually acts on, in one normal form.

    Removes only what format 2 drops on purpose: pipeline inputs/outputs,
    descriptions, `enabled: true` and other explicit defaults, dependencies
    already implied by the data, and the two spellings of single- versus
    multi-input sanity checks.
    """
    from ducta.setting.schemas import _RUNTIME_GLOBAL_CONFIG_KEYS, GlobalConfigSchema

    known = set(GlobalConfigSchema.model_fields) | set(_RUNTIME_GLOBAL_CONFIG_KEYS)
    # project_name is identity, not behaviour; metadata is free-form.
    g = {
        k: v
        for k, v in docs["global_config"].items()
        if k in known and k not in ("metadata", "environments", "project_name")
    }
    nodes = copy.deepcopy(docs["nodes_config"] or {})
    producers = _producers(nodes)
    cnodes: Dict[str, Any] = {}
    used_in: set = set()
    used_out: set = set()
    for name, node in nodes.items():
        node = dict(node or {})
        node.pop("description", None)
        node.pop("name", None)
        streaming = str(node.get("type") or "").lower() == "streaming"
        reads = [] if streaming else _as_list(node.get("input"))
        used_in.update(reads)
        if not streaming:
            used_out.update(_as_list(node.get("output")))
        inferred = {producers[d] for d in reads if d in producers}
        deps = (
            set(_as_list(node.pop("dependencies", None)) + _as_list(node.pop("depends_on", None)))
            - inferred
        )
        if deps:
            node["deps"] = sorted(deps)
        if not isinstance(node.get("input"), dict) and "input" in node:
            node["input"] = _as_list(node["input"])
        if "output" in node and not isinstance(node["output"], dict):
            node["output"] = _as_list(node["output"])
        if node.get("retry") in (0, None):
            node.pop("retry", None)
        sanity = node.pop("sanity_checks", None)
        if isinstance(sanity, dict) and (
            sanity.get("enabled", True) is not False or sanity.get("inputs")
        ):
            if isinstance(sanity.get("inputs"), dict):
                contracts = {ds: _strip_block(b, "gate") for ds, b in sanity["inputs"].items()}
            elif reads:
                idx = int(sanity.get("input_index", 0) or 0)
                idx = idx if idx < len(reads) else 0
                contracts = {reads[idx]: _strip_block(sanity, "sanity_gate")}
            else:
                contracts = {}
            if contracts:
                node["contracts"] = contracts
        if isinstance(node.get("data_quality"), dict):
            node["data_quality"] = _strip_block(node["data_quality"], "quality_gate")
        cnodes[name] = _strip_defaults(node)

    pipelines = {}
    for name, p in (docs["pipelines_config"] or {}).items():
        p = {k: v for k, v in (p or {}).items() if k not in ("inputs", "outputs", "description")}
        p["nodes"] = [
            n if isinstance(n, str) else (n or {}).get("name") for n in p.get("nodes", [])
        ]
        p.setdefault("type", "batch")
        p.setdefault("requires_dates", True)
        pipelines[name] = _strip_defaults(p)

    def side(catalog: Dict[str, Any], used: set, outputs: bool = False) -> Dict[str, Any]:
        out = {}
        for name, entry in (catalog or {}).items():
            if name not in used:
                continue
            e = {k: v for k, v in (entry or {}).items() if k != "description"}
            if "format" in e:
                e["format"] = _fmt(e["format"])
            if outputs:
                # A format-1 output without write_mode appended; migrate writes
                # that explicitly, so both sides compare as "append".
                e.setdefault("write_mode", "append")
            out[name] = _strip_defaults(e)
        return out

    return {
        "global_config": _strip_defaults(g),
        "pipelines": pipelines,
        "nodes": cnodes,
        "inputs": side(docs["input_config"], used_in),
        "outputs": side(docs["output_config"], used_out, outputs=True),
    }


def _strip_block(block: Dict[str, Any], gate_key: str) -> Dict[str, Any]:
    b = {k: v for k, v in block.items() if k not in ("input_index", "run_id", "inputs")}
    if gate_key in b and gate_key != "gate":
        b["gate"] = b.pop(gate_key)
    if isinstance(b.get("gate"), dict):
        b["gate"] = {k: v for k, v in b["gate"].items() if not (k == "enabled" and v is True)}
    return cast(Dict[str, Any], _strip_defaults(b))


def _strip_defaults(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            v = _strip_defaults(v)
            if v is None or v == {} or v == []:
                continue
            if k == "enabled" and v is True:
                continue
            out[k] = v
        return out
    if isinstance(value, list):
        return [_strip_defaults(v) for v in value]
    return value


def _first_difference(a: Any, b: Any, path: str = "") -> Optional[str]:
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b), key=str):
            if key not in a:
                return f"{path}{key}: only after migration = {b[key]!r}"
            if key not in b:
                return f"{path}{key}: lost in migration (was {a[key]!r})"
            diff = _first_difference(a[key], b[key], f"{path}{key}.")
            if diff:
                return diff
        return None
    if a != b:
        return f"{path.rstrip('.')}: {a!r} → {b!r}"
    return None


# ── the migration ────────────────────────────────────────────────────────────


def migrate(root: Path) -> MigrationResult:
    """Decompile, verify equivalence per environment, and return the format-2 files."""
    root = Path(root).resolve()
    if find_project_root(root) is not None:
        raise MigrationError([f"{root / PROJECT_FILE} is already format 2"])

    by_env, files = read_format1(root)
    problems: List[str] = []
    notes: List[str] = []
    envs = [e for e in by_env if e != "base"]
    trees = {
        env: decompile(_apply_inline_environments(docs, env), root.name, problems, notes)
        for env, docs in by_env.items()
    }
    if not (by_env["base"]["global_config"] or {}).get("project_name"):
        notes.append(f"project name set to '{root.name}' (global_config had no project_name)")
    # inline `global_config.environments` may name environments env_config does not
    inline = (by_env["base"]["global_config"] or {}).get("environments")
    if isinstance(inline, dict):
        for env in inline:
            if env not in trees:
                envs.append(env)
                trees[env] = decompile(
                    _apply_inline_environments(by_env["base"], env), root.name, problems, notes
                )
    if problems:
        raise MigrationError(sorted(set(problems)))

    base = trees["base"]
    project = {k: base[k] for k in ("version", "project", "paths", "settings") if k in base}
    if "metadata" in base:
        project["metadata"] = base["metadata"]
    environments: Dict[str, Any] = {}
    for env in envs:
        diff_problems: List[str] = []
        override = _diff(
            {k: v for k, v in base.items() if k in ("settings", "paths", "catalog", "pipelines")},
            {
                k: v
                for k, v in trees[env].items()
                if k in ("settings", "paths", "catalog", "pipelines")
            },
            diff_problems,
            "",
        )
        problems += [f"environment '{env}': {p}" for p in diff_problems]
        if override is not _SAME:
            environments[env] = override
    if environments:
        project["environments"] = environments
    if problems:
        raise MigrationError(sorted(set(problems)))

    result = MigrationResult(
        project=project,
        catalog=base["catalog"],
        pipelines=base["pipelines"],
        environments=envs,
        notes=list(dict.fromkeys(notes)),
        legacy_files=files,
    )
    verify(result, by_env, root)
    return result


def verify(
    result: MigrationResult, by_env: Dict[str, Dict[str, Dict[str, Any]]], root: Path
) -> None:
    """Compile the migrated project for every environment and compare with format 1."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        write_files(result, Path(tmp))
        mismatches = []
        for env in ["base", *result.environments]:
            source = _apply_inline_environments(by_env.get(env, by_env["base"]), env)
            before = canonical(source)
            after = canonical(
                compile_project(validate_project(Path(tmp), None if env == "base" else env))
            )
            diff = _first_difference(before, after)
            if diff:
                mismatches.append(f"environment '{env}': {diff}")
    if mismatches:
        raise MigrationError(["the migrated project would not behave the same:", *mismatches])


# ── writing ──────────────────────────────────────────────────────────────────


def _dump(path: Path, data: Dict[str, Any], schema: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = f"# yaml-language-server: $schema={schema}\n"
    body = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, default_flow_style=False)
    path.write_text(header + body, encoding="utf-8")


def write_schemas(target: Path) -> None:
    """Per-file-kind JSON Schemas under .ducta/schema/, for editor autocompletion."""
    import json

    from ducta.setting.project_schema import json_schema

    defs = json_schema()["$defs"]
    folder = target / _SCHEMA_DIR
    folder.mkdir(parents=True, exist_ok=True)
    for kind, schema in defs.items():
        (folder / f"{kind}.json").write_text(json.dumps(schema, indent=2), encoding="utf-8")


def write_files(result: MigrationResult, target: Path) -> List[Path]:
    target = Path(target)
    written = [target / PROJECT_FILE, target / CATALOG_FILE]
    _dump(written[0], result.project, f"{_SCHEMA_DIR}/project.json")
    _dump(written[1], result.catalog, f"{_SCHEMA_DIR}/catalog.json")
    for name, pipeline in result.pipelines.items():
        path = target / PIPELINES_DIR / f"{name}.yaml"
        _dump(path, pipeline, f"../{_SCHEMA_DIR}/pipeline.json")
        written.append(path)
    write_schemas(target)
    return written


def replace_in_place(result: MigrationResult, root: Path) -> Tuple[List[Path], Path]:
    """Write format 2 into ``root``; move the format-1 files to a backup folder."""
    root = Path(root).resolve()
    backup = root / ".ducta" / "format1-backup" / time.strftime("%Y%m%d-%H%M%S")
    for path in result.legacy_files:
        if not path.exists() or root not in path.resolve().parents:
            continue
        dest = backup / path.resolve().relative_to(root)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(dest))
    for name in result.pipelines:
        clash = root / PIPELINES_DIR / f"{name}.yaml"
        if clash.exists():
            dest = backup / clash.relative_to(root)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(clash), str(dest))
    return write_files(result, root), backup
