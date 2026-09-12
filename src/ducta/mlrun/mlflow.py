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
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from loguru import logger

from ducta.mlrun.config import TrackingURIResolver

MLFLOW_AVAILABLE = False
try:
    import mlflow  # type: ignore
    from mlflow.tracking import MlflowClient  # type: ignore

    MLFLOW_AVAILABLE = True
except ImportError:
    logger.debug("MLflow not installed. Install with: pip install mlflow")
    mlflow = None  # type: ignore
    MlflowClient = None  # type: ignore


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
            mlflow.set_tracking_uri(self.tracking_uri)
            logger.info(f"Set MLflow tracking URI: {self.tracking_uri}")

        if self.registry_uri:
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

        self._client: Optional[MlflowClient] = None
        self._experiment_id: Optional[str] = None
        self._active_pipeline_run: Optional[str] = None
        self._active_node_runs: Dict[str, str] = {}
        self._node_start_times: Dict[str, float] = {}
        # Lock to protect shared mutable state accessed from multiple threads
        self._lock = threading.RLock()

        self._initialize_mlflow()

    def _initialize_mlflow(self) -> None:
        """Initialize MLflow client and experiment."""
        try:
            if self.tracking_uri:
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
                    self._client.set_terminated(pipeline_run_id, status="FAILED")
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
                    self._client.set_terminated(node_run_id_for_error, status="FAILED")
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
                self._client.log_metric(run_id, key, value, step=step or 0)
            else:
                mlflow.log_metric(key, value, step=step)
            logger.debug(f"Logged metric {key}={value}")
        except Exception as e:
            logger.warning(f"Failed to log metric {key}: {e}")

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
                self._client.log_param(run_id, key, value)
            else:
                mlflow.log_param(key, value)
            logger.debug(f"Logged param {key}={value}")
        except Exception as e:
            logger.warning(f"Failed to log param {key}: {e}")

    def log_node_artifact(
        self,
        local_path: Union[str, Path],
        artifact_path: Optional[str] = None,
        node_name: Optional[str] = None,
    ) -> None:
        """Log artifact for the current or specified node.

        Uses ``self._client`` (an explicit run_id, no ambient state) rather
        than ``with mlflow.start_run(run_id=...):`` + the fluent
        ``mlflow.log_artifact(s)`` calls: the fluent API shares one process-
        global "active run" stack, so (1) exiting that inner ``with`` block
        ends the run via MLflow's own teardown, finalizing it before the
        outer ``start_node_step`` context (still logging duration/end time)
        has finished, and (2) nodes run on a thread pool
        (``node_executor.py``), so two nodes' threads racing on that shared
        global stack can misattribute artifacts to the wrong run.
        """
        try:
            local_path = str(local_path)
            run_id = self._active_node_runs.get(node_name) if node_name else None
            if run_id:
                if Path(local_path).is_dir():
                    self._client.log_artifacts(run_id, local_path, artifact_path)
                else:
                    self._client.log_artifact(run_id, local_path, artifact_path)
            else:
                if Path(local_path).is_dir():
                    mlflow.log_artifacts(local_path, artifact_path)
                else:
                    mlflow.log_artifact(local_path, artifact_path)
            logger.info(f"Logged artifact: {local_path}")
        except Exception as e:
            logger.warning(f"Failed to log artifact {local_path}: {e}")

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
            logger.warning(f"Failed to log model: {e}")

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
            self._client.log_metric(self._active_pipeline_run, key, value, step=step or 0)
            logger.debug(f"Logged pipeline metric {key}={value}")
        except Exception as e:
            logger.warning(f"Failed to log pipeline metric {key}: {e}")

    def get_node_run_id(self, node_name: str) -> Optional[str]:
        """Get run ID for a specific node."""
        return self._active_node_runs.get(node_name)

    def get_pipeline_run_id(self) -> Optional[str]:
        """Get active pipeline run ID."""
        return self._active_pipeline_run

    def is_tracking_active(self) -> bool:
        """Check if tracking is currently active."""
        return self._active_pipeline_run is not None

    @staticmethod
    def from_context(context, experiment_name: Optional[str] = None) -> "MLflowPipelineTracker":
        """Factory method to create tracker from Ducta context."""
        if not MLFLOW_AVAILABLE:
            raise ImportError("MLflow is required")

        gs = getattr(context, "global_config", {}) or {}
        mlflow_config = gs.get("mlflow", {}) or {}

        experiment_name = (
            experiment_name
            or mlflow_config.get("experiment_name")
            or getattr(context, "project_name", "Ducta_pipeline")
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
    flavor_map = {
        "sklearn": mlflow.sklearn.log_model,
        "xgboost": mlflow.xgboost.log_model,
        "pytorch": mlflow.pytorch.log_model,
        "tensorflow": mlflow.tensorflow.log_model,
    }

    if flavor in flavor_map:
        flavor_map[flavor](model, artifact_path, **kwargs)
    elif flavor == "pyfunc":
        mlflow.pyfunc.log_model(artifact_path, python_model=model, **kwargs)
    elif hasattr(model, "fit") and hasattr(model, "predict"):
        mlflow.sklearn.log_model(model, artifact_path, **kwargs)
    else:
        mlflow.pyfunc.log_model(artifact_path, python_model=model, **kwargs)


def _mlf_log_params_from_call(
    func: Callable, args, kwargs, log_params: Optional[List[str]]
) -> None:
    """Helper to log function parameters to MLflow."""
    if not log_params or not MLFLOW_AVAILABLE:
        return
    try:
        import inspect

        sig = inspect.signature(func)
        bound_args = sig.bind(*args, **kwargs)
        bound_args.apply_defaults()
        for param_name in log_params:
            if param_name in bound_args.arguments:
                value = bound_args.arguments[param_name]
                try:
                    mlflow.log_param(f"{func.__name__}_{param_name}", value)
                except Exception as e:
                    logger.debug(f"Could not log param {param_name}: {e}")
    except Exception as e:
        logger.debug(f"Could not bind or log params: {e}")


def mlflow_track(
    log_params: Optional[List[str]] = None,
    log_result_as: Optional[str] = None,
    log_execution_time: bool = True,
):
    """
    Decorator for automatic MLflow tracking of functions.
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            if not MLFLOW_AVAILABLE:
                return func(*args, **kwargs)

            _mlf_log_params_from_call(func, args, kwargs, log_params)

            start_time = time.perf_counter()
            result = func(*args, **kwargs)
            duration = time.perf_counter() - start_time

            if log_execution_time:
                try:
                    mlflow.log_metric(f"{func.__name__}_execution_time", duration)
                except Exception as e:
                    logger.debug(f"Could not log execution time: {e}")

            if log_result_as and isinstance(result, (int, float)):
                try:
                    mlflow.log_metric(log_result_as, result)
                except Exception as e:
                    logger.debug(f"Could not log result: {e}")

            return result

        return wrapper

    return decorator


def log_dataframe_stats(df: Any, prefix: str = "df") -> None:
    """
    Log basic DataFrame statistics to MLflow.
    """
    if not MLFLOW_AVAILABLE:
        return

    try:
        if hasattr(df, "toPandas"):
            # Spark DataFrame
            mlflow.log_metric(f"{prefix}_rows", df.count())
            mlflow.log_metric(f"{prefix}_cols", len(df.columns))
        else:
            # Pandas DataFrame
            mlflow.log_metric(f"{prefix}_rows", len(df))
            mlflow.log_metric(f"{prefix}_cols", len(df.columns))
            null_count = df.isnull().sum().sum()
            mlflow.log_metric(f"{prefix}_nulls", int(null_count))
            memory_mb = df.memory_usage(deep=True).sum() / 1024 / 1024
            mlflow.log_metric(f"{prefix}_memory_mb", memory_mb)
    except Exception as e:
        logger.debug(f"Could not log DataFrame stats: {e}")


def log_model_metrics(
    y_true: Any,
    y_pred: Any,
    prefix: str = "test",
    task_type: str = "classification",
) -> Dict[str, float]:
    """
    Log standard ML metrics to MLflow.
    """
    if not MLFLOW_AVAILABLE:
        return {}

    metrics = {}
    try:
        if task_type == "classification":
            from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score

            metrics[f"{prefix}_accuracy"] = accuracy_score(y_true, y_pred)
            metrics[f"{prefix}_precision"] = precision_score(
                y_true, y_pred, average="weighted", zero_division=0
            )
            metrics[f"{prefix}_recall"] = recall_score(
                y_true, y_pred, average="weighted", zero_division=0
            )
            metrics[f"{prefix}_f1"] = f1_score(y_true, y_pred, average="weighted", zero_division=0)
        else:
            from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

            metrics[f"{prefix}_mse"] = mean_squared_error(y_true, y_pred)
            metrics[f"{prefix}_rmse"] = mean_squared_error(y_true, y_pred) ** 0.5
            metrics[f"{prefix}_mae"] = mean_absolute_error(y_true, y_pred)
            metrics[f"{prefix}_r2"] = r2_score(y_true, y_pred)

        for key, value in metrics.items():
            mlflow.log_metric(key, value)
    except Exception as e:
        logger.warning(f"Could not log model metrics: {e}")

    return metrics


def log_confusion_matrix(
    y_true: Any,
    y_pred: Any,
    labels: Optional[List[str]] = None,
    filename: str = "confusion_matrix.png",
) -> None:
    """Log confusion matrix as artifact in MLflow."""
    if not MLFLOW_AVAILABLE:
        return

    try:
        import matplotlib.pyplot as plt  # type: ignore
        import seaborn as sns  # type: ignore
        from sklearn.metrics import confusion_matrix

        cm = confusion_matrix(y_true, y_pred)
        plt.figure(figsize=(8, 6))
        sns.heatmap(cm, annot=True, fmt="d", cmap="Blues", xticklabels=labels, yticklabels=labels)
        plt.title("Confusion Matrix")
        plt.ylabel("True Label")
        plt.xlabel("Predicted Label")
        plt.tight_layout()
        mlflow.log_figure(plt.gcf(), filename)
        plt.close()
    except Exception as e:
        logger.warning(f"Could not log confusion matrix: {e}")


def log_feature_importance(
    model: Any,
    feature_names: List[str],
    top_n: int = 10,
    filename: str = "feature_importance.png",
) -> None:
    """Log feature importance as artifact in MLflow."""
    if not MLFLOW_AVAILABLE:
        return

    try:
        import matplotlib.pyplot as plt  # type: ignore
        import pandas as pd

        if hasattr(model, "feature_importances_"):
            importances = model.feature_importances_
        elif hasattr(model, "coef_"):
            importances = abs(model.coef_[0])
        else:
            logger.warning("Model does not have feature_importances_ or coef_")
            return

        df = (
            pd.DataFrame({"feature": feature_names, "importance": importances})
            .sort_values("importance", ascending=False)
            .head(top_n)
        )

        plt.figure(figsize=(10, 6))
        plt.barh(df["feature"], df["importance"])
        plt.xlabel("Importance")
        plt.title(f"Top {top_n} Feature Importances")
        plt.tight_layout()
        mlflow.log_figure(plt.gcf(), filename)
        plt.close()

        for _, row in df.iterrows():
            mlflow.log_metric(f"importance_{row['feature'].replace(' ', '_')}", row["importance"])
    except Exception as e:
        logger.warning(f"Could not log feature importance: {e}")


def log_training_curve(
    train_scores: List[float],
    val_scores: Optional[List[float]] = None,
    metric_name: str = "accuracy",
    filename: str = "training_curve.png",
) -> None:
    """Log training curve as artifact in MLflow."""
    if not MLFLOW_AVAILABLE:
        return

    try:
        import matplotlib.pyplot as plt  # type: ignore

        epochs = range(1, len(train_scores) + 1)
        plt.figure(figsize=(10, 6))
        plt.plot(epochs, train_scores, label=f"Train {metric_name}", marker="o")
        if val_scores:
            plt.plot(epochs, val_scores, label=f"Val {metric_name}", marker="s")
        plt.xlabel("Epoch")
        plt.ylabel(metric_name.capitalize())
        plt.title(f"Training Curve - {metric_name}")
        plt.legend()
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        mlflow.log_figure(plt.gcf(), filename)
        plt.close()

        for epoch, score in enumerate(train_scores, 1):
            mlflow.log_metric(f"train_{metric_name}", score, step=epoch)
        if val_scores:
            for epoch, score in enumerate(val_scores, 1):
                mlflow.log_metric(f"val_{metric_name}", score, step=epoch)
    except Exception as e:
        logger.warning(f"Could not log training curve: {e}")


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


class MLflowHelper:
    """Helper utilities for working with MLflow in ducta."""

    @staticmethod
    def log_dataframe_sample(
        df: Any,
        name: str = "data_sample",
        n_rows: int = 100,
        artifact_path: Optional[str] = None,
    ) -> None:
        """Log DataFrame sample as artifact."""
        if not MLFLOW_AVAILABLE:
            return

        try:
            import tempfile

            if hasattr(df, "toPandas"):
                df = df.limit(n_rows).toPandas()
            else:
                df = df.head(n_rows)

            with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
                df.to_csv(f.name, index=False)
                temp_path = f.name

            mlflow.log_artifact(temp_path, artifact_path or "data")
            Path(temp_path).unlink(missing_ok=True)
            logger.debug(f"Logged DataFrame sample: {name}")
        except Exception as e:
            logger.warning(f"Could not log DataFrame sample: {e}")

    @staticmethod
    def log_plot(fig: Any, name: str, artifact_path: Optional[str] = None) -> None:
        """Log matplotlib/plotly figure as artifact."""
        if not MLFLOW_AVAILABLE:
            return

        try:
            import tempfile

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                temp_path = f.name

            if hasattr(fig, "savefig"):
                fig.savefig(temp_path, bbox_inches="tight", dpi=150)
            elif hasattr(fig, "write_image"):
                fig.write_image(temp_path)
            else:
                logger.warning(f"Unknown figure type: {type(fig)}")
                return

            mlflow.log_artifact(temp_path, artifact_path or "plots")
            Path(temp_path).unlink(missing_ok=True)
            logger.debug(f"Logged plot: {name}")
        except Exception as e:
            logger.warning(f"Could not log plot: {e}")

    @staticmethod
    def log_dict_as_json(
        data: Dict[str, Any],
        name: str,
        artifact_path: Optional[str] = None,
    ) -> None:
        """Log dictionary as JSON artifact."""
        if not MLFLOW_AVAILABLE:
            return

        try:
            import json
            import tempfile

            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
                json.dump(data, f, indent=2)
                temp_path = f.name

            mlflow.log_artifact(temp_path, artifact_path or "config")
            Path(temp_path).unlink(missing_ok=True)
            logger.debug(f"Logged JSON: {name}")
        except Exception as e:
            logger.warning(f"Could not log JSON: {e}")

    @staticmethod
    def get_best_run(
        experiment_name: str,
        metric: str,
        mode: str = "max",
    ) -> Optional[Any]:
        """Get best run from experiment by metric."""
        if not MLFLOW_AVAILABLE:
            return None

        try:
            client = MlflowClient()
            experiment = client.get_experiment_by_name(experiment_name)
            if not experiment:
                logger.warning(f"Experiment not found: {experiment_name}")
                return None

            runs = client.search_runs(
                experiment_ids=[experiment.experiment_id],
                filter_string="",
                order_by=[f"metrics.{metric} {'DESC' if mode == 'max' else 'ASC'}"],
                max_results=1,
            )
            return runs[0] if runs else None
        except Exception as e:
            logger.warning(f"Could not get best run: {e}")
            return None

    @staticmethod
    def log_system_metrics() -> None:
        """Log system metrics (CPU, memory, etc.)."""
        if not MLFLOW_AVAILABLE:
            return

        try:
            import psutil  # type: ignore

            mlflow.log_metric("system_cpu_percent", psutil.cpu_percent())
            mlflow.log_metric("system_memory_percent", psutil.virtual_memory().percent)
            logger.debug("Logged system metrics")
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"Could not log system metrics: {e}")


def setup_mlflow_for_Ducta(
    config: Optional[MLflowConfig] = None,
    config_path: Optional[str] = None,
) -> MLflowConfig:
    """
    Complete MLflow setup for ducta.
    """
    if config is None:
        if config_path and Path(config_path).exists():
            config = MLflowConfig.from_yaml(config_path)
        else:
            config = MLflowConfig.from_env()

    config.apply()
    return config
