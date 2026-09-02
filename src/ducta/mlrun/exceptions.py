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

import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class ResilienceError(Exception):
    """Base exception for resilience operations."""

    pass


class ResourceLimitError(ResilienceError):
    """Raised when resource limits are exceeded."""

    def __init__(self, resource: str, current: int, limit: int):
        self.resource = resource
        self.current = current
        self.limit = limit
        super().__init__(
            f"Resource limit exceeded for '{resource}': limit={limit}, current={current}"
        )


class ErrorCode(str, Enum):
    """
    Error codes for MLOps exceptions.
    """

    # Model Registry Errors (1xx)
    MODEL_NOT_FOUND = "MODEL_001"
    MODEL_VERSION_NOT_FOUND = "MODEL_002"
    MODEL_VERSION_CONFLICT = "MODEL_003"
    MODEL_REGISTRATION_FAILED = "MODEL_004"
    MODEL_PROMOTION_FAILED = "MODEL_005"
    MODEL_DELETION_FAILED = "MODEL_006"
    MODEL_DOWNLOAD_FAILED = "MODEL_007"
    MODEL_VERSION_PROTECTED = "MODEL_008"

    # Experiment Errors (2xx)
    EXPERIMENT_NOT_FOUND = "EXP_001"
    EXPERIMENT_CREATION_FAILED = "EXP_002"
    EXPERIMENT_DELETION_FAILED = "EXP_003"

    # Run Errors (3xx)
    RUN_NOT_FOUND = "RUN_001"
    RUN_NOT_ACTIVE = "RUN_002"
    RUN_ALREADY_ENDED = "RUN_003"
    RUN_LIMIT_EXCEEDED = "RUN_004"
    RUN_CREATION_FAILED = "RUN_005"

    # Metric/Parameter Errors (4xx)
    INVALID_METRIC = "METRIC_001"
    INVALID_PARAMETER = "PARAM_001"
    METRIC_LIMIT_EXCEEDED = "METRIC_002"

    # Artifact Errors (5xx)
    ARTIFACT_NOT_FOUND = "ARTIFACT_001"
    ARTIFACT_UPLOAD_FAILED = "ARTIFACT_002"
    ARTIFACT_DOWNLOAD_FAILED = "ARTIFACT_003"
    ARTIFACT_INVALID = "ARTIFACT_004"

    # Storage Errors (6xx)
    STORAGE_READ_FAILED = "STORAGE_001"
    STORAGE_WRITE_FAILED = "STORAGE_002"
    STORAGE_DELETE_FAILED = "STORAGE_003"
    STORAGE_CONNECTION_FAILED = "STORAGE_004"
    STORAGE_PERMISSION_DENIED = "STORAGE_005"
    STORAGE_CIRCUIT_OPEN = "STORAGE_006"

    # Lock Errors (7xx)
    LOCK_ACQUISITION_FAILED = "LOCK_001"
    LOCK_TIMEOUT = "LOCK_002"
    LOCK_STALE = "LOCK_003"
    CONCURRENCY_ERROR = "LOCK_004"

    # Validation Errors (8xx)
    VALIDATION_FAILED = "VALID_001"
    SCHEMA_VALIDATION_FAILED = "VALID_002"
    NAME_VALIDATION_FAILED = "VALID_003"
    PATH_VALIDATION_FAILED = "VALID_004"

    # Configuration Errors (9xx)
    CONFIG_INVALID = "CONFIG_001"
    CONFIG_MISSING = "CONFIG_002"
    BACKEND_NOT_CONFIGURED = "CONFIG_003"

    # Resource Errors (10xx)
    RESOURCE_LIMIT_EXCEEDED = "RESOURCE_001"
    RESOURCE_NOT_AVAILABLE = "RESOURCE_002"
    CLEANUP_FAILED = "RESOURCE_003"

    # General Errors
    UNKNOWN_ERROR = "UNKNOWN_001"
    OPERATION_FAILED = "OP_001"


@dataclass
class ErrorContext:
    """
    Contextual information for error debugging and logging.
    """

    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    operation: Optional[str] = None
    component: Optional[str] = None
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    additional_info: Dict[str, Any] = field(default_factory=dict)
    stack_trace: Optional[str] = None
    correlation_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging."""
        return {
            "timestamp": self.timestamp,
            "operation": self.operation,
            "component": self.component,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "additional_info": self.additional_info,
            "correlation_id": self.correlation_id,
            "stack_trace": self.stack_trace,
        }


class MLOpsException(Exception):
    """
    Base exception for all MLOps errors.
    """

    error_code: ErrorCode = ErrorCode.UNKNOWN_ERROR

    def __init__(
        self,
        message: str,
        error_code: Optional[ErrorCode] = None,
        context: Optional[ErrorContext] = None,
        cause: Optional[Exception] = None,
        suggestions: Optional[List[str]] = None,
    ):
        self.message = message
        self.error_code = error_code or self.__class__.error_code
        self.context = context or ErrorContext()
        self.cause = cause
        self.suggestions = suggestions or []

        # Auto-populate stack_trace from cause when available
        if cause is not None and self.context.stack_trace is None:
            self.context.stack_trace = "".join(
                traceback.format_exception(type(cause), cause, cause.__traceback__)
            )

        # Build full message
        full_message = f"[{self.error_code.value}] {message}"
        if cause:
            full_message += f" (caused by: {cause})"

        super().__init__(full_message)

    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for logging/serialization."""
        return {
            "error_code": self.error_code.value,
            "message": self.message,
            "context": self.context.to_dict() if self.context else None,
            "suggestions": self.suggestions,
            "cause": str(self.cause) if self.cause else None,
            "exception_type": self.__class__.__name__,
        }

    def with_context(self, **kwargs) -> "MLOpsException":
        """Add context information and return self for chaining."""
        for key, value in kwargs.items():
            if hasattr(self.context, key):
                setattr(self.context, key, value)
            else:
                self.context.additional_info[key] = value
        return self

    def with_suggestion(self, suggestion: str) -> "MLOpsException":
        """Add a suggestion and return self for chaining."""
        self.suggestions.append(suggestion)
        return self


class ModelNotFoundError(MLOpsException):
    """Raised when a requested model is not found in the registry."""

    error_code = ErrorCode.MODEL_NOT_FOUND

    def __init__(
        self,
        model_name: str,
        version: Optional[int] = None,
        **kwargs,
    ):
        self.model_name = model_name
        self.version = version

        if version:
            msg = f"Model '{model_name}' version {version} not found in registry"
            error_code = ErrorCode.MODEL_VERSION_NOT_FOUND
        else:
            msg = f"Model '{model_name}' not found in registry"
            error_code = ErrorCode.MODEL_NOT_FOUND

        suggestions = [
            f"Check if model name '{model_name}' is spelled correctly",
            "Use registry.list_models() to see available models",
        ]
        if version:
            suggestions.append(
                f"Use registry.list_model_versions('{model_name}') to see available versions"
            )

        context = ErrorContext(
            operation="get_model",
            component="model_registry",
            resource_type="model",
            resource_id=model_name,
            additional_info={"version": version} if version else {},
        )

        super().__init__(
            message=msg,
            error_code=error_code,
            context=context,
            suggestions=suggestions,
            **kwargs,
        )


class PromotionGateError(MLOpsException):
    """Raised when a model fails the promotion policy gate."""

    error_code = ErrorCode.MODEL_PROMOTION_FAILED

    def __init__(self, model_name: str, version: int, reason: str, **kwargs):
        self.model_name = model_name
        self.version = version

        context = ErrorContext(
            operation="promote_model",
            component="model_registry",
            resource_type="model",
            resource_id=model_name,
            additional_info={"version": version},
        )

        super().__init__(
            message=f"Promotion of '{model_name}' v{version} blocked by policy: {reason}",
            error_code=ErrorCode.MODEL_PROMOTION_FAILED,
            context=context,
            suggestions=[
                "Improve the candidate model so it passes the gate",
                "Use force=True (with a reason) to bypass the gate; the bypass is audit-logged",
            ],
            **kwargs,
        )


class ModelVersionConflictError(MLOpsException):
    """Raised when attempting to create a model version that already exists."""

    error_code = ErrorCode.MODEL_VERSION_CONFLICT

    def __init__(self, model_name: str, version: int, **kwargs):
        self.model_name = model_name
        self.version = version

        msg = (
            f"Model '{model_name}' version {version} already exists. "
            f"Use a different version or update the existing one."
        )

        context = ErrorContext(
            operation="register_model",
            component="model_registry",
            resource_type="model",
            resource_id=model_name,
            additional_info={"version": version},
        )

        super().__init__(
            message=msg,
            context=context,
            suggestions=[
                "Use registry.get_model_version() to get the latest version first",
                "Let the registry auto-increment the version by not specifying one",
            ],
            **kwargs,
        )


class ProtectedVersionError(MLOpsException):
    """Raised when deleting a model version currently in Production without force=True."""

    error_code = ErrorCode.MODEL_VERSION_PROTECTED

    def __init__(self, model_name: str, version: int, stage: str = "Production", **kwargs):
        self.model_name = model_name
        self.version = version

        context = ErrorContext(
            operation="delete_model_version",
            component="model_registry",
            resource_type="model",
            resource_id=model_name,
            additional_info={"version": version, "stage": stage},
        )

        super().__init__(
            message=(
                f"Refusing to delete '{model_name}' v{version}: it is currently in "
                f"{stage} stage. Demote it first, or pass force=True to delete anyway."
            ),
            error_code=ErrorCode.MODEL_VERSION_PROTECTED,
            context=context,
            suggestions=[
                f"Promote a different version to demote v{version} first",
                "Pass force=True to delete_model_version() if this is intentional",
            ],
            **kwargs,
        )


class ExperimentNotFoundError(MLOpsException):
    """Raised when a requested experiment is not found."""

    error_code = ErrorCode.EXPERIMENT_NOT_FOUND

    def __init__(self, experiment_id: str, **kwargs):
        self.experiment_id = experiment_id
        super().__init__(
            message=f"Experiment with ID '{experiment_id}' not found",
            context=ErrorContext(
                operation="get_experiment",
                component="experiment_tracker",
                resource_type="experiment",
                resource_id=experiment_id,
            ),
            suggestions=[
                "Check if the experiment ID is correct",
                "Use tracker.create_experiment() to create a new experiment",
            ],
            **kwargs,
        )


class RunNotFoundError(MLOpsException):
    """Raised when a requested run is not found."""

    error_code = ErrorCode.RUN_NOT_FOUND

    def __init__(self, run_id: str, **kwargs):
        self.run_id = run_id
        super().__init__(
            message=f"Run with ID '{run_id}' not found",
            context=ErrorContext(
                operation="get_run",
                component="experiment_tracker",
                resource_type="run",
                resource_id=run_id,
            ),
            suggestions=[
                "Check if the run ID is correct",
                "The run may have been deleted or never created",
            ],
            **kwargs,
        )


class RunNotActiveError(MLOpsException):
    """Raised when attempting to operate on an inactive run."""

    error_code = ErrorCode.RUN_NOT_ACTIVE

    def __init__(self, run_id: str, **kwargs):
        self.run_id = run_id
        super().__init__(
            message=f"Run '{run_id}' is not active. Use get_run() to access completed runs.",
            context=ErrorContext(
                operation="modify_run",
                component="experiment_tracker",
                resource_type="run",
                resource_id=run_id,
            ),
            suggestions=[
                "Use tracker.start_run() to start a new run",
                "Use tracker.get_run() to read completed runs",
            ],
            **kwargs,
        )


class RunLimitExceededError(MLOpsException):
    """Raised when maximum active runs limit is exceeded."""

    error_code = ErrorCode.RUN_LIMIT_EXCEEDED

    def __init__(self, current: int, limit: int, **kwargs):
        self.current = current
        self.limit = limit
        super().__init__(
            message=f"Maximum active runs limit reached ({current}/{limit})",
            context=ErrorContext(
                operation="start_run",
                component="experiment_tracker",
                resource_type="run",
                additional_info={"current": current, "limit": limit},
            ),
            suggestions=[
                "End some existing runs with tracker.end_run()",
                "Increase max_active_runs in configuration",
                "Use tracker.cleanup_stale_runs() to clean up orphaned runs",
            ],
            **kwargs,
        )


class InvalidMetricError(MLOpsException):
    """Raised when attempting to log an invalid metric value."""

    error_code = ErrorCode.INVALID_METRIC

    def __init__(self, key: str, value: Any, reason: str, **kwargs):
        self.key = key
        self.value = value
        self.reason = reason
        msg = (
            f"Invalid metric '{key}' with value {value!r}: {reason}. "
            f"Metrics must be numeric (int or float)."
        )
        super().__init__(
            message=msg,
            context=ErrorContext(
                operation="log_metric",
                component="experiment_tracker",
                resource_type="metric",
                resource_id=key,
                additional_info={"value": repr(value), "value_type": type(value).__name__},
            ),
            suggestions=[
                "Ensure metric values are int or float",
                "Check for NaN or Infinity values",
                f"Current value type: {type(value).__name__}",
            ],
            **kwargs,
        )


class InvalidParameterError(MLOpsException):
    """Raised when attempting to log an invalid parameter."""

    error_code = ErrorCode.INVALID_PARAMETER

    def __init__(self, key: str, reason: str, **kwargs):
        self.key = key
        self.reason = reason
        super().__init__(
            message=f"Invalid parameter '{key}': {reason}",
            context=ErrorContext(
                operation="log_parameter",
                component="experiment_tracker",
                resource_type="parameter",
                resource_id=key,
            ),
            suggestions=[
                "Parameter names must be non-empty strings",
                "Parameter values must be: str, int, float, bool, or None",
            ],
            **kwargs,
        )


class ArtifactNotFoundError(MLOpsException):
    """Raised when a requested artifact is not found."""

    error_code = ErrorCode.ARTIFACT_NOT_FOUND

    def __init__(self, artifact_path: str, **kwargs):
        self.artifact_path = artifact_path
        super().__init__(
            message=f"Artifact not found at path: {artifact_path}",
            context=ErrorContext(
                operation="get_artifact",
                component="storage",
                resource_type="artifact",
                resource_id=artifact_path,
            ),
            suggestions=[
                "Check if the artifact path is correct",
                "Verify the artifact was uploaded successfully",
            ],
            **kwargs,
        )


class ArtifactValidationError(MLOpsException):
    """Raised when an artifact exists but is not valid/loadable for its declared
    framework (corrupt, empty, wrong extension, unsupported shape). Distinct from
    ``ArtifactNotFoundError``, which means nothing exists at the given path."""

    error_code = ErrorCode.ARTIFACT_INVALID

    def __init__(self, artifact_path: str, framework: str, reason: str, **kwargs):
        self.artifact_path = artifact_path
        self.framework = framework
        self.reason = reason
        super().__init__(
            message=(
                f"Artifact at '{artifact_path}' is not a valid '{framework}' artifact: {reason}"
            ),
            context=ErrorContext(
                operation="validate_artifact",
                component="model_registry",
                resource_type="artifact",
                resource_id=artifact_path,
            ),
            suggestions=[
                "Verify the artifact was saved with the declared framework",
                "Check the artifact is not corrupt or truncated",
            ],
            **kwargs,
        )


class StorageBackendError(MLOpsException):
    """Raised when storage backend operations fail."""

    error_code = ErrorCode.STORAGE_WRITE_FAILED

    def __init__(
        self,
        operation: str,
        path: str,
        cause: Exception,
        **kwargs,
    ):
        self.operation = operation
        self.path = path

        if operation == "delete":
            error_code = ErrorCode.STORAGE_DELETE_FAILED
        elif operation.startswith("read"):
            error_code = ErrorCode.STORAGE_READ_FAILED
        else:
            error_code = ErrorCode.STORAGE_WRITE_FAILED

        context = ErrorContext(
            operation=operation,
            component="storage",
            resource_type="file",
            resource_id=path,
            additional_info={"cause_type": type(cause).__name__},
        )

        super().__init__(
            message=f"Storage backend error during {operation} at '{path}': {cause}",
            error_code=error_code,
            context=context,
            cause=cause,
            suggestions=[
                "Check storage permissions",
                "Verify the path is accessible",
                "Check disk space availability",
            ],
            **kwargs,
        )


class StorageCircuitOpenError(MLOpsException):
    """Raised when storage circuit breaker is open."""

    error_code = ErrorCode.STORAGE_CIRCUIT_OPEN

    def __init__(self, backend_name: str, reset_time: float, **kwargs):
        self.backend_name = backend_name
        self.reset_time = reset_time

        context = ErrorContext(
            operation="storage_operation",
            component="storage",
            additional_info={
                "backend": backend_name,
                "reset_time_seconds": reset_time,
            },
        )

        super().__init__(
            message=(
                f"Storage circuit breaker '{backend_name}' is open. "
                f"Will reset in {reset_time:.1f} seconds."
            ),
            context=context,
            suggestions=[
                "Wait for the circuit breaker to reset",
                "Check underlying storage system health",
                "Consider manual circuit breaker reset if storage is healthy",
            ],
            **kwargs,
        )


class ModelRegistrationError(MLOpsException):
    """Raised when model registration fails."""

    error_code = ErrorCode.MODEL_REGISTRATION_FAILED

    def __init__(self, model_name: str, reason: str, **kwargs):
        self.model_name = model_name
        self.reason = reason
        super().__init__(
            message=f"Failed to register model '{model_name}': {reason}",
            context=ErrorContext(
                operation="register_model",
                component="model_registry",
                resource_type="model",
                resource_id=model_name,
            ),
            suggestions=[
                "Verify the artifact path exists and is accessible",
                "Check that model name is valid (alphanumeric, underscore, dash, dot)",
                "Ensure framework is supported",
            ],
            **kwargs,
        )


class SchemaValidationError(MLOpsException):
    """Raised when data schema validation fails."""

    error_code = ErrorCode.SCHEMA_VALIDATION_FAILED

    def __init__(self, schema_type: str, reason: str, **kwargs):
        self.schema_type = schema_type
        self.reason = reason
        super().__init__(
            message=f"Schema validation failed for {schema_type}: {reason}",
            context=ErrorContext(
                operation="validate_schema",
                component="validator",
                resource_type="schema",
                resource_id=schema_type,
            ),
            suggestions=[
                "Check the data format matches expected schema",
                "Verify all required fields are present",
            ],
            **kwargs,
        )


class ConcurrencyError(MLOpsException):
    """Raised when concurrent operations conflict."""

    error_code = ErrorCode.CONCURRENCY_ERROR

    def __init__(self, resource: str, operation: str, **kwargs):
        self.resource = resource
        self.operation = operation
        super().__init__(
            message=(
                f"Concurrency conflict: {operation} on '{resource}' failed. "
                f"Another process may be modifying the same resource."
            ),
            context=ErrorContext(
                operation=operation,
                component="locking",
                resource_type="lock",
                resource_id=resource,
            ),
            suggestions=[
                "Retry the operation after a short delay",
                "Use appropriate locking mechanisms",
                "Check for long-running operations on the same resource",
            ],
            **kwargs,
        )


class LockTimeoutError(MLOpsException):
    """Raised when lock acquisition times out."""

    error_code = ErrorCode.LOCK_TIMEOUT

    def __init__(self, lock_path: str, timeout: float, **kwargs):
        self.lock_path = lock_path
        self.timeout = timeout
        super().__init__(
            message=f"Lock acquisition timeout ({timeout}s) for: {lock_path}",
            context=ErrorContext(
                operation="acquire_lock",
                component="locking",
                resource_type="lock",
                resource_id=lock_path,
                additional_info={"timeout_seconds": timeout},
            ),
            suggestions=[
                "Increase the lock timeout",
                "Check for stale locks and clean them up",
                "Verify no other process is holding the lock",
            ],
            **kwargs,
        )


class ConfigurationError(MLOpsException):
    """Raised when configuration is invalid."""

    error_code = ErrorCode.CONFIG_INVALID

    def __init__(self, config_key: str, reason: str, **kwargs):
        self.config_key = config_key
        self.reason = reason
        super().__init__(
            message=f"Configuration error for '{config_key}': {reason}",
            context=ErrorContext(
                operation="validate_config",
                component="config",
                resource_type="configuration",
                resource_id=config_key,
            ),
            suggestions=[
                "Check the configuration values",
                "Review the documentation for valid configuration options",
            ],
            **kwargs,
        )


class BackendNotConfiguredError(MLOpsException):
    """Raised when a backend is not properly configured."""

    error_code = ErrorCode.BACKEND_NOT_CONFIGURED

    def __init__(self, backend_type: str, missing: str, **kwargs):
        self.backend_type = backend_type
        self.missing = missing
        super().__init__(
            message=f"Backend '{backend_type}' not configured: {missing}",
            context=ErrorContext(
                operation="initialize_backend",
                component="config",
                resource_type="backend",
                resource_id=backend_type,
            ),
            suggestions=[
                f"Set the required configuration: {missing}",
                "Use environment variables or configuration file",
            ],
            **kwargs,
        )


def create_error_response(exception: MLOpsException) -> Dict[str, Any]:
    """
    Create a standardized error response from an exception.
    """
    return {
        "error": True,
        "error_code": exception.error_code.value,
        "message": exception.message,
        "suggestions": exception.suggestions,
        "context": exception.context.to_dict() if exception.context else None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def wrap_exception(
    exception: Exception,
    error_code: ErrorCode = ErrorCode.UNKNOWN_ERROR,
    context: Optional[ErrorContext] = None,
) -> MLOpsException:
    """
    Wrap a generic exception in an MLOpsException.
    """
    if isinstance(exception, MLOpsException):
        return exception

    return MLOpsException(
        message=str(exception),
        error_code=error_code,
        context=context,
        cause=exception,
    )
