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

import time
from typing import Any, Dict, Optional

from loguru import logger  # type: ignore

from ducta.check import QualityOutputManager
from ducta.core.execution.runner import NodeExecutor
from ducta.core.settings import CoreSettings
from ducta.mlrun.mlflow import MLflowPipelineTracker, is_mlflow_available


class MLflowNodeExecutor(NodeExecutor):
    """NodeExecutor with MLflow integration."""

    def __init__(
        self,
        context,
        input_loader,
        output_manager,
        mlflow_tracker: Optional[MLflowPipelineTracker] = None,
        max_workers: int = 4,
        enable_mlflow: bool = True,
        mlops_context: Optional[Any] = None,
        quality_output_manager: Optional[QualityOutputManager] = None,
        settings: Optional[CoreSettings] = None,
    ):
        """
        Initialize MLflow Node Executor.
        """
        super().__init__(
            context,
            input_loader,
            output_manager,
            max_workers,
            mlops_context=mlops_context,
            quality_output_manager=quality_output_manager,
            settings=settings,
        )

        self.enable_mlflow = enable_mlflow and is_mlflow_available()
        self.mlflow_tracker = mlflow_tracker

        if self.enable_mlflow and not self.mlflow_tracker:
            try:
                self.mlflow_tracker = MLflowPipelineTracker.from_context(context)
                logger.info("Created MLflow tracker from context")
            except Exception as e:
                logger.warning(f"Could not create MLflow tracker: {e}")
                self.enable_mlflow = False

    def execute_single_node(
        self,
        node_name: str,
        start_date: str,
        end_date: str,
        ml_info: Dict[str, Any],
    ) -> None:
        """
        Execute single node with MLflow step tracking.
        """
        if not self.enable_mlflow or not self.mlflow_tracker:
            return super().execute_single_node(node_name, start_date, end_date, ml_info)

        node_config = self._get_node_config(node_name)
        node_params = {
            "start_date": start_date,
            "end_date": end_date,
            "node_type": node_config.get("type", "batch"),
            "module": node_config.get("module", "unknown"),
            "function": node_config.get("function", "unknown"),
        }

        if "model_version" in ml_info:
            node_params["model_version"] = ml_info["model_version"]

        if "hyperparams" in ml_info:
            for key, value in ml_info["hyperparams"].items():
                node_params[f"hyperparam_{key}"] = value

        with self.mlflow_tracker.start_node_step(
            node_name=node_name,
            parameters=node_params,
        ) as node_run_id:
            logger.info(
                f"Executing node '{node_name}' with MLflow tracking (run_id: {node_run_id})"
            )

            node_ml_info = dict(ml_info)
            node_ml_info["mlflow_run_id"] = node_run_id
            node_ml_info["mlflow_tracker"] = self.mlflow_tracker

            try:
                start_time = time.perf_counter()
                super().execute_single_node(node_name, start_date, end_date, node_ml_info)
                duration = time.perf_counter() - start_time

                self.mlflow_tracker.log_node_metric(
                    "execution_time_seconds", duration, node_name=node_name
                )
                self.mlflow_tracker.log_node_metric("success", 1.0, node_name=node_name)

                logger.info(
                    f"Node '{node_name}' completed successfully (duration: {duration:.2f}s)"
                )

            except Exception as e:
                self.mlflow_tracker.log_node_param(
                    "error_type", type(e).__name__, node_name=node_name
                )
                self.mlflow_tracker.log_node_param("error_message", str(e), node_name=node_name)
                self.mlflow_tracker.log_node_metric("success", 0.0, node_name=node_name)

                logger.error(f"Node '{node_name}' failed: {e}")
                raise

    def execute_nodes_parallel(
        self,
        execution_order: list,
        node_configs: Dict[str, Dict[str, Any]],
        dag: Dict[str, set],
        start_date: str,
        end_date: str,
        ml_info: Dict[str, Any],
    ) -> None:
        """
        Execute nodes in parallel with MLflow tracking.
        """
        if not self.enable_mlflow or not self.mlflow_tracker:
            return super().execute_nodes_parallel(
                execution_order, node_configs, dag, start_date, end_date, ml_info
            )

        self.mlflow_tracker.log_pipeline_metric("total_nodes", len(execution_order))
        self.mlflow_tracker.log_pipeline_metric("parallel_workers", self.max_workers)

        try:
            super().execute_nodes_parallel(
                execution_order, node_configs, dag, start_date, end_date, ml_info
            )

            self.mlflow_tracker.log_pipeline_metric("pipeline_success", 1.0)

        except Exception:
            self.mlflow_tracker.log_pipeline_metric("pipeline_success", 0.0)
            raise


def create_mlflow_executor(
    context,
    input_loader,
    output_manager,
    mlflow_config: Optional[Dict[str, Any]] = None,
    max_workers: int = 4,
) -> NodeExecutor:
    """
    Factory function to create an MLflow-enabled executor.
    """
    if not is_mlflow_available():
        logger.warning("MLflow not available, falling back to standard executor")
        return NodeExecutor(context, input_loader, output_manager, max_workers)

    tracker = None
    if mlflow_config:
        tracker = MLflowPipelineTracker(
            experiment_name=mlflow_config.get("experiment_name", "Ducta_pipeline"),
            tracking_uri=mlflow_config.get("tracking_uri"),
            artifact_location=mlflow_config.get("artifact_location"),
            enable_autolog=mlflow_config.get("enable_autolog", True),
            nested_runs=mlflow_config.get("nested_runs", True),
            tags=mlflow_config.get("tags"),
        )

    return MLflowNodeExecutor(
        context=context,
        input_loader=input_loader,
        output_manager=output_manager,
        mlflow_tracker=tracker,
        max_workers=max_workers,
        enable_mlflow=True,
    )
