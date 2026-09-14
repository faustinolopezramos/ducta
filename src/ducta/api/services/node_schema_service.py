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
"""

from __future__ import annotations

import ast
import copy
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from loguru import logger  # type: ignore

from ducta.api.exceptions import NodeNotFoundError, PipelineNotFoundError
from ducta.api.models.node_schema import (
    IOItem,
    NodeSchemaResponse,
    PipelineNodeSchemaResponse,
    QualityInfo,
)
from ducta.api.services.dataset_service import node_io

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ducta.api.execution.manager import ExecutionManager
    from ducta.api.services.dataset_service import DatasetService
    from ducta.api.services.node_service import NodeService
    from ducta.api.services.project import ProjectService

# Fields merged from the global node config when the pipeline-level spec omits them.
_MERGEABLE_FIELDS = (
    "module",
    "fn",
    "function",
    "type",
    "description",
    "inputs",
    "outputs",
    "dependencies",
    "data_quality",
    "sanity_checks",
)


class NodeSchemaService:
    """Assemble a :class:`PipelineNodeSchemaResponse` for a node in a pipeline."""

    def __init__(
        self,
        project_svc: "ProjectService",
        node_svc: "NodeService",
        exec_manager: "ExecutionManager",
        dataset_svc: "DatasetService",
    ) -> None:
        self._project_svc = project_svc
        self._node_svc = node_svc
        self._exec_manager = exec_manager
        self._dataset_svc = dataset_svc

    # ── Public API ────────────────────────────────────────────────────────────

    def build(
        self, project_id: str, pipeline_name: str, node_id: str
    ) -> PipelineNodeSchemaResponse:
        """Return the enriched schema for *node_id* within *pipeline_name*.

        Raises :exc:`PipelineNotFoundError` / :exc:`NodeNotFoundError` when the
        pipeline or node cannot be located.
        """
        pipelines = self._project_svc.list_project_pipelines(project_id)
        if pipeline_name not in pipelines:
            raise PipelineNotFoundError(f"Pipeline '{pipeline_name}' not found")

        pipeline_spec = pipelines[pipeline_name]
        node_spec = self._find_node_spec(pipeline_spec, node_id)
        if node_spec is None:
            raise NodeNotFoundError(f"Node '{node_id}' not found in pipeline '{pipeline_name}'")

        # Work on a copy — the pipeline dict may be a shared/cached reference.
        node_spec = copy.deepcopy(node_spec)
        self._merge_global_spec(node_spec, node_id)

        inputs_list = self._build_io(node_spec, node_id, "input")
        outputs_list = self._build_io(node_spec, node_id, "output")

        module, info, file_exists, file_size_bytes = self._resolve_file(node_spec, node_id)

        if not inputs_list and not outputs_list and file_exists and info and info.code:
            inputs_list, outputs_list = self._infer_io_from_ast(
                info.code, node_spec.get("fn", "execute"), node_id
            )

        last_exec = self._last_execution(node_id)

        dependencies = node_spec.get("dependencies", [])
        dependencies = [str(d) for d in dependencies] if isinstance(dependencies, list) else []

        node = NodeSchemaResponse(
            name=node_spec.get("name", node_id),
            node_id=node_spec.get("id", node_id),
            type=node_spec.get("type", "custom"),
            module=module,
            fn=self._fn_name(node_spec),
            description=node_spec.get("description"),
            inputs=inputs_list,
            outputs=outputs_list,
            dependencies=dependencies,
            file_path=f"{module.replace('.', '/')}.py",
            file_size_bytes=file_size_bytes,
            file_exists=file_exists,
            quality=self._quality(node_spec),
            last_execution_status=last_exec.get("status"),
            last_execution_time=last_exec.get("time"),
            last_execution_duration=last_exec.get("duration"),
            last_execution_error_message=last_exec.get("error_message"),
        )
        return PipelineNodeSchemaResponse(
            project_id=project_id, pipeline_name=pipeline_name, node=node
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _find_node_spec(pipeline_spec: Dict[str, Any], node_id: str) -> Optional[Dict[str, Any]]:
        for n in pipeline_spec.get("nodes", []):
            if isinstance(n, dict):
                if n.get("id") == node_id or n.get("name") == node_id:
                    return n
            elif isinstance(n, str) and n == node_id:
                return {"id": node_id, "name": node_id}
        return None

    def _merge_global_spec(self, node_spec: Dict[str, Any], node_id: str) -> None:
        """Fill missing fields from the global node config (in place)."""
        try:
            global_spec, _ = self._node_svc.get_node(node_id)
        except NodeNotFoundError:
            return  # Node not in global config; pipeline-level spec is used as-is.
        if not global_spec:
            return
        for key in _MERGEABLE_FIELDS:
            if node_spec.get(key):
                continue
            val = global_spec.get(key)
            if key in ("inputs", "outputs"):
                val = val or global_spec.get(key[:-1])
            if val:
                node_spec[key] = val

    @staticmethod
    def _fn_name(node_spec: Dict[str, Any]) -> str:
        """Resolve the function name, which streaming nodes declare as a dict."""
        fn = node_spec.get("fn") or node_spec.get("function")
        if isinstance(fn, dict):
            return str(fn.get("key") or fn.get("fn") or "execute")
        return str(fn) if fn else "execute"

    def _build_io(self, node_spec: Dict[str, Any], node_id: str, side: str) -> List[IOItem]:
        """Resolve a node's declared references on *side* into port items."""
        names = node_io(node_spec, side)
        refs = self._dataset_svc.resolve_refs(names, side)
        items: List[IOItem] = []
        for index, ref in enumerate(refs):
            items.append(
                IOItem(
                    id=f"{node_id}-{side}-{index}",
                    name=ref.name,
                    declared=ref.declared,
                    format=ref.format,
                    path=ref.path,
                    write_mode=ref.write_mode,
                    schema=ref.schema_,
                    layer=ref.layer,
                )
            )
        return items

    @staticmethod
    def _quality(node_spec: Dict[str, Any]) -> Optional[QualityInfo]:
        """Summarize the node's checks and gate, when either is enabled."""
        dq = node_spec.get("data_quality") or node_spec.get("dataQuality")
        sanity = node_spec.get("sanity_checks") or node_spec.get("sanityChecks")
        block = None
        is_sanity = False
        if isinstance(dq, dict) and dq.get("enabled"):
            block = dq
        elif isinstance(sanity, dict) and sanity.get("enabled"):
            block = sanity
            is_sanity = True
        if block is None:
            return None

        checks = block.get("checks") or {}
        if isinstance(checks, dict):
            count = sum(
                1
                for c in checks.values()
                if not isinstance(c, dict) or c.get("enabled") is not False
            )
        elif isinstance(checks, list):
            count = len(checks)
        else:
            count = 0

        gate_block = (
            block.get("quality_gate")
            or block.get("qualityGate")
            or block.get("sanity_gate")
            or block.get("sanityGate")
        )
        gate = None
        if isinstance(gate_block, dict) and gate_block.get("enabled"):
            behavior = gate_block.get("behavior")
            gate = str(behavior) if behavior else None

        if count == 0 and gate is None:
            return None
        return QualityInfo(check_count=count, gate_behavior=gate, is_sanity=is_sanity)

    def _resolve_file(
        self, node_spec: Dict[str, Any], node_id: str
    ) -> tuple[str, Optional[Any], bool, Optional[int]]:
        """Resolve the node's Python source file. Returns (module, info, exists, size)."""
        module = node_spec.get("module", node_id)
        for candidate_module in (module, f"src.{module}"):
            try:
                candidate_info = self._node_svc.get_node_python_file_by_module(candidate_module)
            except (NodeNotFoundError, ValueError):
                continue
            if candidate_info.exists:
                return candidate_module, candidate_info, True, candidate_info.size_bytes

        # Fallback: raw path check if module resolution failed.
        from ducta.api.workspace.utils import resolve_module_path

        try:
            raw_path = resolve_module_path(self._node_svc.root, module)
            if raw_path.exists():
                raw_code = raw_path.read_text(encoding="utf-8")
                size = len(raw_code.encode("utf-8"))
                info = SimpleNamespace(exists=True, code=raw_code, size_bytes=size)
                return module, info, True, size
        except (ValueError, OSError) as exc:
            logger.debug("Schema file fallback failed for {module}: {exc}", module=module, exc=exc)

        return module, None, False, None

    @staticmethod
    def _infer_io_from_ast(
        code: str, target_fn_name: str, node_id: str
    ) -> tuple[List[IOItem], List[IOItem]]:
        """Infer I/O from a function signature when the config declares none."""
        inputs: List[IOItem] = []
        outputs: List[IOItem] = []
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            logger.debug("AST inference parse error for node {node}: {exc}", node=node_id, exc=exc)
            return inputs, outputs

        for node_ast in ast.walk(tree):
            if not isinstance(node_ast, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node_ast.name != target_fn_name:
                continue
            for arg in node_ast.args.args:
                if arg.arg in ("self", "cls"):
                    continue
                inputs.append(
                    IOItem(
                        id=f"{node_id}-input-{len(inputs)}",
                        name=arg.arg,
                        declared=False,
                        description="Inferred from the function signature",
                    )
                )
            outputs.append(
                IOItem(
                    id=f"{node_id}-output-0",
                    name="output",
                    declared=False,
                    description="Inferred from the function signature",
                )
            )
            break
        return inputs, outputs

    def _last_execution(self, node_id: str) -> Dict[str, Any]:
        """Look up the most recent execution for *node_id* (best-effort)."""
        try:
            last_execs, _ = self._exec_manager.list_executions_paginated(
                skip=0, limit=1, node_name=node_id
            )
        except Exception as exc:  # noqa: BLE001 - history lookup must never break the schema
            logger.warning(
                "Last-execution lookup failed for node {node}: {exc}", node=node_id, exc=exc
            )
            return {}
        if not last_execs:
            return {}
        last = last_execs[0]
        return {
            "status": last.status.value if hasattr(last.status, "value") else str(last.status),
            "time": last.started_at.isoformat() if last.started_at else None,
            "duration": last.duration_seconds,
            "error_message": last.error_message,
        }
