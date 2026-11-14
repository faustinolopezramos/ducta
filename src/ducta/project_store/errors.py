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
from typing import Any, Optional


class ErrorCode(str, Enum):
    """Standard error codes returned by API endpoints."""

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


class StoreError(Exception):
    """Base of the project-store and run-service errors (the server answers with them)."""

    status_code: int = 500
    error_code: ErrorCode = ErrorCode.INTERNAL_ERROR

    def __init__(self, message: str, detail: Optional[Any] = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail

    def to_dict(self) -> dict:
        return {
            "error": self.error_code.value,
            "message": self.message,
            "detail": self.detail,
        }


class ValidationError(StoreError):
    """Input failed schema or business-level validation."""

    status_code = 400
    error_code = ErrorCode.VALIDATION_ERROR


class SyntaxValidationError(ValidationError):
    """Python code failed ast.parse() syntax check."""

    error_code = ErrorCode.SYNTAX_ERROR


class ConfigValidationError(ValidationError):
    """Ducta config file failed schema validation."""

    error_code = ErrorCode.CONFIG_VALIDATION_ERROR


class NotFoundError(StoreError):
    """Requested resource does not exist."""

    status_code = 404
    error_code = ErrorCode.NOT_FOUND


class WorkspaceNotFoundError(NotFoundError):
    """Workspace directory or required structure missing."""

    error_code = ErrorCode.WORKSPACE_NOT_FOUND


class PipelineNotFoundError(NotFoundError):
    """Pipeline definition not found in workspace."""

    error_code = ErrorCode.PIPELINE_NOT_FOUND


class NodeNotFoundError(NotFoundError):
    """Node definition not found in workspace."""

    error_code = ErrorCode.NODE_NOT_FOUND


class ConfigFileNotFoundError(NotFoundError):
    """Config file not found for the requested environment."""

    error_code = ErrorCode.CONFIG_FILE_NOT_FOUND


class ConflictError(StoreError):
    """Request conflicts with current state."""

    status_code = 409
    error_code = ErrorCode.CONFLICT


class ConcurrencyError(ConflictError):
    """Concurrent modification detected (optimistic lock failure)."""

    error_code = ErrorCode.CONCURRENCY_ERROR


class ProjectNotFoundError(NotFoundError):
    """Project directory or its ducta.yaml not found in workspace."""

    error_code = ErrorCode.PROJECT_NOT_FOUND


class ProjectAlreadyExistsError(ConflictError):
    """A project with this name already exists in the workspace."""

    error_code = ErrorCode.PROJECT_ALREADY_EXISTS
