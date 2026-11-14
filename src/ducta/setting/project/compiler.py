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

Compile a validated project to the engine's five documents.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, cast

from ducta.setting.project.reader import _conventional_path
from ducta.setting.project.schema import (
    BUILTIN_SCORER,
    CatalogEntry,
    ChecksBlock,
    GateSpec,
    IngestNode,
    StreamNode,
    TransformNode,
)
from ducta.setting.project.validation import Project, _check_references, _node_inputs

#: format-2 placeholders → the names the engine's interpolator resolves.


_PLACEHOLDERS = {
    "${paths.input}": "${input_path}",
    "${paths.output}": "${output_path}",
    "${env}": "${environment}",
}
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
                    "allow_empty": w.allow_empty,
                    "partition_overwrite": w.partition_overwrite,
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


def compile_checks(block: ChecksBlock, gate_key: str) -> Dict[str, Any]:
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
        module, _, function = (node.run or BUILTIN_SCORER).partition(":")
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
                    "model": node.model.model_dump(exclude_unset=True) if node.model else None,
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
        out["data_quality"] = compile_checks(node.quality, "quality_gate")
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
        if entry is not None and entry.quality is not None:
            contracts[ds] = compile_checks(entry.quality, "gate")
    for target, block in node.input_checks.items():
        ds = params.get(target, target)
        contracts[ds] = compile_checks(block, "gate")
    return contracts


def compile_project(project: Project) -> Dict[str, Dict[str, Any]]:
    """The five engine documents for a validated project."""
    settings = copy.deepcopy(project.project.settings)
    quality = settings.get("quality")
    if isinstance(quality, dict) and quality.get("gate") is not None:
        quality["gate"] = _gate(GateSpec.model_validate(quality["gate"]))
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
            consumed.update(_check_references(node))
            produced.update(node.outputs)
            nodes_config[nname] = _compile_node(nname, node, project.catalog)
        pipelines_config[pname] = _drop_empty(
            {
                "type": pipeline.type,
                "description": pipeline.description,
                "nodes": list(pipeline.nodes),
                "requires_dates": pipeline.requires_dates,
                "depends_on": list(pipeline.depends_on) or None,
                "retrain": pipeline.retrain.model_dump(exclude_none=True)
                if pipeline.retrain
                else None,
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
