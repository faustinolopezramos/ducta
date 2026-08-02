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

import gc
import json
import time
from collections import defaultdict
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from loguru import logger  # type: ignore

from ducta.core.dependency_resolver import DependencyResolver
from ducta.core.mlops_auto_config import MLOpsAutoConfigurator
from ducta.core.node_executor import NodeExecutor
from ducta.core.pipeline_state import NodeType, UnifiedPipelineState
from ducta.setting.contexts import Context

try:
    from ducta.core.mlflow_node_executor import MLflowNodeExecutor
    from ducta.mlrun.mlflow import MLflowPipelineTracker

    MLFLOW_INTEGRATION_AVAILABLE = True
except ImportError:
    MLFLOW_INTEGRATION_AVAILABLE = False
    MLflowNodeExecutor = None
    MLflowPipelineTracker = None
from ducta.check import (
    QualityOutputManager,
    QualityReport,
    QualityReporter,
    SanityCheckReport,
    SanityPhaseRunner,
)
from ducta.check.core import QualityGateBlocked
from ducta.core.mlops_integration import MLOpsExecutorIntegration
from ducta.core.pipeline_validator import PipelineValidator
from ducta.core.split_validator import document_split_semantics
from ducta.core.utils import extract_pipeline_nodes
from ducta.gate.constants import WriteMode
from ducta.gate.input import InputLoader
from ducta.gate.output import DataOutputManager
from ducta.stream.constants import PipelineType
from ducta.stream.pipeline_manager import StreamingPipelineManager


class _MLOpsRequiredError(Exception):
    """Internal sentinel: MLOps unavailability that must abort the pipeline
    because ``mlops_required`` is set. Caught and re-raised as a RuntimeError
    with a clear message by the caller — never meant to escape this module."""


class BaseExecutor:
    """Base class for pipeline executors."""

    DEFAULT_TIMEOUT_SECONDS = 3600
    MAX_TIMEOUT_SECONDS = 86400

    def __init__(self, context: Context):
        self.context = context

        self._mlops_context = None
        self._mlops_auto_config = MLOpsAutoConfigurator()
        self._mlops_init_attempted = False
        self._mlops_pipeline_name: Optional[str] = None

        self.input_loader = InputLoader(self.context)
        self.output_manager = DataOutputManager(self.context)
        self.quality_output_manager = QualityOutputManager(self.context)
        self.is_ml_layer = getattr(self.context, "is_ml_layer", False)
        gs = getattr(self.context, "global_settings", {}) or {}
        self.max_workers = gs.get("max_parallel_nodes", 4)
        configured_timeout = gs.get("execution_timeout_seconds", self.DEFAULT_TIMEOUT_SECONDS)
        self.timeout_seconds = min(configured_timeout, self.MAX_TIMEOUT_SECONDS)
        if self.timeout_seconds != configured_timeout:
            logger.warning(
                f"Configured timeout {configured_timeout}s exceeds maximum, "
                f"using {self.timeout_seconds}s instead"
            )

        self._mlflow_enabled = self._should_enable_mlflow()
        self._mlflow_required = self._is_mlops_required()
        self._mlflow_tracker = None
        if self._mlflow_enabled and MLFLOW_INTEGRATION_AVAILABLE:
            try:
                self._mlflow_tracker = MLflowPipelineTracker.from_context(self.context)
                self.node_executor = MLflowNodeExecutor(
                    self.context,
                    self.input_loader,
                    self.output_manager,
                    self._mlflow_tracker,
                    self.max_workers,
                    mlops_context=None,
                    quality_output_manager=self.quality_output_manager,
                )
                logger.info("MLflow integration enabled for pipeline execution")
            except Exception as e:
                if self._mlflow_required:
                    raise RuntimeError(
                        f"MLOps (MLflow) initialization failed and is required by config "
                        f"(mlops_required=true). Pipeline aborted. Error: {e}"
                    ) from e
                logger.warning("Could not enable MLflow: {}. Falling back to standard executor.", e)
                self.node_executor = NodeExecutor(
                    self.context,
                    self.input_loader,
                    self.output_manager,
                    self.max_workers,
                    mlops_context=None,
                    quality_output_manager=self.quality_output_manager,
                )
        else:
            self.node_executor = NodeExecutor(
                self.context,
                self.input_loader,
                self.output_manager,
                self.max_workers,
                mlops_context=None,
                quality_output_manager=self.quality_output_manager,
            )

        self.unified_state = None
        self._sanity_reports: List[SanityCheckReport] = []

    def _should_enable_mlflow(self) -> bool:
        """
        Determine if MLflow should be enabled.
        """
        if not MLFLOW_INTEGRATION_AVAILABLE:
            return False

        import os

        env_enabled = os.getenv("Ducta_MLFLOW_ENABLED", "false").lower() == "true"
        if env_enabled:
            return True

        gs = getattr(self.context, "global_settings", {}) or {}
        mlflow_config = gs.get("mlflow", {}) or {}

        return mlflow_config.get("enabled", False)

    def _is_mlops_required(self) -> bool:
        """
        Determine if MLOps is required (hard-fail on initialization failure).
        """
        gs = getattr(self.context, "global_settings", {}) or {}
        return bool(gs.get("mlops_required", False))

    def _should_init_mlops(self) -> bool:
        """
        Determine if MLOps should be initialized for this execution.
        """
        gs = getattr(self.context, "global_settings", {}) or {}

        return self._mlops_auto_config.should_init_mlops_for_pipeline(self.context.nodes_config, gs)

    def _init_mlops_if_needed(self, pipeline_name: Optional[str] = None) -> None:
        """
        Initialize MLOps lazily if needed.
        """
        if self._mlops_init_attempted:
            return

        self._mlops_init_attempted = True

        if not self._should_init_mlops():
            logger.debug("MLOps initialization skipped (not needed for this pipeline)")
            return

        try:
            active_env = getattr(self.context, "env", None)
            if active_env:
                logger.debug("MLOps will use active environment from context: '{}'", active_env)
            else:
                active_env = getattr(self.context, "environment", None)
                if active_env:
                    logger.debug("MLOps will use environment attribute: '{}'", active_env)

            from ducta.mlrun.config import MLOpsContext

            self._mlops_context = MLOpsContext.from_context(
                self.context,
                pipeline_name=pipeline_name,
            )
            logger.info(
                "MLOps initialized successfully (auto-detected ML workload{})",
                f", pipeline: {pipeline_name}" if pipeline_name else "",
            )
        except Exception as e:
            if self._mlflow_required:
                raise RuntimeError(
                    f"MLOps initialization failed and is required by config "
                    f"(mlops_required=true). Pipeline aborted. Error: {e}"
                ) from e
            logger.warning("MLOps initialization failed (non-critical): {}", e)
            self._mlops_context = None

    @property
    def mlops_context(self):
        """Get MLOps context (lazy initialization, preferring pipeline-specific config if available)."""
        if not self._mlops_init_attempted:
            pipeline_name = self._mlops_pipeline_name
            if pipeline_name:
                logger.debug("Initializing MLOps with pipeline-specific config: {}", pipeline_name)
            self._init_mlops_if_needed(pipeline_name=pipeline_name)

        return self._mlops_context

    def _prepare_ml_info(
        self,
        pipeline_name: str,
        model_version: Optional[str],
        hyperparams: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Prepare ML-specific information."""
        ml_info: Dict[str, Any] = {}
        pipeline_ml_config: Dict[str, Any] = {}
        merged_hyperparams = dict(hyperparams or {})
        final_model_version = model_version or getattr(self.context, "default_model_version", None)

        if hasattr(self.context, "get_pipeline_ml_config"):
            pipeline_ml_config = self.context.get_pipeline_ml_config(pipeline_name) or {}
            final_model_version = (
                model_version
                or pipeline_ml_config.get("model_version")
                or getattr(self.context, "default_model_version", None)
            )
            merged_hyperparams.update(getattr(self.context, "default_hyperparams", {}) or {})
            merged_hyperparams.update(pipeline_ml_config.get("hyperparams", {}) or {})
            if hyperparams:
                merged_hyperparams.update(hyperparams)

            if hasattr(self.context, "get_model_registry"):
                try:
                    model_registry = self.context.get_model_registry()
                    model = model_registry.get_model(
                        pipeline_ml_config.get("model_name"), version=final_model_version
                    )
                    if model is not None:
                        ml_info["model"] = model
                except Exception:
                    pass

            ml_info.update(
                {
                    "model_version": final_model_version,
                    "hyperparams": merged_hyperparams,
                    "pipeline_config": pipeline_ml_config,
                    "project_name": getattr(self.context, "project_name", ""),
                    "is_experiment": "experiment" in pipeline_name.lower()
                    or "tuning" in pipeline_name.lower(),
                }
            )

        elif self.is_ml_layer:
            merged_hyperparams.update(getattr(self.context, "default_hyperparams", {}) or {})
            if hyperparams:
                merged_hyperparams.update(hyperparams)
            ml_info = {
                "model_version": final_model_version,
                "hyperparams": merged_hyperparams,
                "pipeline_config": pipeline_ml_config,
                "is_experiment": "experiment" in pipeline_name.lower()
                or "tuning" in pipeline_name.lower(),
            }

        if ml_info:
            ml_info.setdefault("seed", self._resolve_global_seed())
            ml_info.setdefault("split", self._get_pipeline_split_config(pipeline_name))

        return ml_info

    def _get_pipeline_split_config(self, pipeline_name: str) -> Optional[Dict[str, Any]]:
        """Fetch the declarative split block from the pipeline config, if any."""
        pipelines_config = getattr(self.context, "pipelines_config", {}) or {}
        pipeline_cfg = pipelines_config.get(pipeline_name, {}) or {}
        split = pipeline_cfg.get("split")
        if split is not None and hasattr(split, "model_dump"):
            split = split.model_dump()

        if split:
            semantics_doc = document_split_semantics(split)
            logger.info("Pipeline '{}' train/test split config:\n{}", pipeline_name, semantics_doc)

        return split

    def _resolve_global_seed(self) -> Optional[int]:
        """Resolve global random seed from settings (dict or object form)."""
        gs = getattr(self.context, "global_settings", {}) or {}
        if isinstance(gs, dict):
            return gs.get("random_seed")
        return getattr(gs, "random_seed", None)

    def _log_pipeline_start(
        self, pipeline_name: str, ml_info: Dict[str, Any], pipeline_type: str
    ) -> None:
        """Log pipeline execution start."""
        if self.is_ml_layer:
            logger.info("Starting {} ML Pipeline: '{}'", pipeline_type, pipeline_name)
            logger.info("Project: {}", ml_info.get("project_name", "Unknown"))

            if self._resolve_global_seed() is None:
                logger.warning(
                    "ML pipeline '{}' is running WITHOUT random_seed: results will "
                    "not be reproducible. Set global_settings.random_seed.",
                    pipeline_name,
                )

            model_version = ml_info.get("model_version")
            if model_version and str(model_version).lower() != "none":
                logger.info("Model Version: {}", model_version)
        else:
            logger.info("Running {} pipeline '{}'", pipeline_type.lower(), pipeline_name)

    def _get_node_configs(self, pipeline_nodes: List[str]) -> Dict[str, Dict[str, Any]]:
        """Collect node configs for the nodes present in a pipeline."""
        nodes_config = getattr(self.context, "nodes_config", {}) or {}
        return {
            node_name: (nodes_config[node_name] or {})
            for node_name in pipeline_nodes
            if node_name in nodes_config
        }

    def _get_pipeline_config(self, pipeline_name: str) -> Dict[str, Any]:
        """Get pipeline configuration from context."""
        pipeline = self.context.pipelines.get(pipeline_name)
        if not pipeline:
            raise ValueError(f"Pipeline '{pipeline_name}' not found")
        return pipeline

    def _aggregate_and_persist_quality_summary(self) -> None:
        """Aggregate and persist global quality summary after pipeline execution."""
        try:
            if not hasattr(self.context, "quality_output_paths"):
                logger.debug("No quality outputs to aggregate")
                return

            quality_outputs = self.context.quality_output_paths
            if not quality_outputs:
                logger.debug("Pipeline quality output list is empty, skipping aggregation")
                return

            # Group outputs by report type
            outputs_by_type = defaultdict(list)
            outputs_by_node = defaultdict(list)

            for output_path in quality_outputs:
                report_type = output_path.report_type
                node_name = output_path.node_name

                outputs_by_type[report_type].append(output_path)
                outputs_by_node[node_name].append(output_path)

            logger.info(
                f"Aggregating quality outputs: {len(quality_outputs)} total outputs "
                f"({len(outputs_by_type)} types, {len(outputs_by_node)} nodes)"
            )

            # Log summary statistics
            for report_type, outputs in outputs_by_type.items():
                logger.info(f"  {report_type}: {len(outputs)} reports")

            # Optional: Persist global summary
            global_config = getattr(self.context, "global_settings", {}).get("quality", {})
            summary_config = global_config.get("global_summary", {})

            if summary_config.get("enabled", False):
                self._persist_global_quality_summary(
                    outputs_by_type, outputs_by_node, summary_config
                )

        except Exception as e:
            logger.error(f"Failed to aggregate quality summary: {e}")

    def _persist_global_quality_summary(
        self,
        outputs_by_type: Dict[str, List],
        outputs_by_node: Dict[str, List],
        config: Dict[str, Any],
    ) -> None:
        """Persist the global quality summary to configured storage."""
        try:
            output_path = config.get("output_path", "./.quality/global_summary")
            output_format = config.get("format", "json")

            logger.info(f"Persisting global quality summary to {output_path} ({output_format})")

            # Create summary data structure
            summary = {
                "timestamp": time.time(),
                "total_outputs": sum(len(v) for v in outputs_by_type.values()),
                "outputs_by_type": {
                    k: [{"node": o.node_name, "path": o.output_path} for o in v]
                    for k, v in outputs_by_type.items()
                },
                "outputs_by_node": {
                    k: [{"type": o.report_type, "path": o.output_path} for o in v]
                    for k, v in outputs_by_node.items()
                },
            }

            # Save summary
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)

            with open(f"{output_path}.{output_format}", "w") as f:
                if output_format == "json":
                    json.dump(summary, f, indent=2, default=str)
                else:
                    f.write(str(summary))

            logger.info("Global quality summary persisted successfully")

        except Exception as e:
            logger.warning(f"Failed to persist global quality summary: {e}")

    def _run_preflight_sanity_checks(
        self, node_configs: Dict[str, Dict[str, Any]]
    ) -> List[QualityReport]:
        has_sanity_checks = any(
            (nc.get("sanity_checks") or {}).get("enabled", True)
            for nc in node_configs.values()
            if nc.get("sanity_checks")
        )

        if not has_sanity_checks:
            logger.debug("No preflight sanity checks configured for this pipeline")
            return []

        logger.info("Running preflight sanity checks...")

        # Load quality profiles from global_settings so profile= references resolve
        try:
            from ducta.check.profiles import load_profiles as _load_profiles

            _gs = getattr(self.context, "global_settings", {}) or {}
            _profiles = _load_profiles(_gs) if isinstance(_gs, dict) else {}
        except Exception:
            _profiles = {}

        runner = SanityPhaseRunner(fail_fast=True, profiles=_profiles)
        pipeline_config = {"nodes": node_configs}
        reports = runner.run_preflight_checks(
            pipeline_config, self.context, pipeline_name=self._mlops_pipeline_name or "_adhoc"
        )

        QualityReporter().render_pipeline_summary(reports, show_details=True)

        logger.info(
            "Preflight sanity checks completed: {} node(s) checked, {} error(s)",
            len(reports),
            sum(r.errors_count for r in reports.values()),
        )

        return reports


class BatchExecutor(BaseExecutor):
    """Executor for batch pipelines."""

    def execute(
        self,
        pipeline_name: str,
        node_name: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        model_version: Optional[str] = None,
        hyperparams: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._mlops_pipeline_name = pipeline_name
        # Lets sanity/DQ checks (ducta.check) scope their storage per pipeline
        # without threading pipeline_name through every intermediate call —
        # same pattern as _mlops_pipeline_name above.
        self.node_executor.pipeline_name = pipeline_name
        pipeline = self._get_pipeline_config(pipeline_name)

        gs = getattr(self.context, "global_settings", {}) or {}

        # Apply global random seed for reproducibility
        seed = self._resolve_global_seed()

        if seed is not None:
            try:
                import random

                random.seed(seed)

                try:
                    import numpy as np  # type: ignore

                    np.random.seed(seed)
                except ImportError:
                    pass

                try:
                    import torch  # type: ignore

                    torch.manual_seed(seed)
                except ImportError:
                    pass
                logger.info(f"Applied global random seed: {seed}")
                if self.is_ml_layer and getattr(self, "max_workers", 1) > 1:
                    logger.warning(
                        "Global seed is set once at pipeline start, but nodes run on "
                        "parallel threads sharing the process-wide RNG, so global "
                        "random/numpy calls inside nodes are not reproducible under "
                        "parallelism. For deterministic per-node randomness build a "
                        "local generator from ml_context['node_seed'] "
                        "(e.g. numpy.random.default_rng(ml_context['node_seed']))."
                    )
            except Exception as e:
                logger.warning(f"Failed to apply random seed: {e}")

        start_date = start_date or (
            gs.get("start_date") if isinstance(gs, dict) else getattr(gs, "start_date", None)
        )
        end_date = end_date or (
            gs.get("end_date") if isinstance(gs, dict) else getattr(gs, "end_date", None)
        )

        ml_info = self._build_ml_info(pipeline_name, model_version, hyperparams)
        ml_info["pipeline_type"] = pipeline.get("type", PipelineType.BATCH.value)

        self._log_pipeline_start(pipeline_name, ml_info, "BATCH")

        self.unified_state = UnifiedPipelineState()
        self.unified_state.set_pipeline_status("running")
        mlops_integration, mlops_run_id = self._start_mlops_integration(
            pipeline, pipeline_name, ml_info
        )
        # Propagate the real MLOpsContext into ml_context['mlops_context'] for
        # node functions — NodeExecutor was constructed with mlops_context=None
        # since MLOps isn't resolved until this per-run call.
        self.node_executor.set_mlops_context(
            mlops_integration.mlops_context if mlops_integration else None
        )

        try:
            if mlops_integration and mlops_run_id:
                ml_info["mlops_integration"] = mlops_integration
                ml_info["mlops_run_id"] = mlops_run_id

            self._execute_batch_flow(pipeline, node_name, start_date, end_date, ml_info)
            self.unified_state.set_pipeline_status("completed")
            self._end_mlops_run(
                success=True, mlops_integration=mlops_integration, mlops_run_id=mlops_run_id
            )

        except Exception:
            self.unified_state.set_pipeline_status("failed")
            self._end_mlops_run(
                success=False, mlops_integration=mlops_integration, mlops_run_id=mlops_run_id
            )
            raise
        finally:
            if self.unified_state:
                self.unified_state.cleanup()
            # Free any in-memory handoff frames persisted during this run.
            from ducta.gate import handoff

            handoff.clear(self.context)

    def _end_mlops_run(
        self,
        success: bool,
        mlops_integration: Optional[MLOpsExecutorIntegration],
        mlops_run_id: Optional[str],
    ) -> None:
        """Close MLOps run with given status."""
        if not mlops_integration or not mlops_run_id:
            return

        try:
            if success:
                mlops_integration.end_pipeline_run(mlops_run_id)
            else:
                from ducta.mlrun.experiment_tracking import RunStatus

                mlops_integration.end_pipeline_run(mlops_run_id, status=RunStatus.FAILED)
        except Exception as e:
            log_fn = logger.warning if success else logger.error
            msg = (
                f"Failed to end MLOps run {mlops_run_id}"
                + (
                    " — pipeline completed but tracking record may be incomplete"
                    if success
                    else " — failed to record failure"
                )
                + f": {e}"
            )
            log_fn(msg)

    def _build_ml_info(
        self,
        pipeline_name: str,
        model_version: Optional[str],
        hyperparams: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Build or fetch the ml_info and apply CLI overrides."""
        if hasattr(self.context, "get_pipeline_ml_info"):
            ml_info = self.context.get_pipeline_ml_info(pipeline_name) or {}
        else:
            ml_info = self._prepare_ml_info(pipeline_name, model_version, hyperparams)

        if model_version is not None:
            ml_info["model_version"] = model_version

        if hyperparams:
            merged_h = dict(ml_info.get("hyperparams", {}) or {})
            merged_h.update(hyperparams)
            ml_info["hyperparams"] = merged_h

        final_h = ml_info.get("hyperparams")
        if isinstance(final_h, dict):
            for reserved in ("sweep_id", "sweep_index"):
                if reserved in final_h:
                    ml_info[reserved] = final_h.pop(reserved)

        ml_info.setdefault("seed", self._resolve_global_seed())
        ml_info.setdefault("split", self._get_pipeline_split_config(pipeline_name))

        return ml_info

    @staticmethod
    def _parse_bool_setting(name: str, raw: Any, *, default: bool) -> bool:
        """Strictly coerce a global-settings flag to bool."""
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str):
            normalized = raw.strip().lower()
            if normalized in ("true", "yes", "on", "1"):
                return True
            if normalized in ("false", "no", "off", "0", ""):
                return False
            logger.warning(
                "Global setting '{}' has unrecognized value {!r}; expected a boolean "
                "(true/false). Falling back to default={}.",
                name,
                raw,
                default,
            )
            return default
        return bool(raw)

    def _start_mlops_integration(
        self,
        pipeline: Dict[str, Any],
        pipeline_name: str,
        ml_info: Dict[str, Any],
    ) -> Tuple[Optional[MLOpsExecutorIntegration], Optional[str]]:
        """Initialize MLOps integration and start a pipeline run if available."""
        mlops_integration: Optional[MLOpsExecutorIntegration] = None
        mlops_run_id: Optional[str] = None
        experiment_id: Optional[str] = None

        gs = getattr(self.context, "global_settings", {}) or {}
        raw = gs.get("mlops_enabled", True)
        mlops_enabled = self._parse_bool_setting("mlops_enabled", raw, default=True)

        if not mlops_enabled:
            logger.debug("MLOps tracking disabled via global settings (mlops_enabled: false)")
            return None, None

        try:
            mlops_integration = MLOpsExecutorIntegration(
                context=self.context,
                auto_init=True,
                pipeline_name=pipeline_name,
            )
            if not mlops_integration.is_available():
                if self._mlflow_required:
                    raise _MLOpsRequiredError(
                        "MLOps initialization failed and is required by config "
                        "(mlops_required=true): storage backend / experiment tracker "
                        "could not be initialized (commonly a missing/unresolvable "
                        "'output_path')."
                    )
                return mlops_integration, None

            pipeline_type = pipeline.get("type", PipelineType.BATCH.value)
            description = ml_info.get("description") or ""

            tags = {
                "project_name": str(ml_info.get("project_name") or ""),
                "model_name": str(ml_info.get("model_name") or pipeline_name),
                "pipeline_type": str(pipeline_type),
            }

            experiment_id = mlops_integration.create_pipeline_experiment(
                pipeline_name=pipeline_name,
                pipeline_type=str(pipeline_type),
                description=description,
                tags=tags,
            )

            if experiment_id:
                run_params = dict(ml_info.get("hyperparams") or {})
                if ml_info.get("seed") is not None:
                    run_params["seed"] = ml_info["seed"]
                split_cfg = ml_info.get("split")
                if isinstance(split_cfg, dict):
                    run_params.update(
                        {f"split_{k}": v for k, v in split_cfg.items() if v is not None}
                    )

                run_tags = {
                    "env": str(self.context.global_settings.get("env", "")),
                    "execution_mode": str(getattr(self.context, "execution_mode", "")),
                }
                if self.context.global_settings.get("project_id"):
                    run_tags["project_id"] = str(self.context.global_settings["project_id"])
                hp_cfg = ml_info.get("hyperparams_config")
                if hp_cfg is not None:
                    run_params["hp_algorithm"] = hp_cfg.algorithm
                    run_params["hp_cv_folds"] = hp_cfg.cv_folds
                    if hp_cfg.algorithm in ("random", "bayesian"):
                        run_params["hp_n_trials"] = hp_cfg.n_trials

                if ml_info.get("sweep_id"):
                    run_params["sweep_id"] = ml_info["sweep_id"]
                    if ml_info.get("sweep_index") is not None:
                        run_params["sweep_index"] = ml_info["sweep_index"]
                    run_tags["sweep_id"] = str(ml_info["sweep_id"])

                mlops_run_id = mlops_integration.start_pipeline_run(
                    experiment_id=experiment_id,
                    pipeline_name=pipeline_name,
                    model_version=str(ml_info.get("model_version") or ""),
                    hyperparams=run_params,
                    tags=run_tags,
                )

        except _MLOpsRequiredError as e:
            raise RuntimeError(
                f"MLOps (experiment tracking) initialization failed and is required by "
                f"config (mlops_required=true). Pipeline aborted. Error: {e}"
            ) from e
        except Exception as e:
            if self._mlflow_required:
                raise RuntimeError(
                    f"MLOps integration initialization failed and is required by config "
                    f"(mlops_required=true). Pipeline aborted. Error: {e}"
                ) from e
            logger.warning(
                f"MLOps integration initialization failed: {e}. "
                f"Pipeline will execute without experiment tracking."
            )
            mlops_integration = None
            mlops_run_id = None

        return mlops_integration, mlops_run_id

    def _execute_batch_flow(
        self,
        pipeline: Dict[str, Any],
        node_name: Optional[str],
        start_date: str,
        end_date: str,
        ml_info: Dict[str, Any],
    ) -> None:
        """Execute batch flow logic with optional MLflow tracking."""
        pipeline_name = pipeline.get("name", "batch_pipeline")

        if self._mlflow_enabled and self._mlflow_tracker:
            with self._mlflow_tracker.start_pipeline_run(
                pipeline_name=pipeline_name,
                parameters={
                    "start_date": start_date,
                    "end_date": end_date,
                    "model_version": ml_info.get("model_version"),
                    "node_name": node_name or "all",
                },
                tags={
                    "pipeline_type": "batch",
                    "executor": "BatchExecutor",
                },
            ) as run_id:
                logger.info(
                    f"Batch pipeline '{pipeline_name}' tracked in MLflow (run_id: {run_id})"
                )
                self._execute_batch_nodes(node_name, pipeline, start_date, end_date, ml_info)
        else:
            self._execute_batch_nodes(node_name, pipeline, start_date, end_date, ml_info)

    def _execute_batch_nodes(
        self,
        node_name: Optional[str],
        pipeline: Dict[str, Any],
        start_date: str,
        end_date: str,
        ml_info: Dict[str, Any],
    ) -> None:
        """Execute batch nodes (single or all)."""
        if node_name:
            from ducta.gate.exceptions import MissingDependencyError

            try:
                self.node_executor.execute_single_node(node_name, start_date, end_date, ml_info)
            except MissingDependencyError as e:
                # Atomic single-node run (--node) with skip_missing_deps=True and the
                # node's inputs aren't available yet — not a failure, but nothing ran.
                # Callers (CLI/API) check `_skipped_atomic_node` to report a clean
                # "skipped" result instead of success/failure.
                logger.warning("Node '{}' skipped (missing dependencies): {}", node_name, e)
                self._skipped_atomic_node = {"node": node_name, "reason": str(e)}
        else:
            pipeline_nodes = extract_pipeline_nodes(pipeline)
            self._execute_pipeline_nodes(pipeline_nodes, start_date, end_date, ml_info)

    def _execute_pipeline_nodes(
        self,
        pipeline_nodes: List[str],
        start_date: str,
        end_date: str,
        ml_info: Dict[str, Any],
    ) -> None:
        """Execute all nodes in batch pipeline."""
        node_configs = self._get_node_configs(pipeline_nodes)
        PipelineValidator.validate_node_configs(pipeline_nodes, node_configs)
        PipelineValidator.validate_no_dag_cycles(pipeline_nodes, node_configs)

        # F4.3: Run preflight sanity checks if any node has them enabled
        sanity_reports = self._run_preflight_sanity_checks(node_configs)
        if sanity_reports:
            self._sanity_reports = sanity_reports

        dag = DependencyResolver.build_dependency_graph(pipeline_nodes, node_configs)
        execution_order = DependencyResolver.topological_sort(dag)

        self.node_executor.execute_nodes_parallel(
            execution_order, node_configs, dag, start_date, end_date, ml_info
        )

        # HOOK 5: Global summary aggregation
        self._aggregate_and_persist_quality_summary()


class StreamingExecutor(BaseExecutor):
    """Executor for streaming pipelines."""

    def __init__(self, context: Context):
        super().__init__(context)
        max_streaming_pipelines = context.global_settings.get("max_streaming_pipelines", 5)
        self.streaming_manager = StreamingPipelineManager(context, max_streaming_pipelines)
        self._exit_stack = ExitStack()
        self._active_execution_id = None

    def execute(
        self,
        pipeline_name: str,
        execution_mode: Optional[str] = "async",
    ) -> str:
        self._mlops_pipeline_name = pipeline_name
        self.node_executor.pipeline_name = pipeline_name
        logger.info("Executing streaming pipeline: {}", pipeline_name)

        pipeline = self._get_pipeline_config(pipeline_name)
        running_pipelines = self.streaming_manager.list_running_pipelines()
        conflicts = self._check_resource_conflicts(pipeline, running_pipelines)

        if conflicts:
            logger.warning("Potential resource conflicts detected: {}", conflicts)

        # Start MLflow tracking if enabled
        if self._mlflow_enabled and self._mlflow_tracker:
            try:
                run_ctx = self._mlflow_tracker.start_pipeline_run(
                    pipeline_name=pipeline_name,
                    parameters={"execution_mode": execution_mode},
                    tags={"pipeline_type": "streaming", "executor": "StreamingExecutor"},
                )
                run_id = self._exit_stack.enter_context(run_ctx)
                logger.info("Streaming pipeline tracked in MLflow (run_id: {})", run_id)
            except Exception as e:
                logger.warning("Failed to start MLflow run for streaming: {}", e)

        execution_id = self.streaming_manager.start_pipeline(pipeline_name, pipeline)
        self._active_execution_id = execution_id

        logger.info(
            "Streaming pipeline '{}' started with execution_id: {}",
            pipeline_name,
            execution_id,
        )

        if execution_mode == "sync":
            self._wait_for_streaming_pipeline(execution_id)
            self.shutdown()

        return execution_id

    @property
    def active_execution_id(self) -> Optional[str]:
        """Return the ID of the current (or last) streaming execution."""
        return self._active_execution_id

    def shutdown(self) -> None:
        """Shutdown streaming executor and close MLflow run."""
        try:
            self._exit_stack.close()
            logger.info("Streaming pipeline MLflow run closed")
        except Exception as e:
            logger.warning("Failed to close MLflow run for streaming: {}", e)

        if hasattr(self.streaming_manager, "shutdown"):
            self.streaming_manager.shutdown()

    def _check_resource_conflicts(
        self, pipeline: Dict[str, Any], running_pipelines: List[Dict[str, Any]]
    ) -> List[str]:
        """Check resource conflicts with running pipelines."""
        conflicts = []
        current_resources = self._extract_pipeline_resources(pipeline)

        for running in running_pipelines:
            running_resources = self._extract_pipeline_resources(running)

            common_topics = current_resources["kafka_topics"] & running_resources["kafka_topics"]
            if common_topics:
                conflicts.append(f"Kafka topic conflict: topics {', '.join(common_topics)}")

            common_paths = current_resources["file_paths"] & running_resources["file_paths"]
            if common_paths:
                conflicts.append(f"File path conflict: paths {', '.join(common_paths)}")

            common_tables = current_resources["delta_tables"] & running_resources["delta_tables"]
            if common_tables:
                conflicts.append(f"Delta table conflict: tables {', '.join(common_tables)}")

        return conflicts

    def _add_kafka_from_subscribe(
        self, resources: Dict[str, Set[str]], subscribe_value: Any
    ) -> None:
        if isinstance(subscribe_value, str):
            topics = [t.strip() for t in subscribe_value.split(",") if t.strip()]
        elif isinstance(subscribe_value, (list, tuple, set)):
            topics = [str(t).strip() for t in subscribe_value if str(t).strip()]
        else:
            topics = []
        for t in topics:
            resources["kafka_topics"].add(t)

    def _add_kafka_from_assign(self, resources: Dict[str, Set[str]], assign_value: Any) -> None:
        try:
            mapping = json.loads(assign_value) if isinstance(assign_value, str) else assign_value
            if isinstance(mapping, dict):
                for t in mapping.keys():
                    resources["kafka_topics"].add(t)
        except Exception:
            pass

    def _add_kafka_from_opts(self, resources: Dict[str, Set[str]], opts: Dict[str, Any]) -> None:
        if not opts:
            return
        if "subscribe" in opts:
            self._add_kafka_from_subscribe(resources, opts["subscribe"])
            return
        if "assign" in opts:
            self._add_kafka_from_assign(resources, opts["assign"])
            return
        if "subscribePattern" in opts:
            pattern = str(opts["subscribePattern"]).strip()
            if pattern:
                resources["kafka_topics"].add(f"pattern:{pattern}")

    def _extract_path_from_config(self, cfg: Dict[str, Any]) -> Optional[str]:
        path = cfg.get("path")
        if path:
            return path
        opts = cfg.get("options", {}) or {}
        return opts.get("path")

    def _process_input_config(
        self, resources: Dict[str, Set[str]], node_cfg: Dict[str, Any]
    ) -> None:
        input_config = node_cfg.get("input", {}) or {}
        input_format = (input_config.get("format") or "").lower()
        if input_format == "kafka":
            self._add_kafka_from_opts(resources, input_config.get("options", {}) or {})
            return
        if input_format == "file_stream":
            path = self._extract_path_from_config(input_config)
            if path:
                resources["file_paths"].add(path)
            return
        if input_format in ("delta_stream", "delta"):
            path = self._extract_path_from_config(input_config)
            if path:
                resources["delta_tables"].add(path)

    def _process_output_config(
        self, resources: Dict[str, Set[str]], node_cfg: Dict[str, Any]
    ) -> None:
        output_config = node_cfg.get("output", {}) or {}
        output_format = (output_config.get("format") or "").lower()
        if output_format == "kafka":
            opar = output_config.get("options", {}) or {}
            topic = opar.get("topic") or opar.get("kafka.topic")
            if topic:
                resources["kafka_topics"].add(str(topic))
            return
        if output_format == "delta":
            out_path = self._extract_path_from_config(output_config)
            if out_path:
                resources["delta_tables"].add(out_path)

    def _extract_pipeline_resources(self, pipeline: Dict[str, Any]) -> Dict[str, Set[str]]:
        """Extract critical resources from pipeline configuration."""
        resources: Dict[str, Set[str]] = {
            "kafka_topics": set(),
            "file_paths": set(),
            "delta_tables": set(),
        }

        pipeline_nodes = extract_pipeline_nodes(pipeline)
        for node_name in pipeline_nodes:
            node_config = self.context.nodes_config.get(node_name, {}) or {}
            self._process_input_config(resources, node_config)
            self._process_output_config(resources, node_config)

        return resources

    def _wait_for_streaming_pipeline(
        self, execution_id: str, timeout_seconds: Optional[int] = None
    ) -> None:
        """Wait for streaming pipeline to reach a terminal state."""
        _timeout = timeout_seconds if timeout_seconds is not None else self.timeout_seconds
        self.streaming_manager.wait_for_pipeline_done(execution_id, timeout=float(_timeout))


class HybridExecutor(BaseExecutor):
    """Executor for hybrid pipelines."""

    def __init__(self, context: Context):
        super().__init__(context)
        max_streaming_pipelines = context.global_settings.get("max_streaming_pipelines", 5)
        self.streaming_manager = StreamingPipelineManager(context, max_streaming_pipelines)

    def execute(
        self,
        pipeline_name: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        model_version: Optional[str] = None,
        hyperparams: Optional[Dict[str, Any]] = None,
        execution_mode: Optional[str] = "async",
    ) -> Dict[str, Any]:
        self._mlops_pipeline_name = pipeline_name
        self.node_executor.pipeline_name = pipeline_name
        logger.info("Executing hybrid pipeline: {}", pipeline_name)

        pipeline = self._get_pipeline_config(pipeline_name)
        pipeline_nodes = extract_pipeline_nodes(pipeline)
        node_configs = self._get_node_configs(pipeline_nodes)

        validation_result = PipelineValidator.validate_hybrid_pipeline(
            pipeline, node_configs, self.context.format_policy
        )

        if not validation_result["is_valid"]:
            raise ValueError("Hybrid pipeline validation failed")

        self.unified_state = UnifiedPipelineState()
        ml_info = self._prepare_ml_info(pipeline_name, model_version, hyperparams)

        try:
            self._register_nodes_in_unified_state(
                validation_result["batch_nodes"],
                validation_result["streaming_nodes"],
                node_configs,
            )
            self.unified_state.set_streaming_stopper(
                lambda eid: self.streaming_manager.stop_pipeline(eid, graceful=True)
            )
            return self._execute_unified_hybrid_pipeline(
                validation_result["batch_nodes"],
                validation_result["streaming_nodes"],
                node_configs,
                start_date or self.context.global_settings.get("start_date"),
                end_date or self.context.global_settings.get("end_date"),
                ml_info,
                execution_mode,
            )
        finally:
            if self.unified_state:
                self.unified_state.cleanup()
            from ducta.gate import handoff

            handoff.clear(self.context)

    def _register_nodes_in_unified_state(
        self,
        batch_nodes: List[str],
        streaming_nodes: List[str],
        node_configs: Dict[str, Dict[str, Any]],
    ) -> None:
        """Register all nodes in unified state."""
        from ducta.core.dependency_inference import resolve_node_dependencies

        # Resolve over batch + streaming together so a streaming node that
        # consumes a batch node's dataset gets the inferred cross-type edge.
        all_nodes = list(batch_nodes) + list(streaming_nodes)
        resolved = resolve_node_dependencies(all_nodes, node_configs)

        for node_name in batch_nodes:
            self.unified_state.register_node(node_name, NodeType.BATCH, resolved[node_name])

        for node_name in streaming_nodes:
            self.unified_state.register_node(node_name, NodeType.STREAMING, resolved[node_name])

    def _execute_unified_hybrid_pipeline(
        self,
        batch_nodes: List[str],
        streaming_nodes: List[str],
        node_configs: Dict[str, Dict[str, Any]],
        start_date: str,
        end_date: str,
        ml_info: Dict[str, Any],
        execution_mode: str,
    ) -> Dict[str, Any]:
        """Execute hybrid pipeline with enhanced error handling."""
        execution_result = {
            "batch_execution": {},
            "streaming_execution_ids": [],
            "status": "success",
            "errors": [],
        }

        try:
            batch_results = self._execute_batch_phase(
                batch_nodes, node_configs, start_date, end_date, ml_info
            )
            execution_result["batch_execution"] = batch_results

            batch_failures = [
                node for node, result in batch_results.items() if result["status"] != "completed"
            ]

            if batch_failures:
                execution_result["status"] = "failed"
                execution_result["errors"] = [
                    f"Batch node failed: {node} - {batch_results[node].get('error')}"
                    for node in batch_failures
                ]
                logger.error("Batch phase failed, skipping streaming execution")
                return execution_result

            streaming_execution_ids = self._execute_streaming_phase(
                streaming_nodes, node_configs, execution_mode
            )
            execution_result["streaming_execution_ids"] = streaming_execution_ids

        except Exception as e:
            execution_result["status"] = "failed"
            execution_result["errors"].append(f"Hybrid pipeline failed: {str(e)}")
            logger.error("Hybrid pipeline execution failed: {}", e)

        return execution_result

    def _execute_batch_phase(
        self,
        batch_nodes: List[str],
        node_configs: Dict[str, Dict[str, Any]],
        start_date: str,
        end_date: str,
        ml_info: Dict[str, Any],
    ) -> Dict[str, Dict[str, Any]]:
        """Execute batch nodes with retries and dependency resolution."""
        results = {}
        PipelineValidator.validate_no_dag_cycles(batch_nodes, node_configs)
        dag = DependencyResolver.build_dependency_graph(batch_nodes, node_configs)
        execution_order = DependencyResolver.topological_sort(dag)

        for node in execution_order:
            if not self.unified_state.start_node_execution(node):
                # Recorded explicitly (not just skipped silently): without an
                # entry here, this node is simply absent from `results`, so
                # the batch_failures check in _execute_unified_hybrid_pipeline
                # never sees it — it neither blocks the streaming phase nor
                # appears in execution_result["errors"], even though it never
                # actually ran.
                results[node] = {"status": "skipped", "reason": "could_not_start"}
                continue

            try:
                # Per-node retries are handled inside execute_single_node via the
                # node's `retry` config — no blanket retry wrapper here.
                self.node_executor.execute_single_node(node, start_date, end_date, ml_info)
                results[node] = {"status": "completed"}
                self.unified_state.complete_node_execution(node)

            except Exception as e:
                results[node] = {"status": "failed", "error": str(e)}
                # Tag QualityGateBlocked so pipeline_state skips retry
                _err_str = (
                    f"[QualityGateBlocked] {e}" if isinstance(e, QualityGateBlocked) else str(e)
                )
                self.unified_state.fail_node_execution(node, _err_str)
                raise

        return results

    def _execute_streaming_phase(
        self,
        streaming_nodes: List[str],
        node_configs: Dict[str, Dict[str, Any]],
        execution_mode: str,
    ) -> List[str]:
        """Start the streaming nodes as a sub-pipeline and manage their lifecycle.

        The streaming nodes run through ``StreamingPipelineManager.start_pipeline``
        (the manager resolves each node's config from the context). Their
        ``dependencies`` on batch nodes are satisfied by the preceding batch phase,
        so within this streaming sub-pipeline they have no unmet dependencies.
        """
        execution_ids: List[str] = []
        startable = [n for n in streaming_nodes if self.unified_state.start_node_execution(n)]
        if not startable:
            return execution_ids

        stream_pipeline_name = f"{self._mlops_pipeline_name or 'hybrid'}__streaming"
        try:
            execution_id = self.streaming_manager.start_pipeline(
                stream_pipeline_name, {"nodes": startable}
            )
            execution_ids.append(execution_id)
            for node in startable:
                self.unified_state.register_streaming_query(node, execution_id)
                self.unified_state.complete_node_execution(node)
        except Exception as e:
            logger.error("Failed to start streaming nodes {}: {}", startable, e)
            _err_str = (
                f"[QualityGateBlocked] {e}" if type(e).__name__ == "QualityGateBlocked" else str(e)
            )
            for node in startable:
                self.unified_state.fail_node_execution(node, _err_str)
            raise

        if execution_mode == "sync":
            self._wait_for_streaming_completion(execution_ids)

        return execution_ids

    def _wait_for_streaming_completion(self, execution_ids: List[str], timeout_minutes=60):
        """Wait for all streaming executions to reach a terminal state."""
        deadline = time.time() + timeout_minutes * 60
        for eid in execution_ids:
            remaining = max(0.0, deadline - time.time())
            if not self.streaming_manager.wait_for_pipeline_done(eid, timeout=remaining):
                logger.warning("Timeout reached while waiting for streaming queries")
                return


class PipelineExecutor:
    """Orchestrator that delegates to specialized executors."""

    def __init__(self, context: Context, config_directory: Optional[str] = None):
        self.context = context
        self.config_directory = config_directory
        self._batch_executor: Optional[BatchExecutor] = None
        self._streaming_executor: Optional[StreamingExecutor] = None
        self._hybrid_executor: Optional[HybridExecutor] = None

        # Chain-reuse optimization: skip an ancestor pipeline in a depends_on
        # chain when its outputs are already materialized. Read the global
        # defaults here; per-run CLI flags override them in run_pipeline_chain.
        chain_cfg = (getattr(self.context, "global_settings", {}) or {}).get("chain", {}) or {}
        self._reuse_materialized_global = bool(chain_cfg.get("reuse_materialized", False))
        self._staleness_check = bool(chain_cfg.get("staleness_check", False))
        self._force_reuse = False
        self._force_rerun_all = False
        self.reused_pipelines: List[str] = []

    @property
    def batch_executor(self) -> BatchExecutor:
        """Lazy initialization of BatchExecutor."""
        if self._batch_executor is None:
            self._batch_executor = BatchExecutor(self.context)
        return self._batch_executor

    @property
    def streaming_executor(self) -> StreamingExecutor:
        """Lazy initialization of StreamingExecutor."""
        if self._streaming_executor is None:
            self._streaming_executor = StreamingExecutor(self.context)
        return self._streaming_executor

    @property
    def hybrid_executor(self) -> HybridExecutor:
        """Lazy initialization of HybridExecutor."""
        if self._hybrid_executor is None:
            self._hybrid_executor = HybridExecutor(self.context)
        return self._hybrid_executor

    def run_pipeline(
        self,
        pipeline_name: str,
        node_name: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        model_version: Optional[str] = None,
        hyperparams: Optional[Dict[str, Any]] = None,
        execution_mode: Optional[str] = "async",
    ) -> Union[None, str, Dict[str, Any]]:
        pipeline = self.batch_executor._get_pipeline_config(pipeline_name)
        pipeline_type = pipeline.get("type", PipelineType.BATCH.value)

        self._run_preflight(pipeline_name)

        if pipeline_type in [
            PipelineType.BATCH.value,
            PipelineType.ML.value,
            PipelineType.HYBRID.value,
        ]:
            requires_dates = pipeline.get("requires_dates", True)
            PipelineValidator.validate_required_params(
                pipeline_name,
                start_date,
                end_date,
                self.context.global_settings.get("start_date"),
                self.context.global_settings.get("end_date"),
                requires_dates=requires_dates,
            )

        # Streaming runs have their own execution_id lifecycle and, in async
        # mode, return before completion — a certificate would be premature.
        # In sync mode StreamingExecutor.execute() blocks until the stream
        # stops and shuts itself down before returning, so it IS a
        # terminating run and falls through to the same certificate-emitting
        # block as batch/ml/hybrid below, instead of returning early here.
        if pipeline_type == PipelineType.STREAMING.value and execution_mode != "sync":
            return self.streaming_executor.execute(pipeline_name, execution_mode)

        import uuid
        from datetime import datetime, timezone

        run_id = uuid.uuid4().hex
        try:
            setattr(self.context, "_run_id", run_id)
            # Fresh per-node trace + quality summaries for this run (executors append).
            setattr(self.context, "_run_node_details", [])
            setattr(self.context, "_quality_results", [])
        except Exception:
            pass
        started_at = datetime.now(timezone.utc)
        status = "success"
        error_msg: Optional[str] = None
        try:
            if pipeline_type in (PipelineType.BATCH.value, PipelineType.ML.value):
                return self.batch_executor.execute(
                    pipeline_name, node_name, start_date, end_date, model_version, hyperparams
                )
            elif pipeline_type == PipelineType.HYBRID.value:
                result = self.hybrid_executor.execute(
                    pipeline_name, start_date, end_date, model_version, hyperparams, execution_mode
                )
                # HybridExecutor reports failures in its result dict without
                # raising — reflect them in the certificate instead of "success".
                if isinstance(result, dict) and result.get("status") == "failed":
                    status = "failed"
                    error_msg = "; ".join(str(e) for e in result.get("errors") or []) or (
                        "hybrid pipeline failed"
                    )
                return result
            elif pipeline_type == PipelineType.STREAMING.value:
                return self.streaming_executor.execute(pipeline_name, execution_mode)
            else:
                raise ValueError(f"Unsupported pipeline type: {pipeline_type}")
        except Exception as e:
            status = "failed"
            error_msg = str(e)
            raise
        finally:
            self._emit_run_certificate(
                pipeline_name=pipeline_name,
                run_id=run_id,
                started_at=started_at,
                ended_at=datetime.now(timezone.utc),
                status=status,
                error=error_msg,
            )
            if status == "success" and node_name is None:
                self._record_chain_state(pipeline_name, pipeline_type, start_date, end_date)

    def _emit_run_certificate(
        self,
        *,
        pipeline_name: str,
        run_id: str,
        started_at: Any,
        ended_at: Any,
        status: str,
        error: Optional[str],
    ) -> None:
        """Assemble and persist the Run Certificate. Best-effort — never raises."""
        try:
            from ducta.core import certificate as cert_mod

            if not cert_mod.is_enabled(self.context):
                return
            try:
                from ducta import __version__ as ducta_version
            except Exception:  # noqa: BLE001
                ducta_version = "unknown"

            env_name = (
                getattr(self.context, "env", None)
                or (
                    (self.context.global_settings or {}).get("environment")
                    if isinstance(getattr(self.context, "global_settings", None), dict)
                    else None
                )
                or "base"
            )

            cert = cert_mod.build_certificate(
                self.context,
                run_id=run_id,
                pipeline=pipeline_name,
                environment_name=str(env_name),
                status=status,
                started_at=started_at,
                ended_at=ended_at,
                ducta_version=ducta_version,
                error=error,
            )
            signing_key = cert_mod.resolve_signing_key(self.context)
            if signing_key is not None:
                cert.sign(signing_key)
            run_dir = cert_mod.certificate_dir(self.context, run_id)
            path = cert_mod.write_certificate(cert, run_dir)
            logger.info("Run Certificate written: {} (run_id={}, status={})", path, run_id, status)
        except Exception as e:  # noqa: BLE001 — a certificate must never break a run
            logger.debug("Run Certificate emission skipped: {}", e)

    def _run_preflight(self, pipeline_name: str) -> None:
        """Validate the pipeline's configuration before executing it.

        Turns the class of errors that used to surface cryptically mid-DAG (a node
        function missing ``start_date``, a malformed output key, an unregistered
        intermediate) into a clear abort up front. Disabled with
        ``global_settings.preflight_enabled = false``. A bug *in* the preflight
        itself degrades to a warning rather than blocking execution.
        """
        gs = getattr(self.context, "global_settings", {}) or {}
        if not gs.get("preflight_enabled", True):
            return
        try:
            from ducta.core.preflight import validate_pipeline

            report = validate_pipeline(self.context, pipeline_name)
        except Exception as e:  # noqa: BLE001 — never let a preflight bug block a valid run
            # Fail-open is intentional (a bug in the validator itself must not
            # block an otherwise-valid run), but it was previously logged at
            # `debug` — typically suppressed in production — silently hiding
            # that preflight didn't actually run for this pipeline.
            logger.warning(
                "Preflight validation itself raised an exception and was skipped "
                "for pipeline '{}' (continuing without preflight checks): {}",
                pipeline_name,
                e,
            )
            return

        for warn in report.warnings:
            logger.warning("Preflight: {}", warn)
        if not report.ok:
            details = "\n  - ".join(report.errors)
            raise ValueError(
                f"Preflight validation failed for pipeline '{pipeline_name}' "
                f"({len(report.errors)} error(s)):\n  - {details}\n"
                f"Fix the configuration or run `ducta config validate` for details. "
                f"Set global_settings.preflight_enabled=false to bypass."
            )

    def get_active_streaming_execution_id(self) -> Optional[str]:
        """Return the internal execution_id of the running streaming pipeline."""
        if self._streaming_executor is None:
            return None

        # 1. Try to get the stored ID from the executor (persists even if failed/stopped)
        stored_id = self.streaming_executor.active_execution_id
        if stored_id:
            return stored_id

        # 2. Fallback to list (for pipelines started outside the API context, if any)
        try:
            running = self._streaming_executor.streaming_manager.list_running_pipelines()
            if running:
                return running[0].get("execution_id")
        except Exception:
            pass
        return None

    def get_streaming_pipeline_status(self, execution_id: str) -> Dict[str, Any]:
        """Return status info for a streaming pipeline execution."""
        try:
            return self.streaming_executor.streaming_manager.get_pipeline_status(execution_id) or {}
        except Exception:
            return {}

    def list_streaming_pipelines(self) -> List[Dict[str, Any]]:
        """List running streaming pipelines."""
        try:
            return self.streaming_executor.streaming_manager.list_running_pipelines()
        except Exception:
            return []

    def stop_streaming_pipeline(self, execution_id: str, graceful: bool = True) -> bool:
        """Stop a running streaming pipeline."""
        try:
            return self.streaming_executor.streaming_manager.stop_pipeline(execution_id, graceful)
        except Exception:
            return False

    def restart_streaming_node(self, execution_id: str, node_name: str) -> bool:
        """Restart a specific node in a running streaming pipeline."""
        try:
            return self.streaming_executor.streaming_manager.restart_node(execution_id, node_name)
        except Exception:
            return False

    def get_streaming_pipeline_metrics(self, execution_id: str) -> Dict[str, Any]:
        """Get metrics for a streaming pipeline."""
        try:
            return (
                self.streaming_executor.streaming_manager.get_pipeline_metrics(execution_id) or {}
            )
        except Exception:
            return {}

    def run_streaming_pipeline(
        self,
        pipeline_name: str,
        mode: str = "async",
        model_version: Optional[str] = None,
        hyperparams: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Execute a streaming pipeline (convenience wrapper for CLI)."""
        execution_mode = "sync" if mode == "sync" else "async"
        result = self.run_pipeline(
            pipeline_name=pipeline_name,
            model_version=model_version,
            hyperparams=hyperparams,
            execution_mode=execution_mode,
        )
        return result if isinstance(result, str) else ""

    def register_streaming_transforms(self, module_paths: List[str]) -> None:
        """Import Python modules and call register_transforms(registry) on each."""
        import importlib
        import os
        import sys

        cwd = os.getcwd()
        if cwd not in sys.path:
            sys.path.insert(0, cwd)

        registry = self.streaming_executor.streaming_manager.query_manager.transformation_registry
        for module_path in module_paths:
            try:
                module = importlib.import_module(module_path)
                if hasattr(module, "register_transforms") and callable(module.register_transforms):
                    module.register_transforms(registry)
                    logger.info("Registered transforms from module: {}", module_path)
                else:
                    logger.info(
                        "Imported module '{}' (no register_transforms function found — "
                        "relying on import-time registration)",
                        module_path,
                    )
            except ImportError as e:
                raise RuntimeError(
                    f"Cannot import transforms module '{module_path}': {e}. "
                    f"Ensure the module is on PYTHONPATH or run from the directory "
                    f"that contains it."
                ) from e

    def get_running_execution_ids(self) -> List[str]:
        """Get list of running execution IDs from streaming manager."""
        try:
            pipelines = self.streaming_executor.streaming_manager.list_running_pipelines()
            return [p.get("execution_id") for p in pipelines if p.get("execution_id")]
        except Exception:
            return []

    def run_pipeline_chain(
        self,
        pipeline_name: str,
        node_name: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        model_version: Optional[str] = None,
        hyperparams: Optional[Dict[str, Any]] = None,
        execution_mode: Optional[str] = "async",
        reuse_upstream: bool = False,
        rerun_all: bool = False,
    ) -> Union[None, str, Dict[str, Any]]:
        """Execute *pipeline_name* and its transitive dependencies in topological order.

        If the pipeline declares no ``depends_on``, this is identical to
        :meth:`run_pipeline`.  Otherwise the full ancestor chain is resolved and
        each pipeline is executed sequentially, stopping on the first failure.

        Args:
            pipeline_name: The target pipeline to execute.
            node_name: Optional single-node filter — applied only to the target pipeline.
            start_date / end_date: Date range — forwarded to every pipeline in the chain.
            model_version / hyperparams: Applied only to the target pipeline.
            execution_mode: Forwarded to every pipeline.

        Returns:
            The return value of the *target* pipeline's executor.
        """
        from ducta.core.dependency_inference import merge_pipeline_depends_on
        from ducta.core.pipeline_dependency_resolver import PipelineDependencyResolver

        # Per-run overrides of the global chain-reuse defaults (from CLI flags).
        self._force_reuse = bool(reuse_upstream)
        self._force_rerun_all = bool(rerun_all)
        self.reused_pipelines = []

        pipelines_config = getattr(self.context, "pipelines_config", {}) or {}
        nodes_config = getattr(self.context, "nodes_config", {}) or {}

        # Merge explicit `depends_on` with the dependencies inferred from
        # cross-pipeline dataset flow (a pipeline consuming another's output).
        depends_on_map = merge_pipeline_depends_on(pipelines_config, nodes_config)

        if not depends_on_map.get(pipeline_name):
            return self.run_pipeline(
                pipeline_name,
                node_name,
                start_date,
                end_date,
                model_version,
                hyperparams,
                execution_mode,
            )

        chain = PipelineDependencyResolver.resolve_execution_chain(
            pipeline_name, pipelines_config, depends_on_map
        )
        logger.info("Pipeline chain resolved: {}", " → ".join(chain))

        last_result: Union[None, str, Dict[str, Any]] = None
        for step, current_pipeline in enumerate(chain, 1):
            is_target = current_pipeline == pipeline_name

            # Skip an already-materialized ancestor when chain reuse is enabled.
            # Never applies to the target (the user asked for it explicitly) nor
            # to a single-node run, which has its own atomic read-from-disk path.
            if (
                not is_target
                and node_name is None
                and self._reuse_enabled_for(pipelines_config.get(current_pipeline, {}))
                and self._pipeline_is_up_to_date(current_pipeline, start_date, end_date)
            ):
                logger.info(
                    "[{}/{}] Reusing materialized '{}' (skip, up-to-date)",
                    step,
                    len(chain),
                    current_pipeline,
                )
                self.reused_pipelines.append(current_pipeline)
                continue

            logger.info("[{}/{}] Running pipeline '{}'", step, len(chain), current_pipeline)
            try:
                last_result = self.run_pipeline(
                    pipeline_name=current_pipeline,
                    node_name=node_name if is_target else None,
                    start_date=start_date,
                    end_date=end_date,
                    model_version=model_version if is_target else None,
                    hyperparams=hyperparams if is_target else None,
                    execution_mode=execution_mode,
                )
                logger.info("Pipeline '{}' completed successfully", current_pipeline)
            except Exception as e:
                remaining = chain[step:]
                msg = f"Pipeline chain failed at '{current_pipeline}' (step {step}/{len(chain)})."
                if remaining:
                    msg += f" Cancelled: {remaining}."
                raise RuntimeError(msg) from e

        return last_result

    # ── Chain-reuse: skip already-materialized upstream pipelines ────────────

    def _reuse_enabled_for(self, pipeline_cfg: Any) -> bool:
        """Whether chain reuse is enabled for a given ancestor pipeline.

        Precedence (highest first):
          1. ``--rerun-all``               → never reuse (force full chain).
          2. per-pipeline ``reuse_if_materialized: false`` → never reuse this
             pipeline (a correctness opt-out, e.g. ingestion that must refresh).
          3. ``--reuse-upstream``          → reuse.
          4. per-pipeline ``reuse_if_materialized: true`` → reuse.
          5. global ``[chain].reuse_materialized`` (default false).
        """
        if self._force_rerun_all:
            return False
        per_pipeline = self._get_pipeline_field(pipeline_cfg, "reuse_if_materialized")
        if per_pipeline is False:
            return False
        if self._force_reuse:
            return True
        if per_pipeline is True:
            return True
        return self._reuse_materialized_global

    @staticmethod
    def _get_pipeline_field(pipeline_cfg: Any, field: str) -> Any:
        """Read a field from a pipeline config (dict or schema), None if absent."""
        if isinstance(pipeline_cfg, dict):
            return pipeline_cfg.get(field)
        return getattr(pipeline_cfg, field, None)

    def _pipeline_is_up_to_date(
        self, pipeline_name: str, start_date: Optional[str], end_date: Optional[str]
    ) -> bool:
        """True if *pipeline_name* can be safely skipped as already materialized.

        Conservative by construction: any ambiguity (ineligible type, non-overwrite
        output, unresolved/absent output, stale input) returns False so the
        pipeline re-runs. See :meth:`_is_skip_eligible` for the guard rails.
        """
        try:
            pipeline = self.batch_executor._get_pipeline_config(pipeline_name)
        except Exception:
            return False

        if not self._is_skip_eligible(pipeline):
            return False

        # Date-parameterized pipelines: the materialized outputs are only valid
        # for the date range they were produced with. Require a recorded state
        # marker from a previous full run and matching dates; no marker → re-run.
        if pipeline.get("requires_dates", True):
            state = self._load_chain_state(pipeline_name)
            if not state:
                return False
            eff_start, eff_end = self._effective_dates(start_date, end_date)
            if state.get("start_date") != eff_start or state.get("end_date") != eff_end:
                return False

        out_keys = self._resolve_pipeline_output_keys(pipeline)
        if not out_keys:
            return False  # nothing to verify → re-run

        env = self._pipeline_env()
        output_manager = self.batch_executor.output_manager

        # ── Level 1: existence (always) ──
        for out_key in out_keys:
            if not output_manager.is_output_materialized(out_key, env):
                return False

        # ── Level 2: freshness (opt-in) ──
        if self._staleness_check:
            newest_input = self._max_pipeline_input_mtime(pipeline)
            if newest_input is not None:
                oldest_output = self._min_pipeline_output_mtime(out_keys, env)
                if oldest_output is None or oldest_output < newest_input:
                    return False

        return True

    def _is_skip_eligible(self, pipeline: Dict[str, Any]) -> bool:
        """Guard rails: only plain batch pipelines whose outputs all overwrite.

        Excludes ml/hybrid/streaming (models/state must stay fresh) and any
        pipeline with a non-``overwrite`` output (append/merge are cumulative —
        skipping would silently drop this run's delta).
        """
        pipeline_type = pipeline.get("type", PipelineType.BATCH.value)
        type_value = getattr(pipeline_type, "value", pipeline_type)
        if type_value != PipelineType.BATCH.value:
            return False

        output_config = getattr(self.context, "output_config", {}) or {}
        for out_key in self._resolve_pipeline_output_keys(pipeline):
            cfg = output_config.get(out_key, {}) or {}
            write_mode = cfg.get("write_mode", WriteMode.OVERWRITE.value)
            if getattr(write_mode, "value", write_mode) != WriteMode.OVERWRITE.value:
                return False
        return True

    def _resolve_pipeline_output_keys(self, pipeline: Dict[str, Any]) -> List[str]:
        """All output dataset keys declared across a pipeline's nodes."""
        nodes_config = getattr(self.context, "nodes_config", {}) or {}
        out_keys: List[str] = []
        seen: set = set()
        for node_name in extract_pipeline_nodes(pipeline):
            node_cfg = nodes_config.get(node_name, {}) or {}
            raw_out = node_cfg.get("output", [])
            if isinstance(raw_out, str):
                raw_out = [raw_out]
            elif isinstance(raw_out, dict):
                raw_out = list(raw_out.values())
            for key in raw_out or []:
                if isinstance(key, str) and key not in seen:
                    seen.add(key)
                    out_keys.append(key)
        return out_keys

    def _max_pipeline_input_mtime(self, pipeline: Dict[str, Any]) -> Optional[float]:
        """Newest input mtime across all nodes of a pipeline (None if no signal)."""
        nodes_config = getattr(self.context, "nodes_config", {}) or {}
        input_loader = self.batch_executor.input_loader
        newest: Optional[float] = None
        for node_name in extract_pipeline_nodes(pipeline):
            node_cfg = nodes_config.get(node_name, {}) or {}
            mtime = input_loader.max_input_mtime(node_cfg)
            if mtime is not None and (newest is None or mtime > newest):
                newest = mtime
        return newest

    def _min_pipeline_output_mtime(
        self, out_keys: List[str], env: Optional[str]
    ) -> Optional[float]:
        """Oldest output mtime across a pipeline's outputs (None if any missing)."""
        output_manager = self.batch_executor.output_manager
        oldest: Optional[float] = None
        for out_key in out_keys:
            mtime = output_manager.output_mtime(out_key, env)
            if mtime is None:
                return None
            if oldest is None or mtime < oldest:
                oldest = mtime
        return oldest

    def _pipeline_env(self) -> Optional[str]:
        """Resolve the active environment name for output-path resolution.

        Must mirror OutputWriter.save's resolution order (context.env first),
        so the reuse check looks at the same path the write used.
        """
        env = getattr(self.context, "env", None)
        if env:
            return env
        gs = getattr(self.context, "global_settings", {}) or {}
        return gs.get("env") or gs.get("environment") or getattr(self.context, "environment", None)

    # ── Chain-state markers: which dates a pipeline was last materialized with ──

    CHAIN_STATE_DIR = ".ducta/chain_state"

    def _chain_state_path(self, pipeline_name: str) -> Path:
        safe_name = pipeline_name.replace("/", "_")
        return Path(self.CHAIN_STATE_DIR) / f"{safe_name}.json"

    def _effective_dates(
        self, start_date: Optional[str], end_date: Optional[str]
    ) -> Tuple[Optional[str], Optional[str]]:
        """Dates as the executor resolves them (explicit args, else global settings)."""
        gs = getattr(self.context, "global_settings", {}) or {}
        eff_start = start_date or (gs.get("start_date") if isinstance(gs, dict) else None)
        eff_end = end_date or (gs.get("end_date") if isinstance(gs, dict) else None)
        return (
            str(eff_start) if eff_start is not None else None,
            str(eff_end) if eff_end is not None else None,
        )

    def _record_chain_state(
        self,
        pipeline_name: str,
        pipeline_type: Any,
        start_date: Optional[str],
        end_date: Optional[str],
    ) -> None:
        """Persist the date range a successful full-pipeline run used. Best-effort."""
        type_value = getattr(pipeline_type, "value", pipeline_type)
        if type_value != PipelineType.BATCH.value:
            return  # only batch pipelines are ever skip-eligible
        try:
            from datetime import datetime, timezone

            eff_start, eff_end = self._effective_dates(start_date, end_date)
            path = self._chain_state_path(pipeline_name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "pipeline": pipeline_name,
                        "start_date": eff_start,
                        "end_date": eff_end,
                        "recorded_at": datetime.now(timezone.utc).isoformat(),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        except Exception as e:  # noqa: BLE001 — bookkeeping must never break a run
            logger.debug("Could not record chain state for '{}': {}", pipeline_name, e)

    def _load_chain_state(self, pipeline_name: str) -> Optional[Dict[str, Any]]:
        """Read the chain-state marker for a pipeline; None when absent/corrupt."""
        try:
            path = self._chain_state_path(pipeline_name)
            if not path.exists():
                return None
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except Exception:  # noqa: BLE001
            return None

    def validate_pipeline(self, pipeline_name: str) -> bool:
        """Validate if a pipeline exists in the configuration.

        Args:
            pipeline_name: Name of the pipeline to validate

        Returns:
            True if the pipeline exists, False otherwise
        """
        return pipeline_name in self.context.pipelines

    def list_pipelines(self) -> List[str]:
        """List all available pipelines.

        Returns:
            List of pipeline names available in the configuration
        """
        return list(self.context.pipelines.keys())

    def get_pipeline_info(self, pipeline_name: str) -> Dict[str, Any]:
        """Get information about a specific pipeline."""
        if pipeline_name not in self.context.pipelines:
            return {
                "exists": False,
                "description": None,
                "nodes": [],
            }

        pipeline = self.context.pipelines[pipeline_name]

        nodes = []
        if isinstance(pipeline, dict):
            pipeline_nodes = pipeline.get("nodes", [])
            if isinstance(pipeline_nodes, dict):
                nodes = list(pipeline_nodes.keys())
            elif isinstance(pipeline_nodes, list):
                nodes = pipeline_nodes

        return {
            "exists": True,
            "description": pipeline.get("description", "") if isinstance(pipeline, dict) else None,
            "nodes": nodes,
        }

    def shutdown(self) -> None:
        """Unified shutdown with resource cleanup."""
        from concurrent.futures import ThreadPoolExecutor
        from concurrent.futures import TimeoutError as FutureTimeoutError

        shutdown_sequence = [
            (self._stop_streaming_queries, 5),
            (self._release_connection_pools, 10),
            (self._cleanup_memory, 20),
        ]

        for step, timeout in shutdown_sequence:
            # Built and torn down manually, not `with ThreadPoolExecutor(...)
            # as ex:` — that context manager's `__exit__` calls
            # `shutdown(wait=True)`, which would block here until a hung step
            # finishes on its own (Python cannot forcibly stop a running
            # thread), defeating the per-step timeout below: previously a
            # single stuck step could hang the whole `shutdown()` call well
            # past its advertised timeout budget.
            ex = ThreadPoolExecutor(max_workers=1)
            try:
                logger.info("Executing shutdown step: {} (timeout={}s)", step.__name__, timeout)
                ex.submit(step).result(timeout=timeout)
            except FutureTimeoutError:
                logger.warning("Shutdown step {} timed out after {}s", step.__name__, timeout)
            except Exception as e:
                logger.error("Shutdown error in {}: {}", step.__name__, e)
            finally:
                ex.shutdown(wait=False)

    def _stop_streaming_queries(self) -> None:
        """Stop active streaming queries if the manager supports it"""

        if self._streaming_executor is None:
            return
        try:
            # This will close MLflow run and stop streaming manager
            self.streaming_executor.shutdown()
        except Exception:
            pass

    def _release_connection_pools(self) -> None:
        """Release all database connections"""
        if hasattr(self.context, "connection_pools"):
            for pool in self.context.connection_pools.values():
                pool.shutdown()

    def _cleanup_memory(self) -> None:
        """Force memory cleanup"""
        gc.collect()
        # has_spark_session(), not getattr(context, "spark", None): the latter would
        # force a lazy session into existence here just to check, only to then clear
        # a cache it never populated.
        if self.context.has_spark_session():
            try:
                self.context.spark.catalog.clearCache()
            except Exception:
                pass
