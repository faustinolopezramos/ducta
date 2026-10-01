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

from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING, Any

from loguru import logger

try:
    __version__ = version("ducta")
except PackageNotFoundError:  # pragma: no cover - not installed (e.g. running from source)
    __version__ = "0.0.0+unknown"

# Silence the library by default (standard loguru pattern for libraries).
# Ducta emits no log records unless the consuming application explicitly turns
# them on with ``logger.enable("ducta")``. The CLI and API server do this when
# they configure their own handlers. This guarantees Ducta's internal module
# paths (its core) are never exposed to end users through stray import-time logs.
logger.disable("ducta")


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────
#
# The names below are the supported surface: what Ducta promises not to move
# without a deprecation. Everything else — `ducta.core.executors.batch`,
# `ducta.check.engine`, the ~400 names the submodules export — is internal, and
# importing from those paths couples you to a layout that is still moving.
#
# This matters now because "declare the public Python API stable" is the gate to
# leaving alpha. Without a façade, declaring stability would have meant freezing
# every internal module path anyone happened to import from.
#
# Resolved lazily through PEP 562's module `__getattr__`. Importing these eagerly
# would pull `ducta.core` (and transitively pyspark, mlflow, pydantic…) into
# every `import ducta`, and a bare `pip install ducta` deliberately supports
# `ducta template`, `ducta config` and `ducta certify` with none of those
# installed. `import ducta` stays cheap; `ducta.PipelineExecutor` pays for what
# it touches, and raises the underlying ImportError naming the missing extra.

_PUBLIC_API: dict[str, str] = {
    # Execution
    "PipelineExecutor": "ducta.core.executors",
    # Configuration
    "Context": "ducta.setting.contexts",
    "load_project": "ducta.setting.project_loader",
    # Run certificates
    "RunCertificate": "ducta.core.certificate",
    "build_certificate": "ducta.core.certificate",
    "load_certificate": "ducta.core.certificate",
    "verify_certificate": "ducta.core.certificate",
    # Data quality — `register_check` is the documented extension point
    "register_check": "ducta.check",
    "CheckResult": "ducta.check",
    "QualityReport": "ducta.check",
    # I/O extension points
    "ReaderFactory": "ducta.gate",
    "WriterFactory": "ducta.gate",
    # Errors, so `except ducta.DuctaError` works without knowing the layout
    "DuctaError": "ducta.core.errors",
    "ChainExecutionError": "ducta.core.errors",
    "ConfigurationError": "ducta.core.errors",
    "DataError": "ducta.core.errors",
    "DependencyCycleError": "ducta.core.errors",
    "ExecutionError": "ducta.core.errors",
    "MLOpsRequiredError": "ducta.core.errors",
    "NodeExecutionError": "ducta.core.errors",
    "NodeNotFoundError": "ducta.core.errors",
    "NodeTimeoutError": "ducta.core.errors",
    "PipelineExecutionError": "ducta.core.errors",
    "PipelineNotFoundError": "ducta.core.errors",
    "PreflightError": "ducta.core.errors",
    "SanityCheckFailedError": "ducta.core.errors",
    "SchemaValidationError": "ducta.core.errors",
}

if TYPE_CHECKING:  # pragma: no cover - for type checkers and IDE completion
    from ducta.check import CheckResult, QualityReport, register_check
    from ducta.core.certificate import (
        RunCertificate,
        build_certificate,
        load_certificate,
        verify_certificate,
    )
    from ducta.core.errors import (
        ChainExecutionError,
        ConfigurationError,
        DataError,
        DependencyCycleError,
        DuctaError,
        ExecutionError,
        MLOpsRequiredError,
        NodeExecutionError,
        NodeNotFoundError,
        NodeTimeoutError,
        PipelineExecutionError,
        PipelineNotFoundError,
        PreflightError,
        SanityCheckFailedError,
        SchemaValidationError,
    )
    from ducta.core.executors import PipelineExecutor
    from ducta.gate import ReaderFactory, WriterFactory
    from ducta.setting.contexts import Context
    from ducta.setting.project_loader import load_project


def __getattr__(name: str) -> Any:
    """Resolve a public name on first access (PEP 562)."""
    module_path = _PUBLIC_API.get(name)
    if module_path is None:
        raise AttributeError(f"module 'ducta' has no attribute {name!r}")

    import importlib

    return getattr(importlib.import_module(module_path), name)


def __dir__() -> list[str]:
    return sorted(__all__)


# Spelled out rather than derived from `_PUBLIC_API`, so that linters, IDEs and
# `from ducta import *` see the surface statically. `test_public_api.py` asserts
# the two stay in step.
__all__ = [
    "__version__",
    # Execution
    "PipelineExecutor",
    # Configuration
    "Context",
    "load_project",
    # Run certificates
    "RunCertificate",
    "build_certificate",
    "load_certificate",
    "verify_certificate",
    # Data quality
    "register_check",
    "CheckResult",
    "QualityReport",
    # I/O extension points
    "ReaderFactory",
    "WriterFactory",
    # Errors
    "DuctaError",
    "ChainExecutionError",
    "ConfigurationError",
    "DataError",
    "DependencyCycleError",
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
