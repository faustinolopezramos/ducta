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

BatchExecutor: batch and ML pipelines.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from loguru import logger  # type: ignore

from ducta.core.dependency_resolver import DependencyResolver
from ducta.core.executors.base import BaseExecutor
from ducta.core.pipeline_validator import PipelineValidator
from ducta.core.utils import extract_pipeline_nodes
from ducta.stream.constants import PipelineType


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
        self._skipped_atomic_node = None
        self.node_executor.pipeline_name = pipeline_name
        self.node_executor.begin_run()
        pipeline = self._get_pipeline_config(pipeline_name)

        self._apply_global_seed()

        start_date = start_date or self.settings.start_date
        end_date = end_date or self.settings.end_date

        ml_info = self._build_ml_info(pipeline_name, model_version, hyperparams)
        ml_info["pipeline_type"] = pipeline.get("type", PipelineType.BATCH.value)

        self._log_pipeline_start(pipeline_name, ml_info, "BATCH")

        # No UnifiedPipelineState here. A batch run tracks its DAG in
        # ThreadSafeExecutionState (inside NodeExecutor); the UnifiedPipelineState
        # this used to build never had a single node registered in it and only
        # ever received set_pipeline_status/cleanup — a write-only status string
        # nobody read. Its real job (cross-type batch→streaming dependencies and
        # streaming query lifecycle) only exists in HybridExecutor.
        self.pipeline_status = "running"
        mlops_integration, mlops_run_id = self._start_mlops_integration(
            pipeline, pipeline_name, ml_info
        )

        self.node_executor.set_mlops_context(
            mlops_integration.mlops_context if mlops_integration else None
        )

        try:
            if mlops_integration and mlops_run_id:
                ml_info["mlops_integration"] = mlops_integration
                ml_info["mlops_run_id"] = mlops_run_id

            self._execute_batch_flow(pipeline, node_name, start_date, end_date, ml_info)
            self.pipeline_status = "completed"
            self._end_mlops_run(
                success=True, mlops_integration=mlops_integration, mlops_run_id=mlops_run_id
            )

        except Exception:
            self.pipeline_status = "failed"
            self._end_mlops_run(
                success=False, mlops_integration=mlops_integration, mlops_run_id=mlops_run_id
            )
            raise
        finally:
            from ducta.gate import handoff

            handoff.clear(self.context)

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

        sanity_reports = self._run_preflight_sanity_checks(node_configs, start_date, end_date)
        if sanity_reports:
            self._sanity_reports = sanity_reports

        dag = DependencyResolver.build_dependency_graph(pipeline_nodes, node_configs)
        execution_order = DependencyResolver.topological_sort(dag)

        self.node_executor.execute_nodes_parallel(
            execution_order, node_configs, dag, start_date, end_date, ml_info
        )

        self._aggregate_and_persist_quality_summary()
