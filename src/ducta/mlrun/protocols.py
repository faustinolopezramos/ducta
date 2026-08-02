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

from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    Generator,
    List,
    Optional,
    Protocol,
    TypeVar,
    Union,
    runtime_checkable,
)

from ducta.mlrun.experiment_tracking import RunStatus
from ducta.mlrun.model_registry import ModelStage

if TYPE_CHECKING:
    import pandas as pd


T = TypeVar("T")


@runtime_checkable
class StorageMetadataProtocol(Protocol):
    """Protocol for storage metadata."""

    path: str
    size_bytes: int
    content_type: str
    last_modified: str
    checksum: Optional[str]

    def to_dict(self) -> Dict[str, Any]: ...


@runtime_checkable
class StorageBackendProtocol(Protocol):
    """
    Protocol defining the interface for storage backends.
    """

    def write_dataframe(
        self,
        df: "pd.DataFrame",
        path: str,
        mode: str = "overwrite",
    ) -> StorageMetadataProtocol:
        """
        Write DataFrame to storage.
        """
        ...

    def read_dataframe(self, path: str) -> "pd.DataFrame":
        """
        Read DataFrame from storage.
        """
        ...

    def write_json(
        self,
        data: Dict[str, Any],
        path: str,
        mode: str = "overwrite",
    ) -> StorageMetadataProtocol:
        """
        Write JSON object to storage.
        """
        ...

    def read_json(self, path: str) -> Dict[str, Any]:
        """
        Read JSON object from storage.
        """
        ...

    def write_artifact(
        self,
        artifact_path: str,
        destination: str,
        mode: str = "overwrite",
    ) -> StorageMetadataProtocol:
        """
        Write artifact (file or directory) to storage.
        """
        ...

    def read_artifact(self, path: str, local_destination: str) -> None:
        """
        Download artifact from storage to local path.
        """
        ...

    def exists(self, path: str) -> bool:
        """
        Check if path exists in storage.
        """
        ...

    def list_paths(self, prefix: str) -> List[str]:
        """
        List all paths with given prefix.
        """
        ...

    def delete(self, path: str) -> None:
        """
        Delete path (file or directory).
        """
        ...

    def get_stats(self) -> Dict[str, Any]:
        """
        Get storage backend statistics.

        Returns:
            Dictionary with statistics
        """
        return {}


RunStatusProtocol = RunStatus


@runtime_checkable
class RunProtocol(Protocol):
    """Protocol for experiment run objects."""

    run_id: str
    experiment_id: str
    name: str
    status: RunStatusProtocol
    created_at: str
    updated_at: str
    start_time: Optional[str]
    end_time: Optional[str]
    duration_seconds: Optional[float]
    parameters: Dict[str, Any]
    metrics: Dict[str, List[Any]]
    artifacts: List[str]
    tags: Dict[str, str]

    def to_dict(self) -> Dict[str, Any]:
        """Convert run to dictionary."""
        ...


@runtime_checkable
class ExperimentProtocol(Protocol):
    """Protocol for experiment objects."""

    experiment_id: str
    name: str
    description: str
    created_at: str
    updated_at: str
    tags: Dict[str, str]

    def to_dict(self) -> Dict[str, Any]:
        """Convert experiment to dictionary."""
        ...


@runtime_checkable
class ExperimentTrackerProtocol(Protocol):
    """
    Protocol for experiment tracking implementations.
    """

    def create_experiment(
        self,
        name: str,
        description: str = "",
        tags: Optional[Dict[str, str]] = None,
    ) -> ExperimentProtocol:
        """
        Create a new experiment.
        """
        ...

    def start_run(
        self,
        experiment_id: str,
        name: str = "",
        parameters: Optional[Dict[str, Any]] = None,
        tags: Optional[Dict[str, str]] = None,
        parent_run_id: Optional[str] = None,
    ) -> RunProtocol:
        """
        Start a new experiment run.
        """
        ...

    def end_run(
        self,
        run_id: str,
        status: RunStatusProtocol = RunStatusProtocol.COMPLETED,
    ) -> RunProtocol:
        """
        End a run with specified status.
        """
        ...

    def log_metric(
        self,
        run_id: str,
        key: str,
        value: float,
        step: int = 0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Log a metric value.
        """
        ...

    def log_parameter(
        self,
        run_id: str,
        key: str,
        value: Any,
    ) -> None:
        """
        Log a parameter.
        """
        ...

    def log_artifact(
        self,
        run_id: str,
        artifact_path: str,
        destination: str = "",
    ) -> str:
        """
        Log an artifact.
        """
        ...

    def get_run(self, run_id: str) -> RunProtocol:
        """
        Get run by ID.
        """
        ...

    def list_runs(
        self,
        experiment_id: str,
        status_filter: Optional[RunStatusProtocol] = None,
        tag_filter: Optional[Dict[str, str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        List runs in an experiment.
        """
        ...

    def get_stats(self) -> Dict[str, Any]:
        """Get tracker statistics."""
        ...

    def run_context(
        self,
        experiment_id: str,
        name: str = "",
        parameters: Optional[Dict[str, Any]] = None,
        tags: Optional[Dict[str, str]] = None,
    ) -> Generator[RunProtocol, None, None]:
        """
        Context manager for experiment runs.
        Concrete implementations should decorate with @contextmanager.
        """
        ...


ModelStageProtocol = ModelStage


@runtime_checkable
class ModelMetadataProtocol(Protocol):
    """Protocol for model metadata."""

    name: str
    framework: str
    version: int
    created_at: str
    description: str
    hyperparameters: Dict[str, Any]
    metrics: Dict[str, float]
    tags: Dict[str, str]
    stage: ModelStageProtocol

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        ...


@runtime_checkable
class ModelVersionProtocol(Protocol):
    """Protocol for model version objects."""

    model_id: str
    version: int
    metadata: ModelMetadataProtocol
    artifact_uri: str
    artifact_type: str
    created_at: str
    updated_at: str
    experiment_run_id: Optional[str]
    size_bytes: Optional[int]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        ...


@runtime_checkable
class ModelRegistryProtocol(Protocol):
    """
    Protocol for model registry implementations.
    """

    def register_model(
        self,
        name: str,
        artifact_path: str,
        artifact_type: str,
        framework: str,
        description: str = "",
        hyperparameters: Optional[Dict[str, Any]] = None,
        metrics: Optional[Dict[str, float]] = None,
        tags: Optional[Dict[str, str]] = None,
        input_schema: Optional[Dict[str, str]] = None,
        output_schema: Optional[Dict[str, str]] = None,
        dependencies: Optional[List[str]] = None,
        experiment_run_id: Optional[str] = None,
    ) -> ModelVersionProtocol:
        """
        Register a new model or version.
        """
        ...

    def get_model_version(
        self,
        name: str,
        version: Optional[int] = None,
    ) -> ModelVersionProtocol:
        """
        Get a specific model version.
        """
        ...

    def get_model_by_stage(
        self,
        name: str,
        stage: ModelStageProtocol,
    ) -> ModelVersionProtocol:
        """
        Get the latest model version for a given stage.
        """
        ...

    def list_models(self) -> List[Dict[str, Any]]:
        """
        List all registered models.
        """
        ...

    def list_model_versions(self, name: str) -> List[Dict[str, Any]]:
        """
        List all versions of a model.
        """
        ...

    def promote_model(
        self,
        name: str,
        version: int,
        stage: ModelStageProtocol,
    ) -> ModelVersionProtocol:
        """
        Promote a model version to a new stage.
        """
        ...

    def download_artifact(
        self,
        name: str,
        version: Optional[int],
        local_destination: str,
    ) -> None:
        """
        Download model artifact.
        """
        ...

    def delete_model_version(self, name: str, version: int) -> None:
        """
        Delete a specific model version.
        """
        ...


@runtime_checkable
class LockProtocol(Protocol):
    """Protocol for lock implementations."""

    def acquire(self) -> bool:
        """
        Acquire the lock.
        """
        ...

    def release(self) -> None:
        """Release the lock."""
        ...

    @property
    def is_acquired(self) -> bool:
        """Check if lock is currently held."""
        ...

    def __enter__(self) -> "LockProtocol":
        """Context manager entry."""
        ...

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Context manager exit."""
        ...


@runtime_checkable
class EventCallback(Protocol):
    """Protocol for event callbacks."""

    def __call__(self, event_type: str, data: Dict[str, Any]) -> None:
        """
        Handle an event.
        """
        ...


@runtime_checkable
class EventEmitterProtocol(Protocol):
    """Protocol for event emitter implementations."""

    def on(self, event_type: Union[str, Any], callback: EventCallback) -> None:
        """
        Register an event callback.
        """
        ...

    def off(self, event_type: Union[str, Any], callback: EventCallback) -> None:
        """
        Unregister an event callback.
        """
        ...

    def emit(self, event_type: Union[str, Any], data: Dict[str, Any]) -> None:
        """
        Emit an event.
        """
        ...


@runtime_checkable
class SerializableProtocol(Protocol):
    """Protocol for serializable objects."""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        ...

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SerializableProtocol":
        """Create instance from dictionary."""
        ...


@runtime_checkable
class ValidatorProtocol(Protocol[T]):
    """Protocol for validators."""

    def validate(self, value: Any) -> T:
        """
        Validate and transform a value.
        """
        ...


@runtime_checkable
class MLOpsContextProtocol(Protocol):
    """Protocol for MLOps context implementations."""

    model_registry: ModelRegistryProtocol
    experiment_tracker: ExperimentTrackerProtocol
    storage: StorageBackendProtocol

    @classmethod
    def from_config(cls, config: Any) -> "MLOpsContextProtocol":
        """Create context from configuration."""
        ...

    def get_stats(self) -> Dict[str, Any]:
        """Get combined statistics from all components."""
        ...

    def cleanup(self) -> None:
        """Clean up resources."""
        ...
