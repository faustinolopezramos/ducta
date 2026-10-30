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

import importlib
import importlib.util
import os
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Union

from loguru import logger

from ducta.mlrun.config import TrackingURIResolver


class _LazyModule:
    """An optional module, imported the first time one of its attributes is used.

    ``import mlflow`` costs about 0.3 s and writes a line of its own to the log, and this
    module is imported by every ``ducta`` command, ``--help`` included. Nothing here needs
    MLflow until a run is tracked, so the import waits for that.
    """

    def __init__(self, name: str) -> None:
        self.__dict__["_name"] = name
        self.__dict__["_module"] = None

    def _load(self) -> Any:
        if self.__dict__["_module"] is None:
            self.__dict__["_module"] = importlib.import_module(self.__dict__["_name"])
        return self.__dict__["_module"]

    def __getattr__(self, attribute: str) -> Any:
        return getattr(self._load(), attribute)


class _LazyClass:
    """A class from an optional module, resolved when it is first called."""

    def __init__(self, module: str, attribute: str) -> None:
        self._module, self._attribute = module, attribute

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return getattr(importlib.import_module(self._module), self._attribute)(*args, **kwargs)


MLFLOW_AVAILABLE = importlib.util.find_spec("mlflow") is not None
if MLFLOW_AVAILABLE:
    mlflow = _LazyModule("mlflow")  # type: ignore[assignment]
    MlflowClient = _LazyClass("mlflow.tracking", "MlflowClient")  # type: ignore[assignment]
else:
    logger.debug("MLflow not installed. Install with: pip install mlflow")
    mlflow = None  # type: ignore
    MlflowClient = None  # type: ignore


def _mlflow_major() -> int:
    """Major version of the installed MLflow (0 when it cannot be read)."""
    try:
        return int(str(mlflow.__version__).split(".")[0])
    except Exception:  # noqa: BLE001 — absent or unusual version string
        return 0


def _allow_file_store(uri: Optional[str]) -> None:
    """Let MLflow 3 use a local-folder tracking store when the project asks for one.

    MLflow 3 keeps the filesystem store (``./mlruns``, ``file://...``) in maintenance
    mode and refuses it unless ``MLFLOW_ALLOW_FILE_STORE`` is set. A Ducta project can
    configure ``tracking_uri: mlruns`` (resolved under the environment's output path),
    and refusing it would make every run already recorded there unreadable — so it is
    allowed, with a warning that points at the database backend MLflow recommends.
    An explicit ``MLFLOW_ALLOW_FILE_STORE`` in the environment is left as it is.
    """
    if not uri or _mlflow_major() < 3:
        return
    scheme = uri.split("://", 1)[0].lower() if "://" in uri else ""
    if scheme not in ("", "file") or "MLFLOW_ALLOW_FILE_STORE" in os.environ:
        return
    os.environ["MLFLOW_ALLOW_FILE_STORE"] = "true"
    logger.warning(
        "MLflow tracking URI '{}' is a local folder (file store), which MLflow 3 keeps "
        "only in maintenance mode. Ducta allows it so existing runs stay readable; prefer "
        "'sqlite:///<folder>/mlflow.db' (convert existing runs with `mlflow migrate-filestore`).",
        uri,
    )


def _model_location(artifact_path: str) -> Dict[str, str]:
    """Where to log a model: ``name=`` in MLflow 3 (``artifact_path`` is deprecated there)."""
    return {"name": artifact_path} if _mlflow_major() >= 3 else {"artifact_path": artifact_path}


class MLflowTrackingError(RuntimeError):
    """MLflow is required for this run and failed to record something."""


def is_mlflow_available() -> bool:
    """Check if MLflow is installed and available."""
    return MLFLOW_AVAILABLE


class MLflowConfig:
    """
    Centralized MLflow configuration for Ducta pipelines.
    """

    def __init__(
        self,
        tracking_uri: Optional[str] = None,
        experiment_name: str = "Ducta_pipeline",
        artifact_location: Optional[str] = None,
        enable_autolog: bool = True,
        nested_runs: bool = True,
        registry_uri: Optional[str] = None,
        default_tags: Optional[Dict[str, str]] = None,
    ):
        """
        Initialize MLflow configuration.
        """
        self.tracking_uri = tracking_uri
        self.experiment_name = experiment_name
        self.artifact_location = artifact_location
        self.enable_autolog = enable_autolog
        self.nested_runs = nested_runs
        self.registry_uri = registry_uri or tracking_uri
        self.default_tags = default_tags or {}
        self.is_databricks = self._detect_databricks()

        if self.is_databricks:
            logger.info("Databricks environment detected")

    def _detect_databricks(self) -> bool:
        """Detect if running on Databricks."""
        return (
            os.getenv("DATABRICKS_RUNTIME_VERSION") is not None
            or os.getenv("SPARK_HOME", "").find("databricks") >= 0
        )

    @classmethod
    def from_env(cls, prefix: str = "MLFLOW_") -> "MLflowConfig":
        """Create configuration from environment variables."""
        return cls(
            tracking_uri=os.getenv(f"{prefix}TRACKING_URI"),
            experiment_name=os.getenv(f"{prefix}EXPERIMENT_NAME", "Ducta_pipeline"),
            artifact_location=os.getenv(f"{prefix}ARTIFACT_LOCATION"),
            enable_autolog=os.getenv(f"{prefix}ENABLE_AUTOLOG", "true").lower() == "true",
            nested_runs=os.getenv(f"{prefix}NESTED_RUNS", "true").lower() == "true",
            registry_uri=os.getenv(f"{prefix}REGISTRY_URI"),
        )

    @classmethod
    def from_yaml(cls, config_path: str) -> "MLflowConfig":
        """Load configuration from YAML file."""
        import yaml

        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        return cls.from_dict(data.get("mlflow", {}))

    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> "MLflowConfig":
        """Create configuration from dictionary."""
        return cls(
            tracking_uri=config_dict.get("tracking_uri"),
            experiment_name=config_dict.get("experiment_name", "Ducta_pipeline"),
            artifact_location=config_dict.get("artifact_location"),
            enable_autolog=config_dict.get("enable_autolog", True),
            nested_runs=config_dict.get("nested_runs", True),
            registry_uri=config_dict.get("registry_uri"),
            default_tags=config_dict.get("tags", {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary."""
        return {
            "tracking_uri": self.tracking_uri,
            "experiment_name": self.experiment_name,
            "artifact_location": self.artifact_location,
            "enable_autolog": self.enable_autolog,
            "nested_runs": self.nested_runs,
            "registry_uri": self.registry_uri,
            "tags": self.default_tags,
            "is_databricks": self.is_databricks,
        }

    def apply(self) -> None:
        """Apply configuration to MLflow environment."""
        if not MLFLOW_AVAILABLE:
            logger.warning("MLflow not installed, configuration not applied")
            return

        if self.tracking_uri:
            _allow_file_store(self.tracking_uri)
            mlflow.set_tracking_uri(self.tracking_uri)
            logger.info(f"Set MLflow tracking URI: {self.tracking_uri}")

        if self.registry_uri:
            _allow_file_store(self.registry_uri)
            mlflow.set_registry_uri(self.registry_uri)
            logger.info(f"Set MLflow registry URI: {self.registry_uri}")

        logger.info("MLflow configuration applied successfully")


class MLflowPipelineTracker:
    """
    Pipeline tracker using MLflow as backend.
    """

    def __init__(
        self,
        experiment_name: str,
        tracking_uri: Optional[str] = None,
        artifact_location: Optional[str] = None,
        enable_autolog: bool = True,
        nested_runs: bool = True,
        tags: Optional[Dict[str, str]] = None,
        required: bool = False,
    ):
        """
        Initialize MLflow Pipeline Tracker.
        """
        if not MLFLOW_AVAILABLE:
            raise ImportError("MLflow is required. Install with: pip install mlflow")

        self.experiment_name = experiment_name
        self.tracking_uri = tracking_uri
        self.artifact_location = artifact_location
        self.enable_autolog = enable_autolog
        self.nested_runs = nested_runs
        self.tags = tags or {}
        # A run whose model, metrics or artifacts failed to reach MLflow is not the run
        # it claims to be. `required` fails the node instead of logging and moving on.
        self.required = required

        self._client: Optional[Any] = None  # an MlflowClient, imported lazily
        self._experiment_id: Optional[str] = None
        self._active_pipeline_run: Optional[str] = None
        self._active_node_runs: Dict[str, str] = {}
        self._node_start_times: Dict[str, float] = {}
        # Lock to protect shared mutable state accessed from multiple threads
        self._lock = threading.RLock()

        self._initialize_mlflow()

    @property
    def _tracking_client(self) -> Any:
        """The MlflowClient tracking runs (created when tracking starts)."""
        if self._client is None:
            raise RuntimeError("MLflow tracking has not started")
        return self._client

    def _initialize_mlflow(self) -> None:
        """Initialize MLflow client and experiment."""
        try:
            if self.tracking_uri:
                _allow_file_store(self.tracking_uri)
                mlflow.set_tracking_uri(self.tracking_uri)
                logger.info(f"MLflow tracking URI set to: {self.tracking_uri}")

            self._client = MlflowClient()

            try:
                experiment = self._client.get_experiment_by_name(self.experiment_name)
                if experiment:
                    self._experiment_id = experiment.experiment_id
                    logger.info(f"Using existing experiment: {self.experiment_name}")
                else:
                    self._experiment_id = self._client.create_experiment(
                        self.experiment_name,
                        artifact_location=self.artifact_location,
                        tags=self.tags,
                    )
                    logger.info(f"Created new experiment: {self.experiment_name}")
            except Exception:
                mlflow.set_experiment(self.experiment_name)
                experiment = mlflow.get_experiment_by_name(self.experiment_name)
                if experiment:
                    self._experiment_id = experiment.experiment_id

            if self.enable_autolog:
                self._enable_autologging()

        except Exception as e:
            logger.error(f"Failed to initialize MLflow: {e}")
            raise

    def _enable_autologging(self) -> None:
        """Enable autologging for popular ML frameworks."""
        frameworks = ["sklearn", "xgboost", "pytorch", "tensorflow"]
        for framework in frameworks:
            try:
                getattr(mlflow, framework).autolog(silent=True)
                logger.debug(f"Enabled MLflow autologging for {framework}")
            except Exception:
                pass

    @contextmanager
    def start_pipeline_run(
        self,
        pipeline_name: str,
        run_name: Optional[str] = None,
        parameters: Optional[Dict[str, Any]] = None,
        tags: Optional[Dict[str, str]] = None,
        description: Optional[str] = None,
    ):
        """
        Context manager to start a pipeline run in MLflow.
        """
        if not run_name:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            run_name = f"{pipeline_name}_{timestamp}"

        run_tags = {
            "pipeline_name": pipeline_name,
            "Ducta_pipeline": "true",
            "mlflow.note.content": description or f"Ducta pipeline: {pipeline_name}",
        }
        if tags:
            run_tags.update(tags)

        # Entering the MLflow run is a separate failure mode from the pipeline
        # body raising: a tracking-server outage here must degrade to running
        # without MLflow tracking (the bridge is documented as optional/best-
        # effort), not abort the whole pipeline the way a genuine pipeline
        # failure correctly does further down.
        try:
            run_ctx = mlflow.start_run(
                experiment_id=self._experiment_id,
                run_name=run_name,
                tags=run_tags,
                nested=False,
            )
        except Exception as e:
            logger.warning(
                f"MLflow bridge could not start pipeline run '{run_name}' "
                f"(tracking server unreachable?): {e}. Continuing without "
                f"MLflow tracking for this run."
            )
            with self._lock:
                self._active_pipeline_run = None
            yield None
            return

        try:
            with run_ctx as run:
                with self._lock:
                    self._active_pipeline_run = run.info.run_id
                logger.info(f"Started MLflow pipeline run: {run_name}")

                if parameters:
                    mlflow.log_params(parameters)

                mlflow.log_param("pipeline_start_time", datetime.now(timezone.utc).isoformat())
                yield self._active_pipeline_run
                mlflow.log_param("pipeline_end_time", datetime.now(timezone.utc).isoformat())

                logger.info(f"Completed MLflow pipeline run: {run_name}")

        except Exception as e:
            logger.error(f"Pipeline run failed: {e}")
            with self._lock:
                pipeline_run_id = self._active_pipeline_run
            if pipeline_run_id:
                try:
                    self._tracking_client.set_terminated(pipeline_run_id, status="FAILED")
                except Exception:
                    pass
            raise
        finally:
            with self._lock:
                self._active_pipeline_run = None
                self._active_node_runs.clear()
                self._node_start_times.clear()

    @contextmanager
    def start_node_step(
        self,
        node_name: str,
        parent_run_id: Optional[str] = None,
        parameters: Optional[Dict[str, Any]] = None,
        tags: Optional[Dict[str, str]] = None,
    ):
        """
        Context manager to execute a node as an MLflow step (nested run).
        """
        parent_run_id = parent_run_id or self._active_pipeline_run

        if not parent_run_id:
            raise RuntimeError(
                "No active pipeline run. Call start_pipeline_run() before start_node_step()."
            )

        step_tags = {
            "node_name": node_name,
            "Ducta_node": "true",
            "mlflow.parentRunId": parent_run_id,
        }
        if tags:
            step_tags.update(tags)

        start_time = time.perf_counter()
        with self._lock:
            self._node_start_times[node_name] = start_time

        try:
            with mlflow.start_run(
                experiment_id=self._experiment_id,
                run_name=f"step_{node_name}",
                tags=step_tags,
                nested=self.nested_runs,
            ) as run:
                node_run_id = run.info.run_id
                with self._lock:
                    self._active_node_runs[node_name] = node_run_id
                logger.info(f"Started MLflow node step: {node_name}")

                if parameters:
                    mlflow.log_params(parameters)

                mlflow.log_param("node_start_time", datetime.now(timezone.utc).isoformat())
                yield node_run_id

                duration = time.perf_counter() - start_time
                mlflow.log_metric("node_duration_seconds", duration)
                mlflow.log_param("node_end_time", datetime.now(timezone.utc).isoformat())
                logger.info(f"Completed MLflow node step: {node_name} ({duration:.2f}s)")

        except Exception as e:
            logger.error(f"Node step {node_name} failed: {e}")
            with self._lock:
                node_run_id_for_error = self._active_node_runs.get(node_name)
            if node_run_id_for_error:
                try:
                    # B-04: log the error param within the node's own run context,
                    # not in the ambient / parent run context.
                    with mlflow.start_run(run_id=node_run_id_for_error, nested=True):
                        mlflow.log_param("error_message", str(e))
                    self._tracking_client.set_terminated(node_run_id_for_error, status="FAILED")
                except Exception:
                    pass
            raise
        finally:
            with self._lock:
                self._active_node_runs.pop(node_name, None)
                self._node_start_times.pop(node_name, None)

    def log_node_metric(
        self,
        key: str,
        value: Union[float, int],
        step: Optional[int] = None,
        node_name: Optional[str] = None,
    ) -> None:
        """Log metric for the current or specified node."""
        try:
            with self._lock:
                run_id = self._active_node_runs.get(node_name) if node_name else None
            if run_id:
                self._tracking_client.log_metric(run_id, key, value, step=step or 0)
            else:
                mlflow.log_metric(key, value, step=step)
            logger.debug(f"Logged metric {key}={value}")
        except Exception as e:
            self._not_recorded(f"metric '{key}'", e)

    def log_node_param(
        self,
        key: str,
        value: Any,
        node_name: Optional[str] = None,
    ) -> None:
        """Log parameter for the current or specified node."""
        try:
            with self._lock:
                run_id = self._active_node_runs.get(node_name) if node_name else None
            if run_id:
                self._tracking_client.log_param(run_id, key, value)
            else:
                mlflow.log_param(key, value)
            logger.debug(f"Logged param {key}={value}")
        except Exception as e:
            self._not_recorded(f"param '{key}'", e)

    def log_model(
        self,
        model: Any,
        artifact_path: str,
        flavor: Optional[str] = None,
        node_name: Optional[str] = None,
        **kwargs,
    ) -> None:
        """Log ML model for the current node.

        MLflow's flavor-specific ``log_model`` functions (sklearn, xgboost, ...)
        only log to the fluent API's ambient "active run" — there is no
        ``MlflowClient``-based equivalent that takes an explicit ``run_id``.
        That ambient state is a single process-global stack, not thread-local,
        so two node threads (``node_executor.py`` runs nodes in a thread pool)
        can otherwise race on it. ``self._lock`` serializes access; when the
        target run is already the active one in this thread (the normal case:
        called from within ``start_node_step``'s block), logging directly
        avoids re-entering ``mlflow.start_run(run_id=...)``, which would end
        the run early via MLflow's own context-manager teardown before
        ``start_node_step`` finishes recording duration/end time.
        """
        try:
            run_id = self._active_node_runs.get(node_name) if node_name else None
            if run_id:
                with self._lock:
                    active = mlflow.active_run()
                    if active is not None and active.info.run_id == run_id:
                        _log_model_by_flavor(model, artifact_path, flavor, **kwargs)
                    else:
                        with mlflow.start_run(run_id=run_id):
                            _log_model_by_flavor(model, artifact_path, flavor, **kwargs)
            else:
                _log_model_by_flavor(model, artifact_path, flavor, **kwargs)
            logger.info(f"Logged model to: {artifact_path}")
        except Exception as e:
            self._not_recorded(f"model '{artifact_path}'", e)

    def log_pipeline_metric(
        self,
        key: str,
        value: Union[float, int],
        step: Optional[int] = None,
    ) -> None:
        """Log metric at pipeline level (not node level)."""
        if not self._active_pipeline_run:
            logger.warning("No active pipeline run")
            return
        try:
            self._tracking_client.log_metric(self._active_pipeline_run, key, value, step=step or 0)
            logger.debug(f"Logged pipeline metric {key}={value}")
        except Exception as e:
            self._not_recorded(f"pipeline metric '{key}'", e)

    def _not_recorded(self, what: str, error: Exception) -> None:
        """A logging call failed: fail when MLflow is required, else say so as an error.

        It used to be a warning — easy to miss, and a model "logged" this way simply was
        not there afterwards, with the run reported as a success.
        """
        if self.required:
            raise MLflowTrackingError(f"MLflow did not record the {what}: {error}") from error
        logger.error(
            "MLflow did NOT record the {}: {}. The run continues without it; set "
            "`settings.mlflow.required: true` (or `mlops_required: true`) to fail instead.",
            what,
            error,
        )

    @staticmethod
    def from_context(context, experiment_name: Optional[str] = None) -> "MLflowPipelineTracker":
        """Factory method to create tracker from Ducta context."""
        if not MLFLOW_AVAILABLE:
            raise ImportError("MLflow is required")

        gs = getattr(context, "global_config", {}) or {}
        mlflow_config = gs.get("mlflow", {}) or {}

        experiment_name = str(
            experiment_name
            or mlflow_config.get("experiment_name")
            or getattr(context, "project_name", None)
            or "Ducta_pipeline"
        )

        # Resolve tracking_uri considering environment structure
        tracking_uri = mlflow_config.get("tracking_uri")
        resolved_tracking_uri = TrackingURIResolver.resolve_tracking_uri(
            tracking_uri=tracking_uri,
            context=context,
        )

        tags = {
            "project": getattr(context, "project_name", "unknown"),
            "environment": gs.get("env", "unknown"),
        }
        tags.update(mlflow_config.get("tags", {}) or {})

        return MLflowPipelineTracker(
            experiment_name=experiment_name,
            tracking_uri=resolved_tracking_uri,
            artifact_location=mlflow_config.get("artifact_location"),
            enable_autolog=mlflow_config.get("enable_autolog", True),
            nested_runs=mlflow_config.get("nested_runs", True),
            required=bool(mlflow_config.get("required") or gs.get("mlops_required")),
            tags=tags,
        )


def _log_model_by_flavor(
    model: Any,
    artifact_path: str,
    flavor: Optional[str],
    **kwargs,
) -> None:
    """Log a model using the appropriate MLflow flavor.

    Module-level (uses no instance state) so both ``MLflowPipelineTracker.
    log_model`` and ``MLflowNodeContext.log_model`` share one flavor-detection
    implementation instead of the latter hand-rolling a subset of it.
    """
    # Only the flavor in use is touched: `mlflow.<flavor>` is a lazy module that
    # imports its framework on first access, so building a table of every flavor's
    # log_model up front raised ModuleNotFoundError (no tensorflow) for every model.
    flavors = ("sklearn", "xgboost", "pytorch", "tensorflow")

    where = _model_location(artifact_path)
    if flavor in flavors:
        getattr(mlflow, flavor).log_model(model, **where, **kwargs)
    elif flavor == "pyfunc":
        mlflow.pyfunc.log_model(python_model=model, **where, **kwargs)
    elif hasattr(model, "fit") and hasattr(model, "predict"):
        mlflow.sklearn.log_model(model, **where, **kwargs)
    else:
        mlflow.pyfunc.log_model(python_model=model, **where, **kwargs)


class MLflowNodeContext:
    """
    Convenient context manager for logging in pipeline nodes.
    """

    def __init__(self, node_name: str):
        self.node_name = node_name
        self.start_time = None

    def __enter__(self):
        if MLFLOW_AVAILABLE:
            self.start_time = time.perf_counter()
            mlflow.log_param("node_name", self.node_name)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if MLFLOW_AVAILABLE and self.start_time:
            duration = time.perf_counter() - self.start_time
            mlflow.log_metric(f"{self.node_name}_duration", duration)
            if exc_type:
                mlflow.log_param(f"{self.node_name}_error", str(exc_val))

    def log_param(self, key: str, value: Any) -> None:
        """Log parameter."""
        if MLFLOW_AVAILABLE:
            mlflow.log_param(key, value)

    def log_metric(self, key: str, value: float, step: int = 0) -> None:
        """Log metric."""
        if MLFLOW_AVAILABLE:
            mlflow.log_metric(key, value, step=step)

    def log_model(
        self, model: Any, artifact_path: str, flavor: Optional[str] = None, **kwargs
    ) -> None:
        """Log model, auto-detecting the flavor unless one is given."""
        if MLFLOW_AVAILABLE:
            _log_model_by_flavor(model, artifact_path, flavor, **kwargs)
