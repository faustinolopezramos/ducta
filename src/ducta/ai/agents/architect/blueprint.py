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

A blueprint: a set of new pipelines, their datasets and contracts, in words
and names — no code. The model (or a person, or another assistant) writes it;
Ducta checks it without a model and turns it into project files itself.

    name: sales_revenue
    goal: Daily revenue per store from the shop's orders
    assumptions: [amounts are in cents]
    datasets:
      silver.sales.orders:
        description: One row per order, deduplicated
        keys: [order_id]
        write: overwrite            # overwrite | append | merge
        columns: {order_id: bigint, amount: double}
        not_null: [order_id]
        unique: [order_id]
        pii: []
    pipelines:
      silver.sales:
        description: Clean the orders
        owner: data-team
        nodes:
          clean_orders:
            description: Deduplicate orders and drop non-positive amounts
            inputs: {orders: bronze.sales.orders}
            outputs: [silver.sales.orders]
            logic: drop duplicate order_id, keep amount > 0

What Ducta writes from it (:func:`render`): each pipeline's YAML, the new
catalog entries, a ``quality`` block per output from its contract, and a
module per pipeline whose functions are stubs until
:mod:`ducta.ai.agents.architect.build` writes them.
"""

from __future__ import annotations

import fnmatch
import keyword
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Set, Tuple

import yaml  # type: ignore[import-untyped]

#: Medallion layers, in the only order data may flow.
LAYERS = {"bronze": 0, "silver": 1, "gold": 2}
WRITE_MODES = ("overwrite", "append", "merge")
_NAME = re.compile(r"^[A-Za-z_][\w-]*(\.[A-Za-z_][\w-]*)*$")
_STUB = 'raise NotImplementedError("written by `ducta ai architect build`")'

_TOP_KEYS = {"name", "goal", "assumptions", "datasets", "pipelines"}
_DATASET_KEYS = {
    "description",
    "format",
    "keys",
    "write",
    "columns",
    "not_null",
    "unique",
    "pii",
    "owner",
}
_PIPELINE_KEYS = {"description", "owner", "sla", "tags", "requires_dates", "nodes"}
_NODE_KEYS = {"description", "kind", "inputs", "outputs", "logic", "ingest"}


@dataclass
class DatasetSpec:
    name: str
    description: str = ""
    format: Optional[str] = None
    keys: List[str] = field(default_factory=list)
    write: str = "overwrite"
    columns: Dict[str, str] = field(default_factory=dict)
    not_null: List[str] = field(default_factory=list)
    unique: List[str] = field(default_factory=list)
    pii: List[str] = field(default_factory=list)
    owner: Optional[str] = None


@dataclass
class NodeSpec:
    name: str
    description: str = ""
    kind: str = "transform"
    inputs: Dict[str, str] = field(default_factory=dict)
    outputs: List[str] = field(default_factory=list)
    logic: str = ""
    ingest: Dict[str, Any] = field(default_factory=dict)

    @property
    def function(self) -> str:
        """The Python function this node runs: its name, made an identifier."""
        name = re.sub(r"\W", "_", self.name.split(".")[-1])
        return name if not name[:1].isdigit() else f"node_{name}"


@dataclass
class PipelineSpec:
    name: str
    description: str = ""
    owner: Optional[str] = None
    sla: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    requires_dates: bool = False
    nodes: Dict[str, NodeSpec] = field(default_factory=dict)

    @property
    def module(self) -> str:
        """The module its functions go in: ``silver.sales`` → ``silver_sales``."""
        return re.sub(r"\W", "_", self.name)


@dataclass
class Blueprint:
    name: str
    goal: str = ""
    assumptions: List[str] = field(default_factory=list)
    datasets: Dict[str, DatasetSpec] = field(default_factory=dict)
    pipelines: Dict[str, PipelineSpec] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        def clean(obj: Any) -> Any:
            if isinstance(obj, dict):
                return {
                    k: clean(v)
                    for k, v in obj.items()
                    if k != "name" and v not in ("", [], {}, None)
                }
            return obj

        return {
            "name": self.name,
            "goal": self.goal,
            "assumptions": list(self.assumptions),
            "datasets": {n: clean(asdict(d)) for n, d in self.datasets.items()},
            "pipelines": {
                p.name: {
                    **clean({k: v for k, v in asdict(p).items() if k != "nodes"}),
                    "nodes": {n.name: clean(asdict(n)) for n in p.nodes.values()},
                }
                for p in self.pipelines.values()
            },
        }

    def to_yaml(self) -> str:
        return yaml.safe_dump(
            self.to_dict(), sort_keys=False, allow_unicode=True, width=100, default_flow_style=None
        )

    def writer_of(self) -> Dict[str, Tuple[str, str]]:
        """Dataset → (pipeline, node) that writes it."""
        return {
            out: (p.name, n.name)
            for p in self.pipelines.values()
            for n in p.nodes.values()
            for out in n.outputs
        }

    def depends_on(self, pipeline: str, producers: Dict[str, str]) -> List[str]:
        """The other pipelines *pipeline* reads from (*producers*: dataset → pipeline)."""
        found: List[str] = []
        for node in self.pipelines[pipeline].nodes.values():
            for ds in node.inputs.values():
                other = producers.get(ds)
                if other and other != pipeline and other not in found:
                    found.append(other)
        return found

    def order(self) -> List[str]:
        """The pipelines, each after those it reads from (input order when free)."""
        producers = {ds: p for ds, (p, _) in self.writer_of().items()}
        done: List[str] = []
        pending = list(self.pipelines)
        while pending:
            ready = [p for p in pending if all(d in done for d in self.depends_on(p, producers))]
            if not ready:  # a cycle: check_blueprint reports it
                done += pending
                break
            done.append(ready[0])
            pending.remove(ready[0])
        return done


# ── reading ─────────────────────────────────────────────────────────────────


def _strings(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, (str, int)):
        return [str(value)]
    if isinstance(value, list):
        return [str(v) for v in value if isinstance(v, (str, int))]
    return []


def _unknown(data: Dict[str, Any], allowed: Set[str], where: str) -> List[str]:
    extra = sorted(set(data) - allowed)
    return (
        [f"{where}: unknown key(s) {', '.join(extra)} (allowed: {', '.join(sorted(allowed))})"]
        if extra
        else []
    )


def parse_blueprint(data: Any) -> Tuple[Optional[Blueprint], List[str]]:
    """A blueprint from its parsed YAML, and what is wrong with its shape."""
    if isinstance(data, dict) and set(data) == {"blueprint"}:
        data = data["blueprint"]
    if not isinstance(data, dict):
        return None, ["A blueprint is a mapping with `name`, `datasets` and `pipelines`"]
    problems = _unknown(data, _TOP_KEYS, "blueprint")
    raw_pipes = data.get("pipelines")
    if not isinstance(raw_pipes, dict) or not raw_pipes:
        problems.append("`pipelines` must map at least one new pipeline name to its nodes")
        raw_pipes = {}
    raw_sets = data.get("datasets") or {}
    if not isinstance(raw_sets, dict):
        problems.append("`datasets` must map dataset names to their description")
        raw_sets = {}

    datasets: Dict[str, DatasetSpec] = {}
    for name, spec in raw_sets.items():
        spec = spec if isinstance(spec, dict) else {"description": spec}
        problems += _unknown(spec, _DATASET_KEYS, f"dataset {name}")
        columns = spec.get("columns") or {}
        datasets[str(name)] = DatasetSpec(
            name=str(name),
            description=str(spec.get("description") or "").strip(),
            format=str(spec["format"]) if spec.get("format") else None,
            keys=_strings(spec.get("keys")),
            write=str(spec.get("write") or "overwrite"),
            columns={str(k): str(v) for k, v in columns.items()}
            if isinstance(columns, dict)
            else {},
            not_null=_strings(spec.get("not_null")),
            unique=_strings(spec.get("unique")),
            pii=_strings(spec.get("pii")),
            owner=str(spec["owner"]) if spec.get("owner") else None,
        )

    pipelines: Dict[str, PipelineSpec] = {}
    for pname, pspec in raw_pipes.items():
        if not isinstance(pspec, dict):
            problems.append(f"pipeline {pname}: must be a mapping with `nodes`")
            continue
        problems += _unknown(pspec, _PIPELINE_KEYS, f"pipeline {pname}")
        nodes: Dict[str, NodeSpec] = {}
        raw_nodes = pspec.get("nodes")
        if not isinstance(raw_nodes, dict) or not raw_nodes:
            problems.append(
                f"pipeline {pname}: `nodes` must map at least one node name to its spec"
            )
            raw_nodes = {}
        for nname, nspec in raw_nodes.items():
            if not isinstance(nspec, dict):
                problems.append(f"node {nname}: must be a mapping")
                continue
            problems += _unknown(nspec, _NODE_KEYS, f"node {nname}")
            inputs = nspec.get("inputs") or {}
            if isinstance(inputs, list):
                problems.append(
                    f"node {nname}: `inputs` maps a parameter name to a dataset "
                    "({param: dataset}), not a list"
                )
                inputs = {}
            ingest = nspec.get("ingest") or {}
            nodes[str(nname)] = NodeSpec(
                name=str(nname),
                description=str(nspec.get("description") or "").strip(),
                kind=str(nspec.get("kind") or ("ingest" if ingest else "transform")),
                inputs={str(k): str(v) for k, v in inputs.items()}
                if isinstance(inputs, dict)
                else {},
                outputs=_strings(nspec.get("outputs")),
                logic=str(nspec.get("logic") or "").strip(),
                ingest=dict(ingest) if isinstance(ingest, dict) else {},
            )
        pipelines[str(pname)] = PipelineSpec(
            name=str(pname),
            description=str(pspec.get("description") or "").strip(),
            owner=str(pspec["owner"]) if pspec.get("owner") else None,
            sla=str(pspec["sla"]) if pspec.get("sla") else None,
            tags=_strings(pspec.get("tags")),
            requires_dates=bool(pspec.get("requires_dates", False)),
            nodes=nodes,
        )

    first = next(iter(pipelines), "blueprint")
    name = str(data.get("name") or re.sub(r"\W", "_", first)).strip()
    return (
        Blueprint(
            name=re.sub(r"[^\w-]", "_", name) or "blueprint",
            goal=str(data.get("goal") or "").strip(),
            assumptions=_strings(data.get("assumptions")),
            datasets=datasets,
            pipelines=pipelines,
        ),
        problems,
    )


def load_blueprint(text: str) -> Tuple[Optional[Blueprint], List[str]]:
    """A blueprint from YAML text (a file, or the body of a model's block)."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        return None, [f"The blueprint is not valid YAML: {e}"]
    return parse_blueprint(data)


# ── what the project already has ────────────────────────────────────────────


@dataclass
class Existing:
    """The project's names a blueprint must reuse, or not collide with."""

    datasets: Set[str] = field(default_factory=set)
    pipelines: Set[str] = field(default_factory=set)
    nodes: Set[str] = field(default_factory=set)
    sources: Set[str] = field(default_factory=set)
    #: ``defaults.catalog`` globs that give a format.
    formats: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def of(cls, root: Path, ctx: Any) -> "Existing":
        from ducta.setting.project_loader import read_project

        formats: Dict[str, str] = {}
        try:
            project = read_project(root, expand=False)
            defaults = ((project.project or {}).get("defaults") or {}).get("catalog") or {}
            formats = {
                g: s["format"]
                for g, s in defaults.items()
                if isinstance(s, dict) and s.get("format")
            }
        except Exception:  # noqa: BLE001 — a project that does not parse has no defaults
            formats = {}
        return cls(
            datasets=set(ctx.catalog),
            pipelines=set(ctx.pipelines),
            nodes={n for nodes in ctx.pipelines.values() for n in nodes},
            sources={s.split(" (")[0] for s in ctx.sources},
            formats=formats,
        )

    def default_format(self, dataset: str) -> Optional[str]:
        for glob, fmt in self.formats.items():
            if fnmatch.fnmatchcase(dataset, glob):
                return fmt
        return None


# ── checking, without a model ───────────────────────────────────────────────


def _layer(dataset: str) -> Optional[int]:
    return LAYERS.get(dataset.split(".")[0])


def check_blueprint(root: Path, bp: Blueprint, existing: Existing) -> Tuple[List[str], List[str]]:
    """What is wrong with *bp* (errors), and what deserves a second look (warnings)."""
    errors: List[str] = []
    warnings: List[str] = []
    writers: Dict[str, List[str]] = {}
    seen_nodes: Set[str] = set()
    modules: Dict[str, str] = {}
    folder: Optional[str] = None

    for pname, pipe in bp.pipelines.items():
        transforms = [n for n in pipe.nodes.values() if n.kind == "transform"]
        if transforms:
            # One module per pipeline, one function per node: two names that
            # come out the same would make two nodes run one function.
            if pipe.module in modules:
                errors.append(
                    f"pipelines {modules[pipe.module]} and {pname} would share the module "
                    f"{pipe.module}.py: rename one"
                )
            modules.setdefault(pipe.module, pname)
            folder = folder or _code_folder(root)
            if folder and (Path(root) / folder / f"{pipe.module}.py").exists():
                errors.append(
                    f"pipeline {pname}: {folder}/{pipe.module}.py already exists; a blueprint "
                    "only adds new modules — rename the pipeline"
                )
            functions: Dict[str, str] = {}
            for node in transforms:
                if node.function in functions:
                    errors.append(
                        f"nodes {functions[node.function]} and {node.name} would both run "
                        f"{node.function}() in {pipe.module}.py: rename one so the last part "
                        "of their names differs"
                    )
                functions.setdefault(node.function, node.name)
                if keyword.iskeyword(node.function):
                    errors.append(
                        f"node {node.name}: `{node.function}` is a Python keyword and cannot "
                        "name its function"
                    )
                reserved = {"kwargs"} | (
                    {"start_date", "end_date"} if pipe.requires_dates else set()
                )
                for param in node.inputs:
                    if keyword.iskeyword(param) or param in reserved:
                        errors.append(
                            f"node {node.name}: input `{param}` cannot be a parameter name "
                            f"(a Python keyword, or one Ducta passes itself)"
                        )
        if not _NAME.match(pname):
            errors.append(
                f"pipeline {pname}: use letters, digits, `_`, `-` and dots (layer.domain)"
            )
        if pname in existing.pipelines or (Path(root) / "pipelines" / f"{pname}.yaml").exists():
            errors.append(f"pipeline {pname} already exists: a blueprint only adds new pipelines")
        for nname, node in pipe.nodes.items():
            if not _NAME.match(nname):
                errors.append(f"node {nname}: use letters, digits, `_`, `-` and dots")
            if nname in existing.nodes or nname in seen_nodes:
                errors.append(
                    f"node {nname}: the name is taken (node names are unique in the project)"
                )
            seen_nodes.add(nname)
            for out in node.outputs:
                writers.setdefault(out, []).append(f"{pname}.{nname}")
            if node.kind == "ingest":
                source = str(node.ingest.get("source") or "")
                if not source:
                    errors.append(
                        f"node {nname}: an ingest node needs `ingest: {{source: …, table: …}}`"
                    )
                elif existing.sources and source not in existing.sources:
                    errors.append(
                        f"node {nname}: no source '{source}' in sources.yaml "
                        f"(declared: {', '.join(sorted(existing.sources))})"
                    )
                elif not existing.sources:
                    errors.append(
                        f"node {nname}: the project declares no ingestion sources; add the "
                        "connection to sources.yaml first"
                    )
                if not (node.ingest.get("table") or node.ingest.get("query")):
                    errors.append(f"node {nname}: an ingest node reads a `table` or a `query`")
                if node.inputs:
                    errors.append(f"node {nname}: an ingest node has no `inputs`")
            elif node.kind == "transform":
                if not node.inputs:
                    errors.append(
                        f"node {nname}: a transform node reads at least one dataset (`inputs`)"
                    )
                for param in node.inputs:
                    if not param.isidentifier():
                        errors.append(
                            f"node {nname}: input `{param}` must be a Python parameter name"
                        )
                if not node.logic:
                    warnings.append(
                        f"node {nname}: no `logic`; the code will be written from its description"
                    )
            else:
                errors.append(f"node {nname}: kind is `transform` or `ingest`, not `{node.kind}`")
            if len(node.outputs) != 1:
                errors.append(
                    f"node {nname}: a node writes exactly one dataset (`outputs: [name]`)"
                )
            for param, source in node.inputs.items():
                if source not in existing.datasets and source not in bp.datasets:
                    errors.append(
                        f"node {nname}: input {source} is neither in the catalog nor in the blueprint's datasets"
                    )
                out_layers = [n for n in (_layer(o) for o in node.outputs) if n is not None]
                out_layer = min(out_layers) if out_layers else None
                in_layer = _layer(source)
                if out_layer is not None and in_layer is not None and in_layer > out_layer:
                    errors.append(
                        f"node {nname}: reads {source} ({source.split('.')[0]}) to write a lower layer; "
                        "data flows bronze → silver → gold"
                    )

    for name, ds in bp.datasets.items():
        if name in existing.datasets:
            errors.append(
                f"dataset {name} is already in the catalog: reuse it as an input, do not redeclare it"
            )
        if len(name.split(".")) != 3 or not _NAME.match(name):
            errors.append(f"dataset {name}: name new datasets <layer>.<domain>.<table>")
        if name not in writers:
            errors.append(f"dataset {name}: no node of the blueprint writes it")
        if ds.write not in WRITE_MODES:
            errors.append(f"dataset {name}: write is one of {', '.join(WRITE_MODES)}")
        if ds.write == "merge" and not ds.keys:
            errors.append(f"dataset {name}: write merge needs `keys`")
        fmt = ds.format or existing.default_format(name) or "parquet"
        if ds.write == "merge" and fmt != "delta":
            errors.append(
                f"dataset {name}: Ducta merges only Delta tables — set `format: delta` "
                f"(it is {fmt}), or write it with overwrite"
            )
        if ds.write == "append":
            warnings.append(
                f"dataset {name}: appended — a retried run writes its rows twice, so Sentinel "
                "never retries it; prefer merge with keys"
            )
        if ds.columns:
            for label, cols in (
                ("keys", ds.keys),
                ("not_null", ds.not_null),
                ("unique", ds.unique),
                ("pii", ds.pii),
            ):
                missing = [c for c in cols if c not in ds.columns]
                if missing:
                    errors.append(
                        f"dataset {name}: {label} {', '.join(missing)} not in its columns"
                    )
        if not ds.description:
            warnings.append(f"dataset {name}: no description")
    for written, who in writers.items():
        if written not in bp.datasets:
            errors.append(f"{who[0]}: output {written} must be declared under `datasets`")
        if len(who) > 1:
            errors.append(
                f"dataset {written} is written by {', '.join(who)}: one writer per dataset"
            )
        if written in existing.datasets:
            errors.append(
                f"{who[0]}: {written} already exists and has its writer; write a new dataset"
            )
    return errors, warnings


# ── rendering ───────────────────────────────────────────────────────────────


def _quality(ds: DatasetSpec) -> Optional[Dict[str, Any]]:
    checks: Dict[str, Any] = {"row_count": {"min": 1}}
    if ds.columns:
        checks["schema"] = {"expected_columns": list(ds.columns), "strict": False}
    if ds.not_null:
        checks["null_rate"] = {"columns": list(ds.not_null), "threshold": 0.0}
    unique = ds.unique or (ds.keys if ds.write == "merge" else [])
    if unique:
        checks["duplicates"] = {"columns": list(unique), "max_duplicate_rate": 0.0}
    return {"checks": checks, "gate": {"max_errors": 0}}


def _catalog_entry(ds: DatasetSpec, existing: Existing) -> Dict[str, Any]:
    entry: Dict[str, Any] = {}
    fmt = ds.format or (None if existing.default_format(ds.name) else "parquet")
    if fmt:
        entry["format"] = fmt
    if ds.description:
        entry["description"] = ds.description
    if ds.write == "merge":
        entry["write"] = {"mode": "merge", "merge": {"keys": list(ds.keys)}}
    elif ds.write == "append":
        entry["write"] = {"mode": "append"}
    metadata: Dict[str, Any] = {}
    if ds.owner:
        metadata["owner"] = ds.owner
    if ds.pii:
        metadata["pii"] = list(ds.pii)
    if metadata:
        entry["metadata"] = metadata
    return entry


def _code_folder(root: Path) -> Optional[str]:
    try:
        return code_folder_of(root)
    except Exception:  # noqa: BLE001 — a project that does not parse has no code folder yet
        return None


def code_folder_of(root: Path) -> str:
    from ducta.ai.builder import code_folder

    return code_folder(root)


def module_path(root: Path, pipe: PipelineSpec) -> str:
    return f"{code_folder_of(root)}/{pipe.module}.py"


def stub_module(pipe: PipelineSpec) -> str:
    """A module whose functions have the right signatures and no body yet."""
    parts = [f'"""{pipe.description or pipe.name} — written by Ducta Architect."""', ""]
    for node in pipe.nodes.values():
        if node.kind != "transform":
            continue
        params = list(node.inputs)
        if pipe.requires_dates:
            params += ["start_date", "end_date"]
        parts += [
            "",
            f"def {node.function}({', '.join(params + ['**kwargs'])}):",
            f"    {_STUB}",
            "",
        ]
    return "\n".join(parts).rstrip() + "\n"


def pipeline_yaml(bp: Blueprint, pipe: PipelineSpec, folder: str) -> str:
    producers = {ds: p for ds, (p, _) in bp.writer_of().items()}
    doc: Dict[str, Any] = {}
    if pipe.description:
        doc["description"] = pipe.description
    doc["requires_dates"] = pipe.requires_dates
    deps = bp.depends_on(pipe.name, producers)
    if deps:
        doc["depends_on"] = deps
    metadata: Dict[str, Any] = {}
    if pipe.owner:
        metadata["owner"] = pipe.owner
    if pipe.sla:
        metadata["sla"] = pipe.sla
    if pipe.tags:
        metadata["tags"] = list(pipe.tags)
    if metadata:
        doc["metadata"] = metadata
    nodes: Dict[str, Any] = {}
    for node in pipe.nodes.values():
        spec: Dict[str, Any] = {}
        if node.description:
            spec["description"] = node.description
        if node.kind == "ingest":
            spec["kind"] = "ingest"
            spec["ingest"] = dict(node.ingest)
        else:
            spec["run"] = f"{folder}.{pipe.module}:{node.function}"
            spec["inputs"] = dict(node.inputs)
        spec["outputs"] = list(node.outputs)
        out = bp.datasets.get(node.outputs[0]) if node.outputs else None
        quality = _quality(out) if out else None
        if quality:
            spec["quality"] = quality
        nodes[node.name] = spec
    doc["nodes"] = nodes
    header = f"# Designed by Ducta Architect (blueprint {bp.name})\n"
    # Flow style for leaves ({orders: x}, [a, b]), as the project's files are written.
    body = yaml.safe_dump(
        doc, sort_keys=False, allow_unicode=True, width=100, default_flow_style=None
    )
    return header + body


def render(
    root: Path,
    bp: Blueprint,
    existing: Existing,
    modules: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, str], Dict[str, Optional[str]]]:
    """The project files *bp* amounts to, and the hash each existing one had.

    *modules* (project-relative path → source) replaces a pipeline's stub
    module once its code is written.
    """
    from ducta.ai.builder import _catalog_with

    folder = code_folder_of(root)
    files: Dict[str, str] = {}
    base: Dict[str, Optional[str]] = {}
    for pipe in bp.pipelines.values():
        files[f"pipelines/{pipe.name}.yaml"] = pipeline_yaml(bp, pipe, folder)
        base[f"pipelines/{pipe.name}.yaml"] = None
        if any(n.kind == "transform" for n in pipe.nodes.values()):
            rel = module_path(root, pipe)
            files[rel] = (modules or {}).get(rel) or stub_module(pipe)
            base[rel] = None
    entries = {name: _catalog_entry(ds, existing) for name, ds in bp.datasets.items()}
    if entries:
        rel, text, sha = _catalog_with(root, entries, bp.name)
        files[rel] = text
        base[rel] = sha
    return files, base


def is_stub(source: str) -> bool:
    return _STUB in source


def pipeline_files(bp: Blueprint) -> List[str]:
    return [str(PurePosixPath("pipelines") / f"{p}.yaml") for p in bp.pipelines]
