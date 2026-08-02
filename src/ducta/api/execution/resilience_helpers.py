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

from typing import Any, Dict, Optional, TypeVar

from loguru import logger  # type: ignore

from ducta.api.execution.context import execution_id_var, node_id_var
from ducta.api.execution.error_recovery import ErrorContext, get_error_log
from ducta.api.execution.resilience_core import get_resilience_context

T = TypeVar("T")


def set_current_execution_id(execution_id: str) -> None:
    execution_id_var.set(execution_id)


def get_current_execution_id() -> Optional[str]:
    return execution_id_var.get()


def set_current_node_id(node_id: str) -> None:
    node_id_var.set(node_id)


def get_current_node_id() -> Optional[str]:
    return node_id_var.get()


def record_node_error(exception: Exception, error_context: Optional[Dict[str, Any]] = None) -> None:
    execution_id = get_current_execution_id()
    if not execution_id:
        logger.warning("Cannot record node error: no execution ID in context")
        return

    node_id = get_current_node_id()
    resilience_ctx = get_resilience_context(execution_id)
    resilience_ctx.record_node_failure(
        node_id=node_id or "unknown",
        exception=exception,
        context=error_context,
    )

    error_log = get_error_log(execution_id)
    error_log.log_error(
        exception,
        ErrorContext(
            execution_id=execution_id,
            node_id=node_id,
            node_type=error_context.get("node_type") if error_context else None,
        ),
    )

    logger.warning(
        "Node error recorded for {node_id}: {exc}", node_id=node_id, exc=str(exception)[:100]
    )
