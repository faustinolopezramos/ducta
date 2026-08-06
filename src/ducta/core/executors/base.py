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

BaseExecutor: what every pipeline type shares — settings, MLOps wiring, ml_info, quality aggregation.
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger  # type: ignore

from ducta.check import (
    QualityOutputManager,
    QualityReport,
    QualityReporter,
    SanityPhaseRunner,
)
from ducta.core.errors import MLOpsRequiredError, PipelineNotFoundError
from ducta.core.execution.runner import NodeExecutor
from ducta.core.mlops_auto_config import MLOpsAutoConfigurator
from ducta.core.mlops_integration import MLOpsExecutorIntegration
from ducta.core.pipeline_state import UnifiedPipelineState
from ducta.core.settings import (
    DEFAULT_EXECUTION_TIMEOUT_SECONDS,
    MAX_TIMEOUT_SECONDS,
    CoreSettings,
)
from ducta.core.split_validator import document_split_semantics
from ducta.gate.input import InputLoader
from ducta.gate.output import DataOutputManager
from ducta.setting.contexts import Context
from ducta.stream.constants import PipelineType

try:
    from ducta.core.mlflow_node_executor import MLflowNodeExecutor
    from ducta.mlrun.mlflow import MLflowPipelineTracker

    MLFLOW_INTEGRATION_AVAILABLE = True
except ImportError:
    MLFLOW_INTEGRATION_AVAILABLE = False
    MLflowNodeExecutor = None
    MLflowPipelineTracker = None


class _MLOpsRequiredError(Exception):
    """Internal sentinel: MLOps unavailability that must abort the pipeline
    because ``mlops_required`` is set. Caught and re-raised as a RuntimeError
    with a clear message by the caller — never meant to escape this module."""


class BaseExecutor:
    """Base class for pipeline executors."""

    DEFAULT_TIMEOUT_SECONDS = DEFAULT_EXECUTION_TIMEOUT_SECONDS
    MAX_TIMEOUT_SECONDS = MAX_TIMEOUT_SECONDS

    def __init__(self, context: Context, settings: Optional[CoreSettings] = None):
        self.context = context
        # Resolved once, here. Coercion, defaults and clamping live in
        # CoreSettings, so no execution path below re-reads global_settings with
        # its own inline default.
        self.settings = settings or CoreSettings.from_context(context)

        self._mlops_context = None
        self._mlops_auto_config = MLOpsAutoConfigurator()
        self._mlops_init_attempted = False
        self._mlops_pipeline_name: Optional[str] = None

        self.input_loader = InputLoader(self.context)
        self.output_manager = DataOutputManager(self.context)
        self.quality_output_manager = QualityOutputManager(self.context)
        self.is_ml_layer = getattr(self.context, "is_ml_layer", False)
        self.max_workers = self.settings.max_parallel_nodes
        self.timeout_seconds = self.settings.execution_timeout_seconds

        self._mlflow_enabled = self._should_enable_mlflow()
        self._mlflow_required = self.settings.mlops_required
        self._mlflow_tracker = None
        self.node_executor = self._build_node_executor()

        # Only HybridExecutor builds one (cross-type dependency tracking +
        # streaming query lifecycle); batch and streaming leave it None.
        self.unified_state: Optional[UnifiedPipelineState] = None
        self.pipeline_status: str = "initializing"
        self._sanity_reports: Dict[str, QualityReport] = {}
        self._skipped_atomic_node: Optional[Dict[str, str]] = None

    def _build_node_executor(self):
        """Build the node executor, with MLflow tracking when it is available.

        The plain ``NodeExecutor`` construction used to appear twice — once as
        the MLflow fallback and once as the default — so its seven arguments had
        to be kept in step by hand across two branches.
        """

        def _plain() -> NodeExecutor:
            return NodeExecutor(
                self.context,
                self.input_loader,
                self.output_manager,
                self.max_workers,
                mlops_context=None,
                quality_output_manager=self.quality_output_manager,
                settings=self.settings,
            )

        if not (self._mlflow_enabled and MLFLOW_INTEGRATION_AVAILABLE):
            return _plain()

        try:
            self._mlflow_tracker = MLflowPipelineTracker.from_context(self.context)
            executor = MLflowNodeExecutor(
                self.context,
                self.input_loader,
                self.output_manager,
                self._mlflow_tracker,
                self.max_workers,
                mlops_context=None,
                quality_output_manager=self.quality_output_manager,
                settings=self.settings,
            )
            logger.info("MLflow integration enabled for pipeline execution")
            return executor
        except Exception as e:
            if self._mlflow_required:
                raise MLOpsRequiredError(f"MLflow initialization failed: {e}") from e
            logger.warning("Could not enable MLflow: {}. Falling back to standard executor.", e)
            self._mlflow_tracker = None
            return _plain()

    def _should_enable_mlflow(self) -> bool:
        """Whether MLflow tracking should be wired in for this run.

        The environment-variable override now lives in ``CoreSettings`` with
        every other setting, instead of being read here with its own parsing.
        """
        if not MLFLOW_INTEGRATION_AVAILABLE:
            return False
        return self.settings.mlflow_enabled

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
                raise MLOpsRequiredError(str(e)) from e
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
        return self.settings.random_seed

    def _apply_global_seed(self) -> None:
        """Seed the process-wide RNGs for reproducibility. Best-effort.

        Lives on BaseExecutor so every executor gets it: it used to be inlined
        in BatchExecutor.execute only, which left hybrid ML runs unseeded (and
        therefore irreproducible) for no reason other than where the code sat.
        """
        seed = self._resolve_global_seed()
        if seed is None:
            return

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
            raise PipelineNotFoundError(pipeline_name, list(self.context.pipelines))
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

            for report_type, outputs in outputs_by_type.items():
                logger.info(f"  {report_type}: {len(outputs)} reports")

            summary_config = self.settings.quality.get("global_summary", {})

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
    ) -> Dict[str, QualityReport]:
        has_sanity_checks = any(
            (nc.get("sanity_checks") or {}).get("enabled", True)
            for nc in node_configs.values()
            if nc.get("sanity_checks")
        )

        if not has_sanity_checks:
            logger.debug("No preflight sanity checks configured for this pipeline")
            return {}

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

        if not self.settings.mlops_enabled:
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
                    "env": str(self.settings.env or ""),
                    "execution_mode": str(getattr(self.context, "execution_mode", "")),
                }
                if self.settings.project_id:
                    run_tags["project_id"] = str(self.settings.project_id)
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
            raise MLOpsRequiredError(f"experiment tracking unavailable: {e}") from e
        except Exception as e:
            if self._mlflow_required:
                raise MLOpsRequiredError(f"integration initialization failed: {e}") from e
            logger.warning(
                f"MLOps integration initialization failed: {e}. "
                f"Pipeline will execute without experiment tracking."
            )
            mlops_integration = None
            mlops_run_id = None

        return mlops_integration, mlops_run_id
