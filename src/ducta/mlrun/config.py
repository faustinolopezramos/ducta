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

import os
import threading
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Literal, Optional, Tuple

from loguru import logger

from ducta.mlrun.experiment_tracking import ExperimentTracker
from ducta.mlrun.model_registry import ModelRegistry
from ducta.mlrun.resilience import STORAGE_RETRY_CONFIG
from ducta.mlrun.storage import StorageBackend, StorageBackendRegistry

if TYPE_CHECKING:
    from ducta.setting.contexts import Context


DEFAULT_STORAGE_PATH = "./mlops_data"
DEFAULT_REGISTRY_PATH = "model_registry"
DEFAULT_TRACKING_PATH = "experiment_tracking"
DEFAULT_METRIC_BUFFER_SIZE = 100
DEFAULT_MAX_ACTIVE_RUNS = 100
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_DELAY = 1.0
DEFAULT_STALE_RUN_AGE = 3600.0


def _active_env(context: "Context") -> Optional[str]:
    """The context's active environment name, however it's exposed.

    Different Context flavors carry it under ``env`` or ``environment`` —
    shared to avoid re-deriving this fallback at every call site.
    """
    return getattr(context, "env", None) or getattr(context, "environment", None)


@dataclass
class MLOpsConfig:
    """Configuration for MLOps initialization."""

    # Backend configuration
    backend_type: Literal["local", "databricks", "distributed"] = "local"
    storage_path: str = DEFAULT_STORAGE_PATH
    catalog: Optional[str] = None  # For Databricks: Unity Catalog name
    schema: Optional[str] = None  # For Databricks: Schema name
    volume: str = "mlops_artifacts"  # For Databricks: Unity Catalog Volume name

    # Registry configuration
    registry_path: str = DEFAULT_REGISTRY_PATH
    model_retention_days: int = 90
    max_versions_per_model: int = 100

    # Tracking configuration
    tracking_path: str = DEFAULT_TRACKING_PATH
    metric_buffer_size: int = DEFAULT_METRIC_BUFFER_SIZE
    auto_flush_metrics: bool = True
    max_active_runs: int = DEFAULT_MAX_ACTIVE_RUNS
    auto_cleanup_stale: bool = True
    stale_run_age_seconds: float = DEFAULT_STALE_RUN_AGE

    # Resilience configuration
    enable_retry: bool = True
    max_retries: int = DEFAULT_MAX_RETRIES
    retry_delay: float = DEFAULT_RETRY_DELAY
    enable_circuit_breaker: bool = False

    # Additional options
    extra_options: Dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def _env(name: str, default: Optional[str] = None) -> Optional[str]:
        """Read a ``Ducta_MLOPS_*`` env var, also accepting the all-caps ``DUCTA_MLOPS_*``
        form (the conventional Unix casing, unlike this codebase's historical mixed case) —
        a very plausible typo/convention mismatch would otherwise silently fall back to
        defaults with zero warning."""
        value = os.environ.get(name)
        if value is None:
            value = os.environ.get(name.upper())
        return value if value is not None else default

    @classmethod
    def _env_int(cls, name: str, default: int) -> int:
        raw = cls._env(name)
        if raw is None:
            return default
        try:
            return int(raw)
        except ValueError as e:
            raise ValueError(f"Environment variable {name} must be an integer, got {raw!r}") from e

    @classmethod
    def _env_float(cls, name: str, default: float) -> float:
        raw = cls._env(name)
        if raw is None:
            return default
        try:
            return float(raw)
        except ValueError as e:
            raise ValueError(f"Environment variable {name} must be a number, got {raw!r}") from e

    _TRUE_VALUES = frozenset({"true", "yes", "on", "1"})
    _FALSE_VALUES = frozenset({"false", "no", "off", "0", ""})

    @classmethod
    def _env_bool(cls, name: str, default: bool) -> bool:
        """Parse a boolean env var, accepting the same spellings as
        ``ducta.core.settings.coerce_bool`` (``true/yes/on/1`` and
        ``false/no/off/0``) instead of only the literal string ``"true"`` —
        the old behavior silently treated ``Ducta_MLOPS_ENABLE_RETRY=1`` as
        False with no warning.
        """
        raw = cls._env(name)
        if raw is None:
            return default
        normalized = raw.strip().lower()
        if normalized in cls._TRUE_VALUES:
            return True
        if normalized in cls._FALSE_VALUES:
            return False
        logger.warning(
            "Environment variable {} has unrecognized boolean value {!r}; "
            "expected true/false. Falling back to default={}.",
            name,
            raw,
            default,
        )
        return default

    @classmethod
    def from_env(cls) -> "MLOpsConfig":
        """
        Create configuration from environment variables.
        """

        return cls(
            backend_type=cls._env("Ducta_MLOPS_BACKEND", "local"),  # type: ignore
            storage_path=cls._env("Ducta_MLOPS_PATH", DEFAULT_STORAGE_PATH),
            catalog=os.getenv("DATABRICKS_CATALOG"),
            schema=os.getenv("DATABRICKS_SCHEMA"),
            volume=os.getenv("DATABRICKS_VOLUME", "mlops_artifacts"),
            registry_path=cls._env("Ducta_MLOPS_REGISTRY_PATH", DEFAULT_REGISTRY_PATH),
            tracking_path=cls._env("Ducta_MLOPS_TRACKING_PATH", DEFAULT_TRACKING_PATH),
            model_retention_days=cls._env_int("Ducta_MLOPS_MODEL_RETENTION_DAYS", 90),
            max_versions_per_model=cls._env_int("Ducta_MLOPS_MAX_VERSIONS", 100),
            metric_buffer_size=cls._env_int(
                "Ducta_MLOPS_METRIC_BUFFER_SIZE", DEFAULT_METRIC_BUFFER_SIZE
            ),
            auto_flush_metrics=cls._env_bool("Ducta_MLOPS_AUTO_FLUSH", True),
            max_retries=cls._env_int("Ducta_MLOPS_MAX_RETRIES", DEFAULT_MAX_RETRIES),
            retry_delay=cls._env_float("Ducta_MLOPS_RETRY_DELAY", DEFAULT_RETRY_DELAY),
            max_active_runs=cls._env_int("Ducta_MLOPS_MAX_ACTIVE_RUNS", DEFAULT_MAX_ACTIVE_RUNS),
            auto_cleanup_stale=cls._env_bool("Ducta_MLOPS_AUTO_CLEANUP", True),
            stale_run_age_seconds=cls._env_float(
                "Ducta_MLOPS_STALE_RUN_AGE", DEFAULT_STALE_RUN_AGE
            ),
            enable_retry=cls._env_bool("Ducta_MLOPS_ENABLE_RETRY", True),
            enable_circuit_breaker=cls._env_bool("Ducta_MLOPS_CIRCUIT_BREAKER", False),
        )

    def validate(self) -> None:
        """Validate configuration."""

        if self.backend_type not in ("local", "databricks", "distributed"):
            raise ValueError(f"Invalid backend_type: {self.backend_type}")

        if self.backend_type in ("databricks", "distributed"):
            if not self.catalog and not os.getenv("DATABRICKS_CATALOG"):
                logger.warning(
                    "No catalog specified for Databricks backend. "
                    "Set 'catalog' parameter or DATABRICKS_CATALOG environment variable. "
                    "Defaulting to 'main'."
                )

        if self.max_active_runs < 1:
            raise ValueError("max_active_runs must be at least 1")

        if self.max_retries < 0:
            raise ValueError("max_retries cannot be negative")

        if self.model_retention_days <= 0:
            raise ValueError("model_retention_days must be positive")

        if self.max_versions_per_model <= 0:
            raise ValueError("max_versions_per_model must be positive")

        if self.metric_buffer_size <= 0:
            raise ValueError("metric_buffer_size must be positive")

        if self.retry_delay < 0:
            raise ValueError("retry_delay cannot be negative")

        if self.stale_run_age_seconds < 0:
            raise ValueError("stale_run_age_seconds cannot be negative")


class StorageBackendFactory:
    """
    Factory for creating storage backends based on execution mode.
    """

    @staticmethod
    def _get_execution_mode(context: "Context") -> str:
        """Get execution mode from context with fallback."""
        mode = getattr(context, "execution_mode", "local") or "local"
        return str(mode).lower()

    @staticmethod
    def _resolve_mlops_path(
        context: "Context",
        base_path: Optional[str] = None,
        pipeline_name: Optional[str] = None,
    ) -> Optional[str]:
        """Resolve MLOps path using 4-tier priority fallback."""
        if base_path:
            return base_path

        gs = getattr(context, "global_config", {}) or {}

        if gs.get("mlops_path"):
            return gs["mlops_path"]

        output_path = getattr(context, "output_path", None)
        if output_path and pipeline_name:
            try:
                schema, sub_folder = pipeline_name.split(".", 1)
                active_env = _active_env(context)
                root = Path(output_path)
                if active_env:
                    return str(root / active_env / schema / sub_folder)
                return str(root / schema / sub_folder)
            except Exception as e:
                logger.debug(
                    "Tier-3 pipeline-scoped MLOps path resolution failed for "
                    "pipeline_name={!r}: {}",
                    pipeline_name,
                    e,
                )

        if output_path:
            active_env = _active_env(context)
            return str(Path(output_path) / (active_env or "default"))

        logger.critical(
            "Cannot resolve MLOps path: missing output_path and/or environment. "
            "MLOps will NOT be initialized to prevent creating directories in wrong location."
        )
        return None

    @staticmethod
    def create_from_context(
        context: "Context",
        base_path: Optional[str] = None,
        catalog: Optional[str] = None,
        schema: Optional[str] = None,
        pipeline_name: Optional[str] = None,
        **kwargs: Any,
    ) -> Optional[StorageBackend]:
        """
        Create appropriate storage backend from execution context.
        """

        mode = StorageBackendFactory._get_execution_mode(context)

        try:
            backend_key = "databricks" if mode == "distributed" else mode
            backend_cls = StorageBackendRegistry.get(backend_key)

            if mode == "local":
                path = StorageBackendFactory._resolve_mlops_path(context, base_path, pipeline_name)
                if path is None:
                    logger.error("Could not resolve safe MLOps directory path.")
                    return None

                local_kwargs: Dict[str, Any] = {}
                if "retry_config" in kwargs:
                    local_kwargs["retry_config"] = kwargs["retry_config"]
                if "enable_circuit_breaker" in kwargs:
                    local_kwargs["enable_circuit_breaker"] = kwargs["enable_circuit_breaker"]
                return backend_cls(base_path=path, **local_kwargs)

            if mode in ("databricks", "distributed"):
                catalog_to_use = catalog or os.getenv("DATABRICKS_CATALOG", "main")
                schema_to_use = schema or os.getenv("DATABRICKS_SCHEMA", "ml_tracking")
                volume_to_use = kwargs.get("volume_name") or os.getenv(
                    "DATABRICKS_VOLUME", "mlops_artifacts"
                )

                logger.info(
                    f"Creating {backend_cls.__name__} (UC: {catalog_to_use}.{schema_to_use})"
                )

                databricks_kwargs: Dict[str, Any] = {}
                if "retry_config" in kwargs:
                    databricks_kwargs["retry_config"] = kwargs["retry_config"]
                if "enable_circuit_breaker" in kwargs:
                    databricks_kwargs["enable_circuit_breaker"] = kwargs["enable_circuit_breaker"]

                return backend_cls(
                    catalog=catalog_to_use,
                    schema=schema_to_use,
                    volume_name=volume_to_use,
                    workspace_url=kwargs.get("workspace_url"),
                    token=kwargs.get("token"),
                    **databricks_kwargs,
                )

            raise ValueError(
                f"Unsupported execution_mode: '{mode}'. "
                f"Supported values: 'local', 'databricks', 'distributed'."
            )

        except Exception as e:
            logger.error(f"Failed to create storage backend: {e}")
            return None


class TrackingURIResolver:
    """
    Resolver for tracking URI paths that may be relative to output_path/environment.
    """

    @staticmethod
    def resolve_tracking_uri(
        tracking_uri: Optional[str],
        context: Optional["Context"] = None,
    ) -> Optional[str]:
        """
        Resolve tracking_uri considering environment structure.
        """
        if not tracking_uri:
            return tracking_uri

        if tracking_uri.startswith("/") or tracking_uri.startswith("\\") or "://" in tracking_uri:
            return tracking_uri

        if context is None:
            return tracking_uri

        output_path = getattr(context, "output_path", None)
        if not output_path:
            return tracking_uri

        active_env = _active_env(context)
        base = Path(output_path) / active_env if active_env else Path(output_path)
        resolved = str(base / tracking_uri)

        if active_env:
            logger.debug(f"Resolved tracking_uri for env '{active_env}': {resolved}")
        else:
            logger.debug(f"Resolved tracking_uri (no env): {resolved}")

        return resolved


def _resolve_component_storage(
    context: "Context",
    component_name: str,
    capability_label: str,
    path_label: str,
    path_value: str,
    pipeline_name: Optional[str],
    storage: Optional[StorageBackend],
    storage_kwargs: Dict[str, Any],
) -> Optional[StorageBackend]:
    """Resolve (or reuse) the storage backend for an MLOps component factory.

    Shared by ``ExperimentTrackerFactory.from_context`` and
    ``ModelRegistryFactory.from_context``, which previously each carried a
    near-identical copy of this resolution + fail-safe warning + "Creating
    X..." info log; only the component name, the "MLOps ... will not be
    available" phrasing, and which path kwarg gets logged differ.
    """
    if storage is None:
        storage = StorageBackendFactory.create_from_context(
            context, pipeline_name=pipeline_name, **storage_kwargs
        )

    # Fail-safe: If storage creation failed, return None
    if storage is None:
        logger.warning(
            f"{component_name} creation failed: Could not initialize storage backend. "
            f"MLOps {capability_label} will not be available. This usually happens if "
            "'output_path' is missing from global_config or cannot be resolved."
        )
        return None

    logger.info(
        f"Creating {component_name} with {storage.__class__.__name__} "
        f"at base '{storage.base_path}' "
        f"(env: {_active_env(context) or 'none'}, {path_label}: {path_value})"
    )
    return storage


class ExperimentTrackerFactory:
    """
    Factory for creating ExperimentTracker with automatic storage backend selection.
    """

    @staticmethod
    def from_context(
        context: "Context",
        tracking_path: str = "experiment_tracking",
        metric_buffer_size: int = 100,
        auto_flush_metrics: bool = True,
        max_active_runs: int = DEFAULT_MAX_ACTIVE_RUNS,
        auto_cleanup_stale: bool = True,
        stale_run_age_seconds: float = DEFAULT_STALE_RUN_AGE,
        pipeline_name: Optional[str] = None,
        storage: Optional[StorageBackend] = None,
        **storage_kwargs: Any,
    ) -> Optional[ExperimentTracker]:
        """
        Create ExperimentTracker with appropriate storage backend from context.
        """
        storage = _resolve_component_storage(
            context,
            "ExperimentTracker",
            "tracking",
            "tracking_path",
            tracking_path,
            pipeline_name,
            storage,
            storage_kwargs,
        )
        if storage is None:
            return None

        return ExperimentTracker(
            storage=storage,
            tracking_path=tracking_path,
            metric_buffer_size=metric_buffer_size,
            auto_flush_metrics=auto_flush_metrics,
            max_active_runs=max_active_runs,
            auto_cleanup_stale=auto_cleanup_stale,
            stale_run_age_seconds=stale_run_age_seconds,
        )


class ModelRegistryFactory:
    """
    Factory for creating ModelRegistry with automatic storage backend selection.
    """

    @staticmethod
    def from_context(
        context: "Context",
        registry_path: str = "model_registry",
        pipeline_name: Optional[str] = None,
        storage: Optional[StorageBackend] = None,
        **storage_kwargs: Any,
    ) -> Optional[ModelRegistry]:
        """
        Create ModelRegistry with appropriate storage backend from context.

        Pass an existing ``storage`` (as ``MLOpsContext.from_context`` does, so
        the model registry and the experiment tracker share one backend
        instance) to skip resolving/creating a new one.
        """
        storage = _resolve_component_storage(
            context,
            "ModelRegistry",
            "model registry",
            "registry_path",
            registry_path,
            pipeline_name,
            storage,
            storage_kwargs,
        )
        if storage is None:
            return None

        return ModelRegistry(
            storage=storage,
            registry_path=registry_path,
        )


# Convenience aliases

create_storage_backend = StorageBackendFactory.create_from_context

create_experiment_tracker = ExperimentTrackerFactory.from_context

create_model_registry = ModelRegistryFactory.from_context


class MLOpsContext:
    """
    Centralized MLOps context for managing Model Registry and Experiment Tracking.
    """

    _lock = threading.Lock()

    def __init__(
        self,
        model_registry: Optional[ModelRegistry] = None,
        experiment_tracker: Optional[ExperimentTracker] = None,
        config: Optional[MLOpsConfig] = None,
        # Legacy kwargs support
        backend_type: Optional[str] = None,
        storage_path: Optional[str] = None,
        **kwargs,
    ):
        """
        Initialize MLOps context.
        """
        # Check if using legacy API
        if backend_type is not None or storage_path is not None:
            # Legacy initialization - create from config
            logger.debug("Using legacy MLOpsContext initialization")

            if model_registry is not None or experiment_tracker is not None or config is not None:
                logger.warning(
                    "MLOpsContext() received both legacy kwargs (backend_type/storage_path) "
                    "and modern kwargs (model_registry/experiment_tracker/config); the legacy "
                    "path takes over and silently discards the modern kwargs you passed "
                    "(model_registry={}, experiment_tracker={}, config={}). Pass only one "
                    "style.",
                    model_registry is not None,
                    experiment_tracker is not None,
                    config is not None,
                )

            legacy_config = MLOpsConfig(
                backend_type=backend_type or "local",  # type: ignore
                storage_path=storage_path or DEFAULT_STORAGE_PATH,
                **{k: v for k, v in kwargs.items() if k in MLOpsConfig.__dataclass_fields__},
            )

            _, model_registry, experiment_tracker = MLOpsContext._build_from_config(legacy_config)
            config = legacy_config

        self.model_registry = model_registry
        self.experiment_tracker = experiment_tracker
        self.config = config

        # Expose storage for backward compatibility
        if self.model_registry:
            self.storage = self.model_registry.storage
        else:
            self.storage = None

        logger.info("MLOpsContext initialized")

    @classmethod
    def from_config(cls, config: MLOpsConfig) -> "MLOpsContext":
        """
        Create MLOpsContext from configuration object.
        """

        config.validate()

        _, model_registry, experiment_tracker = cls._build_from_config(config)

        logger.info(
            f"MLOpsContext created from config "
            f"(backend: {_resolve_backend_type(config.backend_type)}, "
            f"max_runs: {config.max_active_runs})"
        )

        return cls(
            model_registry=model_registry,
            experiment_tracker=experiment_tracker,
            config=config,
        )

    @staticmethod
    def _build_from_config(
        config: MLOpsConfig,
    ) -> Tuple[StorageBackend, ModelRegistry, ExperimentTracker]:
        """Build the (storage, model_registry, experiment_tracker) triple a
        ``MLOpsConfig`` describes.

        Shared by ``from_config`` and ``__init__``'s legacy-kwargs branch,
        which previously built this triple independently and had drifted:
        the legacy path never passed ``auto_cleanup_stale``/
        ``stale_run_age_seconds`` to ``ExperimentTracker`` (silently ignoring
        those ``MLOpsConfig`` settings) and constructed the Databricks backend
        directly instead of through ``StorageBackendRegistry`` (silently
        ignoring ``config.volume``). Does not call ``config.validate()`` —
        callers decide whether/when to validate.
        """
        resolved_backend = _resolve_backend_type(config.backend_type)
        backend_cls = StorageBackendRegistry.get(resolved_backend)

        if resolved_backend == "local":
            storage = backend_cls(base_path=config.storage_path)
        else:
            # For Databricks, rely on standard environment variables and user configuration
            storage = backend_cls(
                catalog=config.catalog or os.getenv("DATABRICKS_CATALOG", "main"),
                schema=config.schema or os.getenv("DATABRICKS_SCHEMA", "ml_tracking"),
                volume_name=config.volume or os.getenv("DATABRICKS_VOLUME", "mlops_artifacts"),
            )

        model_registry = ModelRegistry(
            storage=storage,
            registry_path=config.registry_path,
        )

        experiment_tracker = ExperimentTracker(
            storage=storage,
            tracking_path=config.tracking_path,
            metric_buffer_size=config.metric_buffer_size,
            auto_flush_metrics=config.auto_flush_metrics,
            max_active_runs=config.max_active_runs,
            auto_cleanup_stale=config.auto_cleanup_stale,
            stale_run_age_seconds=config.stale_run_age_seconds,
        )

        return storage, model_registry, experiment_tracker

    @classmethod
    def from_context(
        cls,
        context: "Context",
        registry_path: Optional[str] = None,
        tracking_path: Optional[str] = None,
        metric_buffer_size: Optional[int] = None,
        auto_flush_metrics: Optional[bool] = None,
        max_active_runs: Optional[int] = None,
        pipeline_name: Optional[str] = None,
        config: Optional[MLOpsConfig] = None,
    ) -> "MLOpsContext":
        """
        Create MLOpsContext from Ducta execution context.
        """
        if config is None:
            config = MLOpsConfig.from_env()
        self_config = config

        resolved_registry_path = (
            registry_path if registry_path is not None else config.registry_path
        )
        resolved_tracking_path = (
            tracking_path if tracking_path is not None else config.tracking_path
        )
        resolved_metric_buffer_size = (
            metric_buffer_size if metric_buffer_size is not None else config.metric_buffer_size
        )
        resolved_auto_flush_metrics = (
            auto_flush_metrics if auto_flush_metrics is not None else config.auto_flush_metrics
        )
        resolved_max_active_runs = (
            max_active_runs if max_active_runs is not None else config.max_active_runs
        )

        active_env = _active_env(context)

        mode = getattr(context, "execution_mode", "local")

        logger.debug(
            f"MLOpsContext.from_context: active_env='{active_env}', mode='{mode}', pipeline='{pipeline_name}'"
        )

        retry_config = (
            replace(STORAGE_RETRY_CONFIG, max_attempts=1)
            if not config.enable_retry
            else replace(
                STORAGE_RETRY_CONFIG,
                max_attempts=max(1, config.max_retries),
                initial_delay=config.retry_delay,
            )
        )

        storage = StorageBackendFactory.create_from_context(
            context,
            pipeline_name=pipeline_name,
            retry_config=retry_config,
            enable_circuit_breaker=config.enable_circuit_breaker,
        )

        model_registry = ModelRegistryFactory.from_context(
            context,
            registry_path=resolved_registry_path,
            pipeline_name=pipeline_name,
            storage=storage,
        )

        experiment_tracker = ExperimentTrackerFactory.from_context(
            context,
            tracking_path=resolved_tracking_path,
            metric_buffer_size=resolved_metric_buffer_size,
            auto_flush_metrics=resolved_auto_flush_metrics,
            max_active_runs=resolved_max_active_runs,
            auto_cleanup_stale=config.auto_cleanup_stale,
            stale_run_age_seconds=config.stale_run_age_seconds,
            pipeline_name=pipeline_name,
            storage=storage,
        )

        logger.info(
            f"MLOpsContext created from context "
            f"(mode: {mode}"
            f"{f', env: {active_env}' if active_env else ''}"
            f"{f', pipeline: {pipeline_name}' if pipeline_name else ''}"
            f", max_runs: {resolved_max_active_runs})"
        )

        return cls(
            model_registry=model_registry,
            experiment_tracker=experiment_tracker,
            config=self_config,
        )

    @classmethod
    def from_env(cls) -> "MLOpsContext":
        """
        Create MLOpsContext from environment variables.
        """

        config = MLOpsConfig.from_env()

        return cls.from_config(config)

    def get_stats(self) -> Dict[str, Any]:
        """Get combined statistics from all components."""
        return {
            "model_registry": self.model_registry.get_stats() if self.model_registry else {},
            "experiment_tracker": (
                self.experiment_tracker.get_stats() if self.experiment_tracker else {}
            ),
            "storage": self.storage.get_stats() if self.storage else {},
            "config": {
                "backend_type": self.config.backend_type if self.config else "unknown",
                "storage_path": self.config.storage_path if self.config else "unknown",
            },
        }

    def cleanup(self) -> None:
        """Clean up resources and close any open connections."""
        if self.experiment_tracker is None:
            return
        try:
            cleaned = self.experiment_tracker.cleanup_stale_runs()
            if cleaned > 0:
                logger.info(f"Cleaned up {cleaned} stale runs during shutdown")
        except Exception as e:
            logger.warning(f"Error during cleanup: {e}")


def _resolve_backend_type(
    backend_type: Optional[Literal["local", "databricks", "distributed"]],
) -> Literal["local", "databricks"]:
    """
    Resolve the backend type, handling aliases.
    """

    if backend_type is None:
        backend_type = "local"

    if backend_type == "distributed":
        return "databricks"

    if backend_type not in ("local", "databricks"):
        raise ValueError(
            f"Unknown backend_type: {backend_type}. Supported: 'local', 'databricks', 'distributed'"
        )

    return backend_type
