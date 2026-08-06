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

The exception types ``ducta.core`` raises.

The core used to signal every kind of problem with a bare ``ValueError``,
``RuntimeError`` or — in the sanity-check path — a literal ``raise
Exception(...)``. Callers that needed to tell those apart had no type to match
on, so they resorted to inspecting the *text*:

    if type(e).__name__ == "QualityGateBlocked": ...
    if error.startswith("[QualityGateBlocked]"): ...
    if isinstance(result_df, str) and "://" in result_df: ...

String matching is invisible to the type checker, silently stops working when a
message is reworded, and cannot carry structured detail. Each class here answers
one question a caller actually asks — *is this the user's config, their node's
code, or the engine?* — and carries the context needed to report it, so the API
can map to HTTP codes and the CLI to exit codes without parsing prose.

Every class derives from :class:`DuctaError`, so ``except DuctaError`` catches
anything the core raises on purpose while still letting genuine bugs (a
``TypeError`` from a mistake in ducta itself) propagate untouched.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class DuctaError(Exception):
    """Base for every error ``ducta.core`` raises deliberately.

    ``exit_code`` is the CLI exit status and ``http_status`` the API response
    code for this class of failure, so neither layer has to maintain its own
    mapping from error text to status.
    """

    #: Default CLI exit code (see ``ducta.console.core.ExitCode``).
    exit_code: int = 1
    #: Default HTTP status for the API layer.
    http_status: int = 500
    #: Whether retrying the identical operation could plausibly succeed.
    retryable: bool = False

    def __init__(self, message: str, **context: Any) -> None:
        super().__init__(message)
        self.message = message
        self.context: Dict[str, Any] = {k: v for k, v in context.items() if v is not None}

    def to_dict(self) -> Dict[str, Any]:
        """Structured form, for API responses and structured logs."""
        return {
            "error": type(self).__name__,
            "message": self.message,
            "retryable": self.retryable,
            **self.context,
        }


# ── Configuration ────────────────────────────────────────────────────────────


class ConfigurationError(DuctaError, ValueError):
    """The project's configuration is wrong. Nothing ran, and nothing will.

    Also a ``ValueError``, which is what these raised before this taxonomy
    existed — so every ``except ValueError`` already written against the core
    keeps working. Same idiom as ``ducta.mlrun.validators.ValidationError``.
    """

    exit_code = 2  # ExitCode.CONFIGURATION_ERROR
    http_status = 400


class PipelineNotFoundError(ConfigurationError):
    """The requested pipeline does not exist in the configuration."""

    http_status = 404

    def __init__(self, pipeline: str, available: Optional[List[str]] = None) -> None:
        listing = ", ".join(sorted(available)) if available else "(none)"
        super().__init__(
            f"Pipeline '{pipeline}' not found. Available: {listing}",
            pipeline=pipeline,
            available=sorted(available) if available else [],
        )


class NodeNotFoundError(ConfigurationError):
    """A pipeline references a node that has no configuration."""

    http_status = 404

    def __init__(self, node: str, available: Optional[List[str]] = None) -> None:
        available = available or []
        shown = ", ".join(available[:10])
        if len(available) > 10:
            shown += f", ... (total: {len(available)} nodes)"
        super().__init__(
            f"Node '{node}' not found in configuration. Available nodes: {shown}",
            node=node,
        )


class DependencyCycleError(ConfigurationError):
    """A cycle in the node DAG or in inter-pipeline ``depends_on``."""

    def __init__(self, message: str, cycle: Optional[List[str]] = None) -> None:
        super().__init__(message, cycle=cycle)


class PreflightError(ConfigurationError):
    """Preflight validation rejected the pipeline before any node ran."""

    def __init__(self, pipeline: str, errors: List[str]) -> None:
        details = "\n  - ".join(errors)
        super().__init__(
            f"Preflight validation failed for pipeline '{pipeline}' "
            f"({len(errors)} error(s)):\n  - {details}\n"
            f"Fix the configuration or run `ducta config validate` for details. "
            f"Set global_settings.preflight_enabled=false to bypass.",
            pipeline=pipeline,
            errors=errors,
        )


# ── Execution ────────────────────────────────────────────────────────────────


class ExecutionError(DuctaError, RuntimeError):
    """A pipeline started but did not complete its work.

    Also a ``RuntimeError`` for backward compatibility with existing
    ``except RuntimeError`` call sites, which is what the core raised for these
    before the taxonomy existed.
    """

    exit_code = 4  # ExitCode.EXECUTION_ERROR
    http_status = 500


class NodeExecutionError(ExecutionError):
    """A node failed.

    Carries the node, the phase it failed in and the original exception, so the
    root cause survives the coordinator deliberately swallowing per-node
    exceptions to let independent branches finish.
    """

    def __init__(
        self,
        node: str,
        cause: Optional[BaseException] = None,
        phase: str = "execute",
        message: Optional[str] = None,
    ) -> None:
        detail = f"{type(cause).__name__}: {cause}" if cause else "unknown error"
        super().__init__(
            message or f"Node '{node}' failed during {phase} — {detail}",
            node=node,
            phase=phase,
            cause_type=type(cause).__name__ if cause else None,
        )
        self.node = node
        self.phase = phase
        self.cause = cause
        if cause is not None:
            self.__cause__ = cause


class NodeTimeoutError(ExecutionError):
    """A node exceeded its configured timeout.

    Distinct from a node raising the builtin ``TimeoutError`` from its own code
    (a socket or subprocess timeout), which is a plain node failure — the two
    were previously indistinguishable because
    ``concurrent.futures.TimeoutError`` *is* the builtin on Python >= 3.11.
    """

    retryable = True

    def __init__(self, node: str, timeout_seconds: float) -> None:
        super().__init__(
            f"Node '{node}' exceeded its timeout ({timeout_seconds:.0f}s)",
            node=node,
            timeout_seconds=timeout_seconds,
        )
        self.node = node
        self.timeout_seconds = timeout_seconds


class PipelineExecutionError(ExecutionError):
    """The pipeline as a whole failed, naming the node that caused it."""

    def __init__(
        self,
        pipeline: str,
        message: Optional[str] = None,
        failed_nodes: Optional[List[str]] = None,
        cause: Optional[BaseException] = None,
    ) -> None:
        super().__init__(
            message or f"Pipeline '{pipeline}' execution failed",
            pipeline=pipeline,
            failed_nodes=failed_nodes,
        )
        self.pipeline = pipeline
        self.failed_nodes = failed_nodes or []
        if cause is not None:
            self.__cause__ = cause


class ChainExecutionError(ExecutionError):
    """A pipeline chain stopped at one of its steps.

    Names the pipelines that were cancelled as a consequence, which is the part
    a user needs in order to know what state their data is in.
    """

    def __init__(
        self,
        failed_pipeline: str,
        step: int,
        total: int,
        cancelled: Optional[List[str]] = None,
        cause: Optional[BaseException] = None,
    ) -> None:
        message = f"Pipeline chain failed at '{failed_pipeline}' (step {step}/{total})."
        if cancelled:
            message += f" Cancelled: {cancelled}."
        super().__init__(
            message,
            failed_pipeline=failed_pipeline,
            step=step,
            total=total,
            cancelled=cancelled,
        )
        self.failed_pipeline = failed_pipeline
        self.cancelled = cancelled or []
        if cause is not None:
            self.__cause__ = cause


class MLOpsRequiredError(ExecutionError):
    """MLOps could not be initialized and ``mlops_required`` is set."""

    def __init__(self, reason: str) -> None:
        super().__init__(
            f"MLOps initialization failed and is required by config "
            f"(mlops_required=true). Pipeline aborted. Error: {reason}",
            reason=reason,
        )


# ── Data ─────────────────────────────────────────────────────────────────────


class DataError(DuctaError, RuntimeError):
    """The pipeline ran but the data did not meet expectations.

    Also a ``RuntimeError``: the sanity-check path used to raise a bare
    ``Exception``, and callers that broadened to ``except RuntimeError`` should
    not start missing it.
    """

    exit_code = 4
    http_status = 422


class SchemaValidationError(DataError):
    """A node returned something that is not a usable DataFrame."""


class SanityCheckFailedError(DataError):
    """Preflight sanity checks failed with ``fail_fast``.

    Replaces a literal ``raise Exception(...)``, which could not be caught
    selectively by anything and read as an internal error to every caller.
    """

    def __init__(self, node: str, errors_count: int) -> None:
        super().__init__(
            f"Sanity checks failed for node '{node}': {errors_count} error(s)",
            node=node,
            errors_count=errors_count,
        )
        self.node = node
        self.errors_count = errors_count


__all__ = [
    "ChainExecutionError",
    "ConfigurationError",
    "DataError",
    "DependencyCycleError",
    "DuctaError",
    "ExecutionError",
    "MLOpsRequiredError",
    "NodeExecutionError",
    "NodeNotFoundError",
    "NodeTimeoutError",
    "PipelineExecutionError",
    "PipelineNotFoundError",
    "PreflightError",
    "SanityCheckFailedError",
    "SchemaValidationError",
]
