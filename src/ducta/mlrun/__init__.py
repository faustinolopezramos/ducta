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
# Baseline / drift detection
# ---------------------------------------------------------------------------
from ducta.mlrun.baseline import compare_to_baseline, trivial_baseline_metrics

# ---------------------------------------------------------------------------
# Concurrency / locking
# ---------------------------------------------------------------------------
from ducta.mlrun.concurrency import (
    FileLock,
    LockManager,
    OptimisticLock,
    ReadWriteLock,
    SafeTransaction,
    Transaction,
    TransactionError,
    get_lock_manager,
    transactional_operation,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
from ducta.mlrun.config import MLOpsConfig, MLOpsContext

# ---------------------------------------------------------------------------
# Environment helpers
# ---------------------------------------------------------------------------
from ducta.mlrun.environment import EnvironmentSnapshot

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------
from ducta.mlrun.exceptions import (
    ArtifactNotFoundError,
    ArtifactValidationError,
    BackendNotConfiguredError,
    ConcurrencyError,
    ConfigurationError,
    ErrorCode,
    ErrorContext,
    ExperimentNotFoundError,
    InvalidMetricError,
    InvalidParameterError,
    LockTimeoutError,
    MLOpsException,
    ModelNotFoundError,
    ModelRegistrationError,
    ModelVersionConflictError,
    PromotionGateError,
    ProtectedVersionError,
    ResilienceError,
    ResourceLimitError,
    RunLimitExceededError,
    RunNotActiveError,
    RunNotFoundError,
    SchemaValidationError,
    StorageBackendError,
    StorageCircuitOpenError,
    create_error_response,
    wrap_exception,
)

# ---------------------------------------------------------------------------
# Experiment tracking
# ---------------------------------------------------------------------------
from ducta.mlrun.experiment_tracking import Experiment, ExperimentTracker, Metric, Run, RunStatus

# ---------------------------------------------------------------------------
# Data fingerprinting
# ---------------------------------------------------------------------------
from ducta.mlrun.fingerprint import DataFingerprint

# ---------------------------------------------------------------------------
# Garbage collection
# ---------------------------------------------------------------------------
from ducta.mlrun.gc import ModelGarbageCollector

# ---------------------------------------------------------------------------
# Hyperparameter search
# ---------------------------------------------------------------------------
from ducta.mlrun.hyperparams import (
    Distribution,
    HyperparamConfig,
    HyperparamConfigError,
    ParamGrid,
    expand_sweep_grid,
    load_hyperparams_config,
)

# ---------------------------------------------------------------------------
# Mlflow integration
# ---------------------------------------------------------------------------
from ducta.mlrun.mlflow import (
    MLflowConfig,
    MLflowHelper,
    MLflowNodeContext,
    MLflowPipelineTracker,
    is_mlflow_available,
)

# ---------------------------------------------------------------------------
# Model registry
# ---------------------------------------------------------------------------
from ducta.mlrun.model_registry import (
    ModelMetadata,
    ModelRegistry,
    ModelStage,
    ModelVersion,
    PromotionPolicy,
)

# ---------------------------------------------------------------------------
# Model persistence
# ---------------------------------------------------------------------------
from ducta.mlrun.persistence import infer_schema, persist_model

# ---------------------------------------------------------------------------
# Resilience / Retry
# ---------------------------------------------------------------------------
from ducta.mlrun.resilience import CircuitBreaker, ResourceLimits, RetryConfig

# ---------------------------------------------------------------------------
# Dataset splitting
# ---------------------------------------------------------------------------
from ducta.mlrun.split import SplitError, kfold_splits, split_dataframe

# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------
from ducta.mlrun.storage import StorageBackend, StorageMetadata

# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------
from ducta.mlrun.validators import (
    validate_artifact_type,
    validate_experiment_name,
    validate_framework,
    validate_metric_value,
    validate_model_name,
    validate_parameters,
    validate_run_name,
    validate_tags,
)

__all__ = [
    # exceptions
    "ArtifactNotFoundError",
    "ArtifactValidationError",
    "BackendNotConfiguredError",
    "ConfigurationError",
    "ConcurrencyError",
    "ErrorCode",
    "ErrorContext",
    "ExperimentNotFoundError",
    "InvalidMetricError",
    "InvalidParameterError",
    "LockTimeoutError",
    "MLOpsException",
    "ModelNotFoundError",
    "ModelRegistrationError",
    "ModelVersionConflictError",
    "ProtectedVersionError",
    "PromotionGateError",
    "ResilienceError",
    "ResourceLimitError",
    "RunLimitExceededError",
    "RunNotFoundError",
    "RunNotActiveError",
    "SchemaValidationError",
    "StorageBackendError",
    "StorageCircuitOpenError",
    "create_error_response",
    "wrap_exception",
    # resilience
    "CircuitBreaker",
    "ResourceLimits",
    "RetryConfig",
    # config
    "MLOpsConfig",
    "MLOpsContext",
    # storage
    "StorageBackend",
    "StorageMetadata",
    # model registry
    "ModelMetadata",
    "ModelRegistry",
    "ModelStage",
    "ModelVersion",
    "PromotionPolicy",
    # experiment tracking
    "Experiment",
    "ExperimentTracker",
    "Metric",
    "Run",
    "RunStatus",
    # mlflow
    "MLflowConfig",
    "MLflowHelper",
    "MLflowNodeContext",
    "MLflowPipelineTracker",
    "is_mlflow_available",
    # hyperparams
    "Distribution",
    "HyperparamConfig",
    "HyperparamConfigError",
    "ParamGrid",
    "expand_sweep_grid",
    "load_hyperparams_config",
    # fingerprinting
    "DataFingerprint",
    # baseline
    "compare_to_baseline",
    "trivial_baseline_metrics",
    # dataset split
    "SplitError",
    "kfold_splits",
    "split_dataframe",
    # validators
    "validate_artifact_type",
    "validate_experiment_name",
    "validate_framework",
    "validate_metric_value",
    "validate_model_name",
    "validate_parameters",
    "validate_run_name",
    "validate_tags",
    # concurrency
    "FileLock",
    "LockManager",
    "OptimisticLock",
    "ReadWriteLock",
    "SafeTransaction",
    "Transaction",
    "TransactionError",
    "get_lock_manager",
    "transactional_operation",
    # gc
    "ModelGarbageCollector",
    # environment
    "EnvironmentSnapshot",
    # persistence
    "infer_schema",
    "persist_model",
]
