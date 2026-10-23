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

import importlib
from typing import TYPE_CHECKING, Any, List

# Names are loaded on first use (PEP 562). The package used to import every submodule
# eagerly, which pulled MLflow, pandas and the experiment tracker into *every* process
# that touched ``ducta.mlrun.hyperparams`` — including ``ducta --help`` — for about
# 0.4 s and a line of MLflow log output. ``from ducta.mlrun import X`` and
# ``ducta.mlrun.X`` behave exactly as before.
_EXPORTS = {
    "compare_to_baseline": ("ducta.mlrun.baseline", "compare_to_baseline"),
    "trivial_baseline_metrics": ("ducta.mlrun.baseline", "trivial_baseline_metrics"),
    "FileLock": ("ducta.mlrun.concurrency", "FileLock"),
    "LockManager": ("ducta.mlrun.concurrency", "LockManager"),
    "OptimisticLock": ("ducta.mlrun.concurrency", "OptimisticLock"),
    "ReadWriteLock": ("ducta.mlrun.concurrency", "ReadWriteLock"),
    "SafeTransaction": ("ducta.mlrun.concurrency", "SafeTransaction"),
    "Transaction": ("ducta.mlrun.concurrency", "Transaction"),
    "TransactionError": ("ducta.mlrun.concurrency", "TransactionError"),
    "get_lock_manager": ("ducta.mlrun.concurrency", "get_lock_manager"),
    "transactional_operation": ("ducta.mlrun.concurrency", "transactional_operation"),
    "MLOpsConfig": ("ducta.mlrun.config", "MLOpsConfig"),
    "MLOpsContext": ("ducta.mlrun.config", "MLOpsContext"),
    "EnvironmentSnapshot": ("ducta.mlrun.environment", "EnvironmentSnapshot"),
    "ArtifactNotFoundError": ("ducta.mlrun.exceptions", "ArtifactNotFoundError"),
    "ArtifactValidationError": ("ducta.mlrun.exceptions", "ArtifactValidationError"),
    "BackendNotConfiguredError": ("ducta.mlrun.exceptions", "BackendNotConfiguredError"),
    "ConcurrencyError": ("ducta.mlrun.exceptions", "ConcurrencyError"),
    "ConfigurationError": ("ducta.mlrun.exceptions", "ConfigurationError"),
    "ErrorCode": ("ducta.mlrun.exceptions", "ErrorCode"),
    "ErrorContext": ("ducta.mlrun.exceptions", "ErrorContext"),
    "ExperimentNotFoundError": ("ducta.mlrun.exceptions", "ExperimentNotFoundError"),
    "InvalidMetricError": ("ducta.mlrun.exceptions", "InvalidMetricError"),
    "InvalidParameterError": ("ducta.mlrun.exceptions", "InvalidParameterError"),
    "LockTimeoutError": ("ducta.mlrun.exceptions", "LockTimeoutError"),
    "MLOpsException": ("ducta.mlrun.exceptions", "MLOpsException"),
    "ModelNotFoundError": ("ducta.mlrun.exceptions", "ModelNotFoundError"),
    "ModelRegistrationError": ("ducta.mlrun.exceptions", "ModelRegistrationError"),
    "ModelVersionConflictError": ("ducta.mlrun.exceptions", "ModelVersionConflictError"),
    "PromotionGateError": ("ducta.mlrun.exceptions", "PromotionGateError"),
    "ProtectedVersionError": ("ducta.mlrun.exceptions", "ProtectedVersionError"),
    "ResilienceError": ("ducta.mlrun.exceptions", "ResilienceError"),
    "ResourceLimitError": ("ducta.mlrun.exceptions", "ResourceLimitError"),
    "RunLimitExceededError": ("ducta.mlrun.exceptions", "RunLimitExceededError"),
    "RunNotActiveError": ("ducta.mlrun.exceptions", "RunNotActiveError"),
    "RunNotFoundError": ("ducta.mlrun.exceptions", "RunNotFoundError"),
    "SchemaValidationError": ("ducta.mlrun.exceptions", "SchemaValidationError"),
    "StorageBackendError": ("ducta.mlrun.exceptions", "StorageBackendError"),
    "StorageCircuitOpenError": ("ducta.mlrun.exceptions", "StorageCircuitOpenError"),
    "create_error_response": ("ducta.mlrun.exceptions", "create_error_response"),
    "wrap_exception": ("ducta.mlrun.exceptions", "wrap_exception"),
    "Experiment": ("ducta.mlrun.experiment_tracking", "Experiment"),
    "ExperimentTracker": ("ducta.mlrun.experiment_tracking", "ExperimentTracker"),
    "Metric": ("ducta.mlrun.experiment_tracking", "Metric"),
    "Run": ("ducta.mlrun.experiment_tracking", "Run"),
    "RunStatus": ("ducta.mlrun.experiment_tracking", "RunStatus"),
    "DataFingerprint": ("ducta.mlrun.fingerprint", "DataFingerprint"),
    "ModelGarbageCollector": ("ducta.mlrun.gc", "ModelGarbageCollector"),
    "Distribution": ("ducta.mlrun.hyperparams", "Distribution"),
    "HyperparamConfig": ("ducta.mlrun.hyperparams", "HyperparamConfig"),
    "HyperparamConfigError": ("ducta.mlrun.hyperparams", "HyperparamConfigError"),
    "ParamGrid": ("ducta.mlrun.hyperparams", "ParamGrid"),
    "expand_sweep_grid": ("ducta.mlrun.hyperparams", "expand_sweep_grid"),
    "load_hyperparams_config": ("ducta.mlrun.hyperparams", "load_hyperparams_config"),
    "MLflowConfig": ("ducta.mlrun.mlflow", "MLflowConfig"),
    "MLflowHelper": ("ducta.mlrun.mlflow", "MLflowHelper"),
    "MLflowNodeContext": ("ducta.mlrun.mlflow", "MLflowNodeContext"),
    "MLflowPipelineTracker": ("ducta.mlrun.mlflow", "MLflowPipelineTracker"),
    "is_mlflow_available": ("ducta.mlrun.mlflow", "is_mlflow_available"),
    "ModelMetadata": ("ducta.mlrun.model_registry", "ModelMetadata"),
    "ModelRegistry": ("ducta.mlrun.model_registry", "ModelRegistry"),
    "ModelStage": ("ducta.mlrun.model_registry", "ModelStage"),
    "ModelVersion": ("ducta.mlrun.model_registry", "ModelVersion"),
    "PromotionPolicy": ("ducta.mlrun.model_registry", "PromotionPolicy"),
    "infer_schema": ("ducta.mlrun.persistence", "infer_schema"),
    "persist_model": ("ducta.mlrun.persistence", "persist_model"),
    "TrainResult": ("ducta.mlrun.training", "TrainResult"),
    "train_with_search": ("ducta.mlrun.training", "train_with_search"),
    "run_summary": ("ducta.mlrun.summary", "run_summary"),
    "CircuitBreaker": ("ducta.mlrun.resilience", "CircuitBreaker"),
    "ResourceLimits": ("ducta.mlrun.resilience", "ResourceLimits"),
    "RetryConfig": ("ducta.mlrun.resilience", "RetryConfig"),
    "SplitError": ("ducta.mlrun.split", "SplitError"),
    "kfold_splits": ("ducta.mlrun.split", "kfold_splits"),
    "split_dataframe": ("ducta.mlrun.split", "split_dataframe"),
    "tag_partitions": ("ducta.mlrun.split", "tag_partitions"),
    "StorageBackend": ("ducta.mlrun.storage", "StorageBackend"),
    "StorageMetadata": ("ducta.mlrun.storage", "StorageMetadata"),
    "validate_artifact_type": ("ducta.mlrun.validators", "validate_artifact_type"),
    "validate_experiment_name": ("ducta.mlrun.validators", "validate_experiment_name"),
    "validate_framework": ("ducta.mlrun.validators", "validate_framework"),
    "validate_metric_value": ("ducta.mlrun.validators", "validate_metric_value"),
    "validate_model_name": ("ducta.mlrun.validators", "validate_model_name"),
    "validate_parameters": ("ducta.mlrun.validators", "validate_parameters"),
    "validate_run_name": ("ducta.mlrun.validators", "validate_run_name"),
    "validate_tags": ("ducta.mlrun.validators", "validate_tags"),
}


def __getattr__(name: str) -> Any:
    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    value = getattr(importlib.import_module(module_name), attribute)
    globals()[name] = value  # resolved once
    return value


def __dir__() -> List[str]:
    return sorted(set(globals()) | set(_EXPORTS))


if TYPE_CHECKING:  # the same names, for type checkers and editors
    from ducta.mlrun.baseline import compare_to_baseline, trivial_baseline_metrics  # noqa: F401
    from ducta.mlrun.concurrency import (  # noqa: F401
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
    from ducta.mlrun.config import MLOpsConfig, MLOpsContext  # noqa: F401
    from ducta.mlrun.environment import EnvironmentSnapshot  # noqa: F401
    from ducta.mlrun.exceptions import (  # noqa: F401
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
    from ducta.mlrun.experiment_tracking import (  # noqa: F401
        Experiment,
        ExperimentTracker,
        Metric,
        Run,
        RunStatus,
    )
    from ducta.mlrun.fingerprint import DataFingerprint  # noqa: F401
    from ducta.mlrun.gc import ModelGarbageCollector  # noqa: F401
    from ducta.mlrun.hyperparams import (  # noqa: F401
        Distribution,
        HyperparamConfig,
        HyperparamConfigError,
        ParamGrid,
        expand_sweep_grid,
        load_hyperparams_config,
    )
    from ducta.mlrun.mlflow import (  # noqa: F401
        MLflowConfig,
        MLflowHelper,
        MLflowNodeContext,
        MLflowPipelineTracker,
        is_mlflow_available,
    )
    from ducta.mlrun.model_registry import (  # noqa: F401
        ModelMetadata,
        ModelRegistry,
        ModelStage,
        ModelVersion,
        PromotionPolicy,
    )
    from ducta.mlrun.persistence import infer_schema, persist_model  # noqa: F401
    from ducta.mlrun.resilience import CircuitBreaker, ResourceLimits, RetryConfig  # noqa: F401
    from ducta.mlrun.split import (  # noqa: F401
        SplitError,
        kfold_splits,
        split_dataframe,
        tag_partitions,
    )
    from ducta.mlrun.storage import StorageBackend, StorageMetadata  # noqa: F401
    from ducta.mlrun.summary import run_summary  # noqa: F401
    from ducta.mlrun.training import TrainResult, train_with_search  # noqa: F401
    from ducta.mlrun.validators import (  # noqa: F401
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
    "tag_partitions",
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
    "TrainResult",
    "train_with_search",
    "run_summary",
]
