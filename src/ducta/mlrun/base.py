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

import threading
import weakref
from abc import ABC
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

try:
    import pandas as pd

    _PANDAS_AVAILABLE = True
except ImportError:
    pd = None  # type: ignore[assignment]
    _PANDAS_AVAILABLE = False
from loguru import logger

from ducta.mlrun.concurrency import file_lock
from ducta.mlrun.events import (
    EventEmitter,
    EventType,
    MetricsCollector,
    get_event_emitter,
    get_metrics_collector,
)

if TYPE_CHECKING:
    from ducta.mlrun.storage import StorageBackend


class ComponentState(str, Enum):
    """Component lifecycle states."""

    CREATED = "created"
    INITIALIZING = "initializing"
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class ComponentStats:
    """Base statistics for MLOps components."""

    component_name: str
    state: ComponentState = ComponentState.CREATED
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    started_at: Optional[str] = None
    operations_count: int = 0
    errors_count: int = 0
    last_operation_at: Optional[str] = None
    custom_stats: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "component_name": self.component_name,
            "state": self.state,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "operations_count": self.operations_count,
            "errors_count": self.errors_count,
            "last_operation_at": self.last_operation_at,
            **self.custom_stats,
        }


class BaseMLOpsComponent(ABC):
    """
    Base class for all MLOps components.
    """

    _instances: Set[weakref.ref] = set()
    _instances_lock = threading.Lock()

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Give every concrete subclass its own independent instance registry."""
        super().__init_subclass__(**kwargs)
        cls._instances = set()
        cls._instances_lock = threading.Lock()

    def __init__(
        self,
        component_name: str,
        storage: "StorageBackend",
        event_emitter: Optional[EventEmitter] = None,
        metrics_collector: Optional[MetricsCollector] = None,
    ):
        """
        Initialize base component.
        """
        self._component_name = component_name
        self.storage = storage

        self._emitter = event_emitter or get_event_emitter()
        self._metrics = metrics_collector or get_metrics_collector()

        self._state = ComponentState.CREATED
        self._lock = threading.RLock()

        self._stats = ComponentStats(component_name=component_name)

        self._register_instance()

        logger.debug(f"BaseMLOpsComponent '{component_name}' created")

    @property
    def component_name(self) -> str:
        """Get component name."""
        return self._component_name

    @property
    def state(self) -> str:
        """Get current component state."""
        with self._lock:
            return self._state

    @property
    def is_ready(self) -> bool:
        """Check if component is ready for operations."""
        return self.state in (ComponentState.READY, ComponentState.RUNNING)

    def initialize(self) -> None:
        """
        Initialize the component.
        """
        with self._lock:
            if self._state != ComponentState.CREATED:
                logger.warning(f"Component '{self._component_name}' already initialized")
                return

            self._state = ComponentState.INITIALIZING

        try:
            self._do_initialize()

            with self._lock:
                self._state = ComponentState.READY
                self._stats.started_at = datetime.now(timezone.utc).isoformat()

            self._emit_event(
                EventType.CONTEXT_INITIALIZED,
                {
                    "component": self._component_name,
                },
            )

            logger.info(f"Component '{self._component_name}' initialized")

        except Exception as e:
            with self._lock:
                self._state = ComponentState.ERROR
            logger.error(f"Failed to initialize '{self._component_name}': {e}")
            raise

    def shutdown(self) -> None:
        """
        Shutdown the component gracefully.
        """
        with self._lock:
            if self._state == ComponentState.STOPPED:
                return

            self._state = ComponentState.STOPPING

        try:
            self._do_shutdown()

            with self._lock:
                self._state = ComponentState.STOPPED

            self._emit_event(
                EventType.CONTEXT_CLEANUP,
                {
                    "component": self._component_name,
                },
            )

            logger.info(f"Component '{self._component_name}' shut down")

        except Exception as e:
            with self._lock:
                self._state = ComponentState.ERROR
            logger.error(f"Error shutting down '{self._component_name}': {e}")

    def _do_initialize(self) -> None:
        """Override for custom initialization logic."""
        pass

    def _do_shutdown(self) -> None:
        """Override for custom shutdown logic."""
        pass

    def _emit_event(
        self,
        event_type: EventType,
        data: Dict[str, Any],
    ) -> None:
        """Emit an event with component context."""
        data["_component"] = self._component_name
        data["_timestamp"] = datetime.now(timezone.utc).isoformat()
        self._emitter.emit(event_type, data, source=self._component_name)

    def _increment_metric(
        self,
        name: str,
        value: int = 1,
        tags: Optional[Dict[str, str]] = None,
    ) -> None:
        """Increment a counter metric."""
        full_tags = {"component": self._component_name}
        if tags:
            full_tags.update(tags)
        self._metrics.increment(name, value, full_tags)

    def _record_time(
        self,
        name: str,
        duration: float,
        tags: Optional[Dict[str, str]] = None,
    ) -> None:
        """Record a timing metric."""
        full_tags = {"component": self._component_name}
        if tags:
            full_tags.update(tags)
        self._metrics.record_time(name, duration, full_tags)

    def get_stats(self) -> Dict[str, Any]:
        """Get component statistics."""
        with self._lock:
            stats = self._stats.to_dict()
            stats["state"] = self._state
            return stats

    def reset_stats(self) -> None:
        """Reset statistics counters."""
        with self._lock:
            self._stats.operations_count = 0
            self._stats.errors_count = 0

    def _register_instance(self) -> None:
        """Register this instance for cleanup tracking."""
        cls = type(self)

        def _cleanup(ref, _cls=cls):
            with _cls._instances_lock:
                _cls._instances.discard(ref)

        with cls._instances_lock:
            ref = weakref.ref(self, _cleanup)
            cls._instances.add(ref)

    @classmethod
    def shutdown_all(cls) -> int:
        """
        Shutdown all registered component instances.
        """
        count = 0
        with cls._instances_lock:
            for ref in cls._instances.copy():
                instance = ref()
                if instance is not None:
                    try:
                        instance.shutdown()
                        count += 1
                    except Exception as e:
                        logger.warning(f"Error shutting down component: {e}")
        return count


class IndexManagerMixin:
    """
    Mixin for managing index files.
    """

    def _load_index(
        self,
        index_path: str,
        columns: List[str],
    ) -> "pd.DataFrame":
        """
        Load index from storage, creating empty if not exists.
        """
        if not _PANDAS_AVAILABLE:
            raise ImportError(
                "pandas is required for MLOps index management. Install it with: pip install pandas"
            )
        try:
            return self.storage.read_dataframe(index_path)
        except FileNotFoundError:
            return pd.DataFrame(columns=columns)

    def _save_index(
        self,
        df: pd.DataFrame,
        index_path: str,
        lock_path: str,
        timeout: float = 30.0,
    ) -> None:
        """
        Save index with file locking.
        """
        with file_lock(
            lock_path, timeout=timeout, base_path=getattr(self.storage, "base_path", None)
        ):
            self.storage.write_dataframe(df, index_path, mode="overwrite")

    def _update_index_entry(
        self,
        index_path: str,
        lock_path: str,
        entry: Dict[str, Any],
        key_column: str,
        columns: List[str],
        timeout: float = 30.0,
    ) -> None:
        """
        Update or insert an entry in an index.
        """
        if not _PANDAS_AVAILABLE:
            raise ImportError(
                "pandas is required for MLOps index management. Install it with: pip install pandas"
            )
        with file_lock(
            lock_path, timeout=timeout, base_path=getattr(self.storage, "base_path", None)
        ):
            df = self._load_index(index_path, columns)

            # Create new row
            new_row = pd.DataFrame([entry])

            # Append and deduplicate
            df = pd.concat([df, new_row], ignore_index=True)
            df = df.drop_duplicates(subset=[key_column], keep="last")

            # Save
            self.storage.write_dataframe(df, index_path, mode="overwrite")


class ValidationMixin:
    """
    Mixin providing validation utilities.
    """

    def _validate_name(
        self,
        name: str,
        entity_type: str = "entity",
        min_length: int = 1,
        max_length: int = 255,
    ) -> str:
        """
        Validate an entity name.
        """
        if not name or not isinstance(name, str):
            raise ValueError(f"{entity_type} name must be non-empty string")

        name = name.strip()

        if len(name) < min_length:
            raise ValueError(f"{entity_type} name too short (min: {min_length})")

        if len(name) > max_length:
            raise ValueError(f"{entity_type} name too long (max: {max_length})")

        return name

    def _validate_positive_int(
        self,
        value: int,
        name: str,
        min_value: int = 1,
    ) -> int:
        """
        Validate a positive integer.
        """
        if not isinstance(value, int) or value < min_value:
            raise ValueError(f"{name} must be integer >= {min_value}, got {value}")
        return value

    def _validate_optional_dict(
        self,
        value: Optional[Dict[str, Any]],
        name: str,
    ) -> Dict[str, Any]:
        """
        Validate optional dictionary, returning empty dict if None.
        """
        if value is None:
            return {}

        if not isinstance(value, dict):
            raise ValueError(f"{name} must be dict or None, got {type(value).__name__}")

        return value


class PathManager:
    """
    Manages structured paths for MLOps storage.
    """

    def __init__(self, base_path: str):
        """
        Initialize path manager.
        """
        self.base_path = base_path.rstrip("/")

    # Experiment paths
    def experiments_dir(self) -> str:
        """Get experiments directory path."""
        return f"{self.base_path}/experiments"

    def experiments_index(self) -> str:
        """Get experiments index path."""
        return f"{self.base_path}/experiments/index.parquet"

    def experiments_index_lock(self) -> str:
        """Get experiments index lock path."""
        return f"{self.base_path}/experiments/.index.lock"

    def experiment(self, experiment_id: str) -> str:
        """Get experiment metadata path."""
        return f"{self.base_path}/experiments/{experiment_id}.json"

    # Run paths
    def runs_dir(self, experiment_id: str) -> str:
        """Get runs directory for experiment."""
        return f"{self.base_path}/runs/{experiment_id}"

    def runs_index(self) -> str:
        """Get runs index path."""
        return f"{self.base_path}/runs/index.parquet"

    def runs_index_lock(self) -> str:
        """Get runs index lock path."""
        return f"{self.base_path}/runs/.index.lock"

    def run(self, experiment_id: str, run_id: str) -> str:
        """Get run metadata path."""
        return f"{self.base_path}/runs/{experiment_id}/{run_id}.json"

    # Metrics paths
    def metrics_dir(self, experiment_id: str) -> str:
        """Get metrics directory for experiment."""
        return f"{self.base_path}/metrics/{experiment_id}"

    def metrics_index(self) -> str:
        """Get metrics index path."""
        return f"{self.base_path}/metrics/index.parquet"

    def run_metrics(self, experiment_id: str, run_id: str) -> str:
        """Get run metrics path."""
        return f"{self.base_path}/metrics/{experiment_id}/{run_id}_metrics.json"

    # Artifact paths
    def artifacts_dir(self, run_id: str) -> str:
        """Get artifacts directory for run."""
        return f"{self.base_path}/artifacts/{run_id}"

    # Model registry paths
    def models_dir(self) -> str:
        """Get models directory path."""
        return f"{self.base_path}/models"

    def models_index(self) -> str:
        """Get models index path."""
        return f"{self.base_path}/models/index.parquet"

    def models_index_lock(self) -> str:
        """Get models index lock path."""
        return f"{self.base_path}/models/.index.lock"

    def model_metadata(self, model_id: str, version: int) -> str:
        """Get model version metadata path."""
        return f"{self.base_path}/metadata/{model_id}/v{version}.json"

    def model_artifact(self, model_id: str, version: int) -> str:
        """Get model artifact path."""
        return f"{self.base_path}/artifacts/{model_id}/v{version}"

    # Lock paths
    def registry_lock(self) -> str:
        """Get registry lock path."""
        return f"{self.base_path}/models.lock"


def now_iso() -> str:
    """Get current UTC time as ISO format string."""
    return datetime.now(timezone.utc).isoformat()


def parse_iso(timestamp: str) -> datetime:
    """Parse ISO format timestamp to datetime."""
    return datetime.fromisoformat(timestamp)


def age_seconds(timestamp: str) -> float:
    """Calculate age in seconds from ISO timestamp to now."""
    created = parse_iso(timestamp)
    now = datetime.now(timezone.utc)

    # Handle timezone-naive timestamps
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)

    return (now - created).total_seconds()
