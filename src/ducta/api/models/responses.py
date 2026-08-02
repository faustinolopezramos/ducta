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

from enum import Enum
from typing import TYPE_CHECKING, Any, Optional

from pydantic import BaseModel, Field  # type: ignore

if TYPE_CHECKING:
    from fastapi import Request


class ErrorCode(str, Enum):
    """Standard error codes returned by API endpoints.

    Maps to corresponding DuctaAPIError subclasses. Used by UI for
    user-friendly error messages and error recovery logic.
    """

    # Validation
    VALIDATION_ERROR = "VALIDATION_ERROR"
    SYNTAX_ERROR = "SYNTAX_ERROR"
    CONFIG_VALIDATION_ERROR = "CONFIG_VALIDATION_ERROR"
    SCHEMA_MISMATCH = "SCHEMA_MISMATCH"

    # Not Found
    NOT_FOUND = "NOT_FOUND"
    WORKSPACE_NOT_FOUND = "WORKSPACE_NOT_FOUND"
    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    PIPELINE_NOT_FOUND = "PIPELINE_NOT_FOUND"
    NODE_NOT_FOUND = "NODE_NOT_FOUND"
    CONFIG_FILE_NOT_FOUND = "CONFIG_FILE_NOT_FOUND"
    EXECUTION_NOT_FOUND = "EXECUTION_NOT_FOUND"

    # Conflict
    CONFLICT = "CONFLICT"
    CONCURRENCY_ERROR = "CONCURRENCY_ERROR"
    PROJECT_ALREADY_EXISTS = "PROJECT_ALREADY_EXISTS"

    # Authentication
    AUTHENTICATION_ERROR = "AUTHENTICATION_ERROR"
    INVALID_TOKEN = "INVALID_TOKEN"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    UNAUTHORIZED = "UNAUTHORIZED"

    # Execution
    EXECUTION_ERROR = "EXECUTION_ERROR"
    EXECUTION_TIMEOUT = "EXECUTION_TIMEOUT"
    EXECUTION_CANCELLED = "EXECUTION_CANCELLED"

    # Repository & Git
    REPOSITORY_ADAPTER_ERROR = "REPOSITORY_ADAPTER_ERROR"
    GIT_ERROR = "GIT_ERROR"

    # Server
    INTERNAL_ERROR = "INTERNAL_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"

    # Rate Limiting
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"

    # Unknown
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


class SuccessResponse(BaseModel):
    """Generic success response wrapper."""

    success: bool = True
    data: Any = Field(..., description="Response payload")
    request_id: Optional[str] = Field(None, description="Request ID for tracing")


# ── Helper function to inject request_id from middleware state ──────────────


def success_response(data: Any, request: "Request | None" = None) -> SuccessResponse:
    """Create a SuccessResponse injecting the request_id from middleware state.

    Usage in route handlers:
        return success_response(data=payload, request=request)

    The request parameter is optional and can be obtained via FastAPI dependency injection.
    If provided, the request_id is extracted from request.state set by middleware.
    """
    rid: Optional[str] = None
    if request is not None:
        rid = getattr(getattr(request, "state", None), "request_id", None)
    return SuccessResponse(data=data, request_id=rid)
