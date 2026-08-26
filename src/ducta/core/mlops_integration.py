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

from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from loguru import logger  # type: ignore

from ducta.mlrun.config import MLOpsContext
from ducta.mlrun.experiment_tracking import RunStatus

if TYPE_CHECKING:
    from ducta.setting.contexts import Context


class MLOpsExecutorIntegration:
    """
    Integration between Executor and MLOps layer.
    """

    def __init__(
        self,
        context: Optional["Context"] = None,
        mlops_context: Optional[MLOpsContext] = None,
        auto_init: bool = True,
        pipeline_name: Optional[str] = None,
    ):
        """
        Initialize MLOps-Executor integration.
        """
        self.context = context
        self.mlops_context = mlops_context
        self.pipeline_name = pipeline_name
        self.active_experiment_id: Optional[str] = None
        self.active_run_id: Optional[str] = None
        self.pipeline_runs: Dict[str, str] = {}  # pipeline_name -> run_id
        self.node_artifacts: Dict[str, List[str]] = {}  # run_id -> artifact_paths

        if self.mlops_context is None and auto_init:
            if self.context is not None:
                try:
                    self.mlops_context = MLOpsContext.from_context(
                        self.context,
                        pipeline_name=pipeline_name,
                    )
                    logger.info("MLOpsContext initialized from execution context")
                except Exception as e:
                    logger.warning(f"Could not init MLOpsContext from context: {e}")
            else:
                logger.debug(
                    "MLOps auto-init skipped: no context available. "
                    "MLOps will not be available unless explicitly configured."
                )

    def is_available(self) -> bool:
        """Check if MLOps context is available with all core components."""
        return (
            self.mlops_context is not None
            and self.mlops_context.experiment_tracker is not None
            and self.mlops_context.model_registry is not None
        )

    def create_pipeline_experiment(
        self,
        pipeline_name: str,
        pipeline_type: str,
        description: str = "",
        tags: Optional[Dict[str, str]] = None,
    ) -> Optional[str]:
        """
        Create experiment for pipeline execution.
        """
        if not self.is_available():
            return None

        try:
            tags = tags or {}
            processed_tags = {str(k): str(v) for k, v in tags.items() if v is not None}
            processed_tags.update(
                {
                    "pipeline_type": str(pipeline_type),
                    "pipeline_name": str(pipeline_name),
                }
            )

            exp = self.mlops_context.experiment_tracker.create_experiment(
                name=pipeline_name,
                description=description,
                tags=processed_tags,
            )

            self.active_experiment_id = exp.experiment_id
            logger.info(f"Created MLOps experiment {pipeline_name} (ID: {exp.experiment_id})")
            return exp.experiment_id

        except Exception as e:
            logger.error(f"Failed to create experiment: {e}")
            return None

    def start_pipeline_run(
        self,
        experiment_id: str,
        pipeline_name: str,
        model_version: Optional[str] = None,
        hyperparams: Optional[Dict[str, Any]] = None,
        tags: Optional[Dict[str, str]] = None,
    ) -> Optional[str]:
        """
        Start a run for pipeline execution.
        """
        if not self.is_available():
            return None

        try:
            tags = tags or {}
            tags.update(
                {
                    "pipeline_name": pipeline_name,
                    "model_version": model_version or "unknown",
                }
            )

            env_snapshot = self._capture_environment()
            if env_snapshot is not None:
                tags["git_commit"] = env_snapshot.git_commit or "unknown"
                tags["git_branch"] = env_snapshot.git_branch or "unknown"
                tags["python_version"] = env_snapshot.python_version
                tags["ducta_version"] = env_snapshot.ducta_version
                tags["env_hash"] = env_snapshot.env_hash or "unknown"

            run = self.mlops_context.experiment_tracker.start_run(
                experiment_id=experiment_id,
                name=f"{pipeline_name}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
                parameters=hyperparams or {},
                tags=tags,
            )

            self.active_run_id = run.run_id
            self.pipeline_runs[pipeline_name] = run.run_id
            self.node_artifacts[run.run_id] = []

            if env_snapshot is not None:
                try:
                    import json

                    self.mlops_context.experiment_tracker.log_parameter(
                        run.run_id,
                        "_environment_snapshot",
                        json.dumps(env_snapshot.to_dict(), default=str),
                    )
                except Exception as e:
                    logger.debug(f"Could not log environment snapshot parameter: {e}")

            if self.context:
                try:
                    config_snapshot = {
                        "global_settings": getattr(self.context, "global_settings", {}),
                        "pipelines_config": getattr(self.context, "pipelines_config", {}),
                        "nodes_config": getattr(self.context, "nodes_config", {}),
                    }
                    import json
                    import os
                    import tempfile

                    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
                        json.dump(config_snapshot, f, default=str, indent=2)
                        tmp_path = f.name
                    self.mlops_context.experiment_tracker.log_artifact(
                        run.run_id, tmp_path, destination="config_snapshot"
                    )
                    os.unlink(tmp_path)
                except Exception as e:
                    logger.debug(f"Config snapshot skipped: {e}")

            self._stash_previous_fingerprints(experiment_id, pipeline_name, run.run_id)

            logger.info(f"Started MLOps run {pipeline_name} (ID: {run.run_id})")
            return run.run_id

        except Exception as e:
            logger.error(f"Failed to start run: {e}")
            return None

    def _get_fingerprint_policy(self) -> str:
        """Read fingerprint_policy from global settings (dict or object form)."""
        if not self.context:
            return "record"
        from ducta.core.settings import CoreSettings

        return CoreSettings.from_context(self.context).fingerprint_policy

    def _stash_previous_fingerprints(
        self, experiment_id: str, pipeline_name: str, current_run_id: str
    ) -> None:
        """Load input fingerprints of the last successful run into the context."""
        try:
            if self._get_fingerprint_policy() == "record" or not self.context:
                return

            import json

            runs = self.mlops_context.experiment_tracker.list_runs(
                experiment_id,
                status_filter=RunStatus.COMPLETED,
                tag_filter={"pipeline_name": pipeline_name},
            )
            candidates = [
                r
                for r in runs
                if r["run_id"] != current_run_id
                and (r.get("parameters") or {}).get("_input_fingerprints")
            ]
            if not candidates:
                return

            candidates.sort(key=lambda r: r.get("created_at") or "", reverse=True)
            previous = json.loads(candidates[0]["parameters"]["_input_fingerprints"])

            from ducta.core.ledger import ledger_for

            ledger_for(self.context).previous_input_fingerprints = previous
            logger.debug(
                f"Loaded input fingerprints from previous run {candidates[0]['run_id']} "
                f"for fingerprint_policy enforcement"
            )
        except Exception as e:
            logger.debug(f"Could not load previous fingerprints: {e}")

    def _capture_environment(self) -> Optional[Any]:
        """Capture execution environment snapshot.  Never raises."""
        try:
            from ducta.mlrun.environment import EnvironmentSnapshot

            return EnvironmentSnapshot.capture(include_packages=True)
        except Exception as e:
            logger.debug(f"Environment capture skipped: {e}")
            return None

    def log_node_execution(
        self,
        run_id: str,
        node_name: str,
        status: str,
        duration_seconds: float,
        metrics: Optional[Dict[str, float]] = None,
        error: Optional[str] = None,
    ) -> None:
        """
        Log node execution details.
        """
        if not self.is_available() or not run_id:
            return

        try:
            log_strategy = {"log_metrics": True}
            try:
                from ducta.core.mlops_auto_config import MLOpsAutoConfigurator

                if self.context and hasattr(self.context, "nodes_config"):
                    node_cfg = self.context.nodes_config.get(node_name, {})
                    ml_stage = MLOpsAutoConfigurator.resolve_ml_stage(node_cfg)
                    log_strategy = MLOpsAutoConfigurator.get_logging_strategy(ml_stage)
            except Exception as e:
                logger.debug(f"Could not load logging strategy: {e}")

            self.mlops_context.experiment_tracker.log_parameter(
                run_id,
                f"node_{node_name}_status",
                status,
            )

            self.mlops_context.experiment_tracker.log_metric(
                run_id,
                f"node_{node_name}_duration_seconds",
                duration_seconds,
                step=0,
            )

            if metrics and log_strategy.get("log_metrics", True):
                for metric_name, value in metrics.items():
                    if isinstance(value, (int, float)):
                        self.mlops_context.experiment_tracker.log_metric(
                            run_id,
                            f"node_{node_name}_{metric_name}",
                            float(value),
                            step=0,
                        )

            if error:
                self.mlops_context.experiment_tracker.log_parameter(
                    run_id,
                    f"node_{node_name}_error",
                    error,
                )

            logger.debug(f"Logged execution for node {node_name}")

        except Exception as e:
            logger.warning(f"Could not log node execution: {e}")

    def log_pipeline_metrics(
        self,
        run_id: str,
        metrics: Dict[str, float],
    ) -> None:
        """
        Log pipeline-level metrics.
        """
        if not self.is_available() or not run_id:
            return

        try:
            for metric_name, value in metrics.items():
                if isinstance(value, (int, float)):
                    self.mlops_context.experiment_tracker.log_metric(
                        run_id,
                        metric_name,
                        float(value),
                        step=0,
                    )

            logger.debug("Logged pipeline metrics")

        except Exception as e:
            logger.warning(f"Could not log pipeline metrics: {e}")

    def log_artifact(
        self,
        run_id: str,
        artifact_path: str,
        artifact_type: str = "model",
    ) -> Optional[str]:
        """
        Log artifact for run.
        """
        if not self.is_available() or not run_id:
            return None

        try:
            artifact_uri = self.mlops_context.experiment_tracker.log_artifact(
                run_id,
                artifact_path,
                destination=f"artifacts/{artifact_type}",
            )

            if run_id in self.node_artifacts:
                self.node_artifacts[run_id].append(artifact_uri)

            logger.info(f"Logged artifact {artifact_type}: {artifact_uri}")
            return artifact_uri

        except Exception as e:
            logger.warning(f"Could not log artifact: {e}")
            return None

    def end_pipeline_run(
        self,
        run_id: str,
        status: RunStatus = RunStatus.COMPLETED,
        summary: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, float]:
        """
        End pipeline run.
        """
        if not self.is_available() or not run_id:
            return {}

        final_metrics: Dict[str, float] = {}
        try:
            # Log summary if provided
            if summary:
                for key, value in summary.items():
                    if isinstance(value, (int, float)):
                        self.mlops_context.experiment_tracker.log_metric(
                            run_id,
                            f"summary_{key}",
                            float(value),
                            step=0,
                        )

            # Log data fingerprints for lineage tracking
            import json

            if self.context:
                from ducta.core.ledger import ledger_for

                ledger = ledger_for(self.context)
                in_fps = ledger.input_fingerprints
                out_fps = ledger.output_fingerprints

                if in_fps:
                    self.mlops_context.experiment_tracker.log_parameter(
                        run_id, "_input_fingerprints", json.dumps(in_fps, default=str)
                    )
                if out_fps:
                    self.mlops_context.experiment_tracker.log_parameter(
                        run_id, "_output_fingerprints", json.dumps(out_fps, default=str)
                    )

            tracker = self.mlops_context.experiment_tracker
            try:
                for metric_name in list(tracker.get_run(run_id).metrics.keys()):
                    latest = tracker.get_latest_metric(run_id, metric_name)
                    if latest is not None:
                        final_metrics[metric_name] = float(latest.value)
            except Exception as e:
                logger.debug(f"Could not snapshot final metrics for run {run_id}: {e}")

            # End the run
            tracker.end_run(run_id, status)

            logger.info(f"Ended MLOps run {run_id} with status {status.value}")

            # Clean up
            self.active_run_id = None
            if run_id in self.node_artifacts:
                del self.node_artifacts[run_id]

        except Exception as e:
            logger.error(f"Failed to end run: {e}")

        return final_metrics

    def register_model_from_run(
        self,
        run_id: str,
        model_name: str,
        artifact_path: str,
        artifact_type: str,
        framework: str,
        description: str = "",
        hyperparams: Optional[Dict[str, Any]] = None,
        metrics: Optional[Dict[str, float]] = None,
        tags: Optional[Dict[str, str]] = None,
    ) -> Optional[str]:
        """
        Register trained model in Model Registry from run artifacts.
        """
        if not self.is_available():
            return None

        try:
            enriched_tags = dict(tags or {})

            if self.context:
                environment = getattr(self.context, "env", None) or getattr(
                    self.context, "environment", None
                )
                if environment:
                    enriched_tags["environment"] = str(environment)
                    logger.debug(f"Registering model in environment: {environment}")
                else:
                    logger.warning(
                        "No environment detected in context. "
                        "Model will be registered without environment tag."
                    )

                exec_mode = getattr(self.context, "execution_mode", None)
                if exec_mode:
                    enriched_tags["execution_mode"] = str(exec_mode)

            model_version = self.mlops_context.model_registry.register_model(
                name=model_name,
                artifact_path=artifact_path,
                artifact_type=artifact_type,
                framework=framework,
                description=description,
                hyperparameters=hyperparams,
                metrics=metrics,
                tags=enriched_tags,
                experiment_run_id=run_id,
            )

            logger.info(
                f"Registered model {model_name} v{model_version.version} from run {run_id} "
                f"(environment: {enriched_tags.get('environment', 'unknown')})"
            )

            return model_version.artifact_uri

        except Exception as e:
            logger.error(f"Failed to register model: {e}")
            return None

    def get_run_comparison(
        self,
        experiment_id: str,
        metric_filter: Optional[Dict[str, tuple]] = None,
    ) -> Any:
        """
        Get DataFrame comparing runs in experiment.
        """
        if not self.is_available():
            return None

        try:
            run_ids = self.mlops_context.experiment_tracker.search_runs(
                experiment_id,
                metric_filter=metric_filter,
            )

            if not run_ids:
                return None

            comparison_df = self.mlops_context.experiment_tracker.compare_runs(run_ids)

            logger.info(f"Generated comparison DataFrame for {len(run_ids)} runs")
            return comparison_df

        except Exception as e:
            logger.warning(f"Could not generate comparison: {e}")
            return None


class MLInfoConfigLoader:
    """
    Loader for ML configuration from YAML/JSON/TOML files.
    """

    @staticmethod
    def load_ml_info_from_file(
        filepath: str,
    ) -> Dict[str, Any]:
        """
        Load ML info from YAML or JSON file.
        """
        path = Path(filepath)

        if not path.exists():
            logger.warning(f"ML info file not found: {filepath}")
            return {}

        try:
            if path.suffix in [".yml", ".yaml"]:
                import yaml  # type: ignore

                with open(path) as f:
                    data = yaml.safe_load(f) or {}
            elif path.suffix == ".json":
                import json

                with open(path) as f:
                    data = json.load(f)
            else:
                logger.warning(f"Unsupported file format: {path.suffix}")
                return {}

            logger.info(f"Loaded ML info from {filepath}")
            return data

        except Exception as e:
            logger.error(f"Failed to load ML info from {filepath}: {e}")
            return {}

    @staticmethod
    def load_ml_info_from_context(
        context,
        pipeline_name: str,
    ) -> Dict[str, Any]:
        """
        Load ML info from context using existing method.
        """
        if not hasattr(context, "get_pipeline_ml_config"):
            return {}

        try:
            ml_config = context.get_pipeline_ml_config(pipeline_name)
            return ml_config or {}
        except Exception as e:
            logger.warning(f"Could not load ML config from context: {e}")
            return {}

    @staticmethod
    def merge_ml_info(
        base_ml_info: Dict[str, Any],
        override_ml_info: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Merge ML info dictionaries with override taking precedence.
        """
        merged = dict(base_ml_info)
        merged.update(override_ml_info)

        # Merge nested dicts
        for key in ["hyperparams", "metrics", "tags"]:
            if (
                key in base_ml_info
                and key in override_ml_info
                and isinstance(base_ml_info[key], dict)
                and isinstance(override_ml_info[key], dict)
            ):
                merged_nested = dict(base_ml_info[key])
                merged_nested.update(override_ml_info[key])
                merged[key] = merged_nested

        return merged
