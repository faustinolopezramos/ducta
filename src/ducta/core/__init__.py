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

# ---------------------------------------------------------------------------
# Certificates & security
# ---------------------------------------------------------------------------
from ducta.core.certificate import (
    RunCertificate,
    VerifyResult,
    build_certificate,
    certificate_dir,
    is_enabled,
    key_id_of,
    load_certificate,
    resolve_signing_key,
    verify_certificate,
    write_certificate,
)

# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
from ducta.core.commands import Command, MLNodeCommand, NodeCommand, NodeFunction
from ducta.core.dependency_inference import (
    build_producer_map,
    extract_input_keys,
    extract_output_keys,
    infer_pipeline_depends_on,
    merge_pipeline_depends_on,
    resolve_node_dependencies,
)
from ducta.core.dependency_resolver import DependencyResolver, detect_cycles_dfs

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
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
from ducta.core.execution import (
    FunctionLoader,
    IngestionExecutor,
    MLContextBuilder,
    NodeExecutor,
    OutputWriter,
    ParallelCoordinator,
    QualityCheckExecutor,
    ThreadSafeExecutionState,
)

# ---------------------------------------------------------------------------
# Pipeline execution
# ---------------------------------------------------------------------------
from ducta.core.executors import (
    BaseExecutor,
    BatchExecutor,
    HybridExecutor,
    PipelineExecutor,
    StreamingExecutor,
)
from ducta.core.import_security import ModuleImportError, SecureModuleImporter

# ---------------------------------------------------------------------------
# Run ledger
# ---------------------------------------------------------------------------
from ducta.core.ledger import RunLedger, ledger_for

# ---------------------------------------------------------------------------
# ML context & MLOps integration
# ---------------------------------------------------------------------------
from ducta.core.ml_context import MLNodeContext
from ducta.core.mlflow_node_executor import MLflowNodeExecutor, create_mlflow_executor
from ducta.core.mlops_auto_config import MLOpsAutoConfigurator
from ducta.core.mlops_integration import MLInfoConfigLoader, MLOpsExecutorIntegration
from ducta.core.pipeline_dependency_resolver import PipelineDependencyResolver

# ---------------------------------------------------------------------------
# Pipeline state & dependency resolution
# ---------------------------------------------------------------------------
from ducta.core.pipeline_state import (
    CircuitBreaker,
    CircuitBreakerState,
    NodeExecutionInfo,
    NodeStatus,
    NodeType,
    UnifiedPipelineState,
)

# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
from ducta.core.pipeline_validator import PipelineValidator

# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------
from ducta.core.preflight import PreflightReport, validate_all_pipelines, validate_pipeline
from ducta.core.resilience import RetryPolicy

# ---------------------------------------------------------------------------
# Resource management & resilience
# ---------------------------------------------------------------------------
from ducta.core.resource_manager import (
    ManagedResource,
    ResourceManager,
    ResourceType,
    get_resource_manager,
)

# ---------------------------------------------------------------------------
# Run results
# ---------------------------------------------------------------------------
from ducta.core.results import NodeOutcome, PipelineRunResult, RunStatus

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
from ducta.core.settings import (
    CoreSettings,
    clamp_timeout,
    coerce_bool,
    coerce_int,
)
from ducta.core.split_validator import (
    SplitValidationError,
    document_split_semantics,
    log_split_leakage_checks,
    validate_split_config,
)

# ---------------------------------------------------------------------------
# Sweep / hyperparameter search
# ---------------------------------------------------------------------------
from ducta.core.sweep import SweepError, expand_sweep, load_sweep_spec, new_sweep_id

# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------
from ducta.core.utils import (
    compile_function,
    extract_dependency_name,
    extract_pipeline_nodes,
    get_node_dependencies,
    is_jit_enabled,
    jit,
    normalize_dependencies,
)

__all__ = [
    # pipeline execution
    "BaseExecutor",
    "BatchExecutor",
    "HybridExecutor",
    "PipelineExecutor",
    "StreamingExecutor",
    "FunctionLoader",
    "IngestionExecutor",
    "MLContextBuilder",
    "NodeExecutor",
    "OutputWriter",
    "ParallelCoordinator",
    "QualityCheckExecutor",
    "ThreadSafeExecutionState",
    # pipeline state & dependency
    "CircuitBreaker",
    "CircuitBreakerState",
    "NodeExecutionInfo",
    "NodeStatus",
    "NodeType",
    "UnifiedPipelineState",
    "DependencyResolver",
    "detect_cycles_dfs",
    "build_producer_map",
    "extract_input_keys",
    "extract_output_keys",
    "infer_pipeline_depends_on",
    "merge_pipeline_depends_on",
    "resolve_node_dependencies",
    "PipelineDependencyResolver",
    # validation
    "PipelineValidator",
    "SplitValidationError",
    "document_split_semantics",
    "log_split_leakage_checks",
    "validate_split_config",
    # preflight
    "PreflightReport",
    "validate_all_pipelines",
    "validate_pipeline",
    # commands
    "Command",
    "MLNodeCommand",
    "NodeCommand",
    "NodeFunction",
    # MLOps
    "MLNodeContext",
    "MLInfoConfigLoader",
    "MLOpsExecutorIntegration",
    "MLOpsAutoConfigurator",
    "MLflowNodeExecutor",
    "create_mlflow_executor",
    # certificates & security
    "RunCertificate",
    "VerifyResult",
    "build_certificate",
    "certificate_dir",
    "is_enabled",
    "key_id_of",
    "load_certificate",
    "resolve_signing_key",
    "verify_certificate",
    "write_certificate",
    "ModuleImportError",
    "SecureModuleImporter",
    # resource management & resilience
    "ManagedResource",
    "ResourceManager",
    "ResourceType",
    "get_resource_manager",
    "RetryPolicy",
    # errors
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
    # run ledger
    "RunLedger",
    "ledger_for",
    # run results
    "NodeOutcome",
    "PipelineRunResult",
    "RunStatus",
    # settings
    "CoreSettings",
    "clamp_timeout",
    "coerce_bool",
    "coerce_int",
    # sweep
    "SweepError",
    "expand_sweep",
    "load_sweep_spec",
    "new_sweep_id",
    # utilities
    "compile_function",
    "extract_dependency_name",
    "extract_pipeline_nodes",
    "get_node_dependencies",
    "is_jit_enabled",
    "jit",
    "normalize_dependencies",
]
