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

import asyncio
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Dict, Optional


class StreamingError(Exception):
    """Base exception for streaming operations with enhanced context."""

    def __init__(
        self,
        message: str,
        error_code: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
    ):
        self.message = message
        self.error_code = error_code
        self.context = context or {}
        self.cause = cause

        # Build enhanced error message
        enhanced_message = self._build_enhanced_message()
        super().__init__(enhanced_message)

    def _build_enhanced_message(self) -> str:
        """Build enhanced error message with context."""
        parts = [self.message]

        if self.error_code:
            parts.insert(0, f"[{self.error_code}]")

        if self.context:
            context_str = ", ".join([f"{k}={v}" for k, v in self.context.items()])
            parts.append(f"Context: {context_str}")

        if self.cause:
            parts.append(f"Caused by: {str(self.cause)}")

        return " - ".join(parts)

    def add_context(self, key: str, value: Any) -> "StreamingError":
        """Add context information."""
        self.context[key] = value
        return self


class StreamingValidationError(StreamingError):
    """Raised when streaming configuration validation fails."""

    def __init__(
        self,
        message: str,
        field: Optional[str] = None,
        expected: Optional[str] = None,
        actual: Optional[str] = None,
        **kwargs,
    ):
        context = kwargs.pop("context", {})
        if field:
            context["field"] = field
        if expected:
            context["expected"] = expected
        if actual:
            context["actual"] = actual
        super().__init__(message, error_code="VALIDATION_ERROR", context=context, **kwargs)


class _ContextualStreamingError(StreamingError):
    """Base class for streaming errors with context building."""

    ERROR_CODE: str = "STREAMING_ERROR"

    def __init__(self, message: str, context_kwargs: Dict[str, Optional[str]], **kwargs):
        context = kwargs.pop("context", {})
        for key, value in context_kwargs.items():
            if value is not None:
                context[key] = value
        super().__init__(message, error_code=self.ERROR_CODE, context=context, **kwargs)


class StreamingFormatNotSupportedError(_ContextualStreamingError):
    """Raised when a streaming format is not supported."""

    ERROR_CODE = "UNSUPPORTED_FORMAT"

    def __init__(
        self,
        message: str,
        format_name: Optional[str] = None,
        supported_formats: Optional[list] = None,
        **kwargs,
    ):
        context_kwargs = {
            "format_name": format_name,
            "supported_formats": str(supported_formats) if supported_formats is not None else None,
        }
        super().__init__(message, context_kwargs, **kwargs)


class StreamingQueryError(_ContextualStreamingError):
    """Raised when streaming query operations fail."""

    ERROR_CODE = "QUERY_ERROR"

    def __init__(
        self,
        message: str,
        query_id: Optional[str] = None,
        query_name: Optional[str] = None,
        query_status: Optional[str] = None,
        **kwargs,
    ):
        context_kwargs = {
            "query_id": query_id,
            "query_name": query_name,
            "query_status": query_status,
        }
        super().__init__(message, context_kwargs, **kwargs)


class StreamingPipelineError(_ContextualStreamingError):
    """Raised when streaming pipeline operations fail."""

    ERROR_CODE = "PIPELINE_ERROR"

    def __init__(
        self,
        message: str,
        pipeline_name: Optional[str] = None,
        execution_id: Optional[str] = None,
        pipeline_status: Optional[str] = None,
        failed_nodes: Optional[list] = None,
        **kwargs,
    ):
        context_kwargs = {
            "pipeline_name": pipeline_name,
            "execution_id": execution_id,
            "pipeline_status": pipeline_status,
            "failed_nodes": str(failed_nodes) if failed_nodes is not None else None,
        }
        super().__init__(message, context_kwargs, **kwargs)


class StreamingConfigurationError(_ContextualStreamingError):
    """Raised when streaming configuration is invalid."""

    ERROR_CODE = "CONFIG_ERROR"

    def __init__(
        self,
        message: str,
        config_section: Optional[str] = None,
        config_value: Optional[Any] = None,
        **kwargs,
    ):
        context_kwargs = {
            "config_section": config_section,
            "config_value": str(config_value) if config_value is not None else None,
        }
        super().__init__(message, context_kwargs, **kwargs)


class StreamingTimeoutError(_ContextualStreamingError):
    """Raised when streaming operations timeout."""

    ERROR_CODE = "TIMEOUT_ERROR"

    def __init__(
        self,
        message: str,
        timeout_seconds: Optional[float] = None,
        operation: Optional[str] = None,
        **kwargs,
    ):
        context_kwargs = {
            "timeout_seconds": str(timeout_seconds) if timeout_seconds is not None else None,
            "operation": operation,
        }
        super().__init__(message, context_kwargs, **kwargs)


# Error handling utilities
def handle_streaming_error(func):
    """Decorator to handle streaming errors with enhanced context.

    Supports both synchronous and asynchronous functions.
    """
    func_name = getattr(func, "__name__", str(func))

    def _make_error(e: Exception, args: tuple = (), kwargs: dict = None) -> StreamingError:
        context = {
            "function": func_name,
            "args_count": len(args),
            "kwargs_keys": sorted(kwargs.keys()) if kwargs else [],
        }
        return StreamingError(
            f"Unexpected error in {func_name}: {str(e)}",
            error_code="UNEXPECTED_ERROR",
            context=context,
            cause=e,
        )

    if asyncio.iscoroutinefunction(func):

        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except StreamingError:
                raise
            except Exception as e:
                raise _make_error(e, args, kwargs) from e

        return async_wrapper

    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except StreamingError:
            raise
        except Exception as e:
            raise _make_error(e, args, kwargs) from e

    return wrapper


def create_error_context(
    operation: str, component: Optional[str] = None, **additional_context
) -> Dict[str, Any]:
    """Create standardized error context."""
    context = {
        "operation": operation,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if component:
        context["component"] = component

    context.update(additional_context)
    return context
