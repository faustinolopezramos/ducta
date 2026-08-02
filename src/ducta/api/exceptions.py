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

from typing import Any, Optional

from ducta.api.models.responses import ErrorCode


class DuctaAPIError(Exception):
    """Base exception for all Ducta API errors."""

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


class ValidationError(DuctaAPIError):
    """Input failed schema or business-level validation."""

    status_code = 400
    error_code = ErrorCode.VALIDATION_ERROR


class SyntaxValidationError(ValidationError):
    """Python code failed ast.parse() syntax check."""

    error_code = ErrorCode.SYNTAX_ERROR


class ConfigValidationError(ValidationError):
    """Ducta config file failed schema validation."""

    error_code = ErrorCode.CONFIG_VALIDATION_ERROR


class NotFoundError(DuctaAPIError):
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


class ExecutionNotFoundError(NotFoundError):
    """Pipeline execution record not found."""

    error_code = ErrorCode.EXECUTION_NOT_FOUND


class ConflictError(DuctaAPIError):
    """Request conflicts with current state."""

    status_code = 409
    error_code = ErrorCode.CONFLICT


class ConcurrencyError(ConflictError):
    """Concurrent modification detected (optimistic lock failure)."""

    error_code = ErrorCode.CONCURRENCY_ERROR


class RepositoryAdapterError(DuctaAPIError):
    """Remote repository adapter (GitHub/Azure/AWS) encountered an error."""

    status_code = 500
    error_code = ErrorCode.REPOSITORY_ADAPTER_ERROR


class ExecutionError(DuctaAPIError):
    """Pipeline execution failed unexpectedly."""

    status_code = 500
    error_code = ErrorCode.EXECUTION_ERROR


class AuthenticationError(DuctaAPIError):
    """Invalid or missing authentication credentials."""

    status_code = 401
    error_code = ErrorCode.AUTHENTICATION_ERROR


class InvalidTokenError(AuthenticationError):
    """JWT token is malformed, expired, or has an invalid signature."""

    error_code = ErrorCode.INVALID_TOKEN


class ExpiredTokenError(AuthenticationError):
    """JWT token has expired."""

    error_code = ErrorCode.TOKEN_EXPIRED


class ProjectNotFoundError(NotFoundError):
    """Project directory or project_settings.yaml not found in workspace."""

    error_code = ErrorCode.PROJECT_NOT_FOUND


class ProjectAlreadyExistsError(ConflictError):
    """A project with this name already exists in the workspace."""

    error_code = ErrorCode.PROJECT_ALREADY_EXISTS
