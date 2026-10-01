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
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from pydantic import BaseModel, Field

from ducta.api.dependencies import ExecutionManagerDep, NodeServiceDep, require_permission
from ducta.api.exceptions import (
    ConfigFileNotFoundError,
    ConfigValidationError,
    NodeNotFoundError,
    http_error_on,
)
from ducta.api.models.execution import ExecutionListResponse

_NODE_NAME_RE = re.compile(r"^[A-Za-z0-9_\-\.]+$")
_PY_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_node_name(name: str, spec: Optional[Dict[str, Any]] = None) -> None:
    """Raise 400 if name is not a safe node identifier."""
    if not _NODE_NAME_RE.match(name) or name in (".", ".."):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid node name '{name}'. "
                "Only alphanumeric characters, underscores, hyphens and dots are allowed."
            ),
        )
    has_explicit_module = bool(spec and spec.get("module"))
    if spec is not None and not has_explicit_module and not _PY_IDENTIFIER_RE.match(name):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid node name '{name}': without an explicit 'module' in the "
                "spec, the name is used to derive one (nodes.<name>) and must be a "
                "valid Python identifier — letters, digits and underscores, not "
                "starting with a digit. Add 'module' to the spec to use a name "
                "outside those rules."
            ),
        )


router = APIRouter(prefix="/nodes", tags=["Nodes"])


class NodeResponse(BaseModel):
    name: str
    spec: Dict[str, Any]
    commit_sha: Optional[str] = Field(default=None, description="SHA for OCC")


class NodesListResponse(BaseModel):
    nodes: Dict[str, Any]
    count: int


class NodeUpdateRequest(BaseModel):
    spec: Dict[str, Any] = Field(description="Node specification dict")
    expected_commit_sha: Optional[str] = Field(None, description="SHA for OCC validation")


class NodeCodeResponse(BaseModel):
    name: str
    module_path: str = Field(description="Relative .py file path inside the workspace")
    code: str = Field(description="Python source code")
    size_bytes: int = Field(description="Source file size in bytes")
    exists: bool = Field(description="Whether the Python file already exists on disk")


class NodeCodeUpdateRequest(BaseModel):
    code: str = Field(description="Python source code to save", max_length=10 * 1024 * 1024)


@router.get(
    "",
    response_model=NodesListResponse,
    summary="List all nodes",
    dependencies=[Depends(require_permission("node.read"))],
)
async def list_nodes(node_svc: NodeServiceDep) -> NodesListResponse:
    """Return all node definitions from the base config."""
    nodes = node_svc.list_nodes()
    return NodesListResponse(nodes=nodes, count=len(nodes))


@router.get(
    "/{name}",
    response_model=NodeResponse,
    summary="Get a node definition",
    dependencies=[Depends(require_permission("node.read"))],
)
async def get_node(
    name: str,
    node_svc: NodeServiceDep,
) -> NodeResponse:
    """Return spec for a single node."""
    _validate_node_name(name)
    try:
        spec, commit_sha = node_svc.get_node(name)
    except NodeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message)
    return NodeResponse(name=name, spec=spec, commit_sha=commit_sha)


@router.put(
    "/{name}",
    response_model=NodeResponse,
    summary="Update a node spec",
    dependencies=[Depends(require_permission("node.write"))],
)
async def update_node(
    name: str,
    body: NodeUpdateRequest,
    node_svc: NodeServiceDep,
    pipeline: Optional[str] = Query(
        default=None,
        description="Pipeline to create the node in. Required to create a node in a "
        "project, where every node lives in a pipeline.",
    ),
) -> NodeResponse:
    """Update or create a node spec and commit to git."""
    _validate_node_name(name, body.spec)
    try:
        commit_sha = node_svc.save_node(
            name, body.spec, expected_sha=body.expected_commit_sha, pipeline=pipeline
        )
    except (ConfigFileNotFoundError, ConfigValidationError) as exc:
        raise HTTPException(status_code=400, detail=exc.message)
    return NodeResponse(name=name, spec=body.spec, commit_sha=commit_sha)


@router.delete(
    "/{name}",
    status_code=204,
    summary="Delete a node spec",
    dependencies=[Depends(require_permission("node.write"))],
)
async def delete_node(
    name: str,
    node_svc: NodeServiceDep,
    expected_commit_sha: Optional[str] = None,
) -> None:
    """Remove a node from the workspace config and commit to git."""
    _validate_node_name(name)
    try:
        node_svc.delete_node(name, expected_sha=expected_commit_sha)
    except NodeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message)
    except (ConfigFileNotFoundError, ConfigValidationError) as exc:
        raise HTTPException(status_code=400, detail=exc.message)


@router.get(
    "/{name}/code",
    response_model=NodeCodeResponse,
    summary="Get node Python source code",
    dependencies=[Depends(require_permission("node.read"))],
)
async def get_node_code(
    name: str,
    node_svc: NodeServiceDep,
    module: Optional[str] = None,
    preview: Optional[int] = None,
) -> NodeCodeResponse:
    """Return the Python source file for a node."""
    _validate_node_name(name)
    with http_error_on(400):
        # If module is provided, use it directly (for nodes only in pipelines)
        if module:
            info = node_svc.get_node_python_file_by_module(module)
        else:
            # Otherwise, look up node in global nodes config
            info = node_svc.get_node_python_file(name)

    code = info.code
    if preview and preview > 0 and code:
        lines = code.split("\n")
        code = "\n".join(lines[:preview])

    return NodeCodeResponse(
        name=name,
        module_path=info.rel_path,
        code=code,
        size_bytes=info.size_bytes,
        exists=info.exists,
    )


class FunctionInfo(BaseModel):
    name: str
    params: List[str] = Field(default_factory=list)
    return_type: Optional[str] = None
    decorators: List[str] = Field(default_factory=list)
    is_async: bool = False
    docstring: Optional[str] = None
    lineno: int = 0


class NodeAstResponse(BaseModel):
    functions: List[FunctionInfo] = Field(default_factory=list)
    imports: List[str] = Field(default_factory=list)
    error: Optional[str] = None


@router.post(
    "/{name}/code/ast",
    response_model=NodeAstResponse,
    summary="Parse node Python code with AST and return function signatures",
    dependencies=[Depends(require_permission("node.read"))],
)
async def get_node_code_ast(
    name: str,
    node_svc: NodeServiceDep,
    module: Optional[str] = None,
) -> NodeAstResponse:
    """Parse the node's Python source with ast.parse() and return structured info."""
    _validate_node_name(name)
    try:
        if module:
            info = node_svc.get_node_python_file_by_module(module)
        else:
            info = node_svc.get_node_python_file(name)
    except NodeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message)
    except ValueError:
        return NodeAstResponse()

    if not info.code:
        return NodeAstResponse()

    try:
        tree = ast.parse(info.code)
    except SyntaxError as exc:
        return NodeAstResponse(error=f"Syntax error: {exc.msg}")

    functions: List[FunctionInfo] = []
    imports: List[str] = []

    # Collect top-level imports
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module_name = node.module or ""
            for alias in node.names:
                imports.append(f"{module_name}.{alias.name}")

    # Collect only top-level functions (not nested functions inside other functions)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            params = []
            for arg in node.args.args:
                params.append(arg.arg)

            return_type = None
            if node.returns:
                try:
                    return_type = ast.unparse(node.returns)
                except Exception as exc:
                    logger.debug(
                        "Could not unparse return type annotation for function '{fn}': {exc}",
                        fn=node.name,
                        exc=exc,
                    )
                    return_type = None

            decorators = []
            for dec in node.decorator_list:
                if isinstance(dec, ast.Name):
                    decorators.append(dec.id)
                elif isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name):
                    decorators.append(dec.func.id)
                elif isinstance(dec, ast.Attribute):
                    decorators.append(dec.attr)

            docstring = ast.get_docstring(node)

            functions.append(
                FunctionInfo(
                    name=node.name,
                    params=params,
                    return_type=return_type,
                    decorators=decorators,
                    is_async=isinstance(node, ast.AsyncFunctionDef),
                    docstring=docstring,
                    lineno=node.lineno,
                )
            )

    return NodeAstResponse(functions=functions, imports=imports)


@router.get(
    "/{name}/executions",
    response_model=ExecutionListResponse,
    summary="Get execution history for a specific node",
    dependencies=[Depends(require_permission("execution.read"))],
)
async def get_node_executions(
    name: str,
    node_svc: NodeServiceDep,
    exec_manager: ExecutionManagerDep,
    skip: int = 0,
    limit: int = 10,
) -> ExecutionListResponse:
    """Return the last N executions for a specific node, ordered by start time desc."""
    _validate_node_name(name)
    executions, total = exec_manager.list_executions_paginated(
        skip=skip,
        limit=limit,
        node_name=name,
    )
    return ExecutionListResponse(
        executions=executions, count=len(executions), total=total, skip=skip, limit=limit
    )


@router.put(
    "/{name}/code",
    response_model=NodeCodeResponse,
    summary="Update node Python source code",
    dependencies=[Depends(require_permission("node.write"))],
)
async def update_node_code(
    name: str,
    body: NodeCodeUpdateRequest,
    node_svc: NodeServiceDep,
) -> NodeCodeResponse:
    """Validate syntax, write the source file, and commit to git."""
    _validate_node_name(name)
    # NodeNotFoundError (404) and SyntaxValidationError (400, with line/offset
    # detail) reach the global DuctaAPIError handler with their error codes.
    with http_error_on(400):
        info = node_svc.save_node_code(name, body.code)

    return NodeCodeResponse(
        name=name,
        module_path=info.rel_path,
        code=body.code,
        size_bytes=info.size_bytes,
        exists=True,
    )
