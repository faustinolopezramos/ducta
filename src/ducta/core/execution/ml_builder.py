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

from typing import Any, Callable, Dict, List, Optional

from ducta.core.commands import Command, MLNodeCommand, NodeCommand


class MLContextBuilder:
    """Builds ML commands and prepares per-node ML metadata."""

    def __init__(self, context: Any, mlops_context: Optional[Any], is_ml_layer: bool) -> None:
        self.context = context
        self.mlops_context = mlops_context
        self.is_ml_layer = is_ml_layer

    def is_ml_node(self, node_config: Dict[str, Any], ml_info: Dict[str, Any]) -> bool:
        """Decide whether a node must receive the ML context."""
        from ducta.core.mlops_auto_config import MLOpsAutoConfigurator

        return (
            bool(MLOpsAutoConfigurator.resolve_ml_stage(node_config))
            or self.is_ml_layer
            or ml_info.get("pipeline_type") == "ml"
            or ml_info.get("split") is not None
        )

    def create_command(
        self,
        function: Callable,
        input_dfs: List[Any],
        start_date: str,
        end_date: str,
        node_name: str,
        ml_info: Dict[str, Any],
        node_config: Dict[str, Any],
        input_names: Optional[List[str]] = None,
    ) -> Command:
        """Create appropriate command based on ML stage or layer type."""
        if self.is_ml_node(node_config, ml_info):
            return self._create_ml_command(
                function,
                input_dfs,
                start_date,
                end_date,
                node_name,
                ml_info,
                node_config,
                input_names,
            )
        return NodeCommand(
            function=function,
            input_dfs=input_dfs,
            start_date=start_date,
            end_date=end_date,
            node_name=node_name,
            node_config=node_config,
            input_names=input_names,
        )

    def _create_ml_command(
        self,
        function: Callable,
        input_dfs: List[Any],
        start_date: str,
        end_date: str,
        node_name: str,
        ml_info: Dict[str, Any],
        node_config: Dict[str, Any],
        input_names: Optional[List[str]] = None,
    ) -> Command:
        """Create ML command (either standard or experiment)."""
        common_params = {
            "function": function,
            "input_dfs": input_dfs,
            "start_date": start_date,
            "end_date": end_date,
            "node_name": node_name,
            "model_version": ml_info.get("model_version"),
            "hyperparams": ml_info.get("hyperparams", {}),
            "hyperparams_config": ml_info.get("hyperparams_config"),
            "node_config": node_config,
            "pipeline_config": ml_info.get("pipeline_config", {}),
            "mlops_context": self.mlops_context,
            "mlops_run_id": ml_info.get("mlops_run_id"),
            "seed": ml_info.get("seed"),
            "split": ml_info.get("split"),
            "cv_folds": ml_info.get("cv_folds"),
            "input_names": input_names,
        }

        if hasattr(self.context, "spark"):
            common_params["spark"] = self.context.spark

        return MLNodeCommand(**common_params)

    def prepare_node_ml_info(self, node_name: str, ml_info: Dict[str, Any]) -> Dict[str, Any]:
        """Prepare node-specific ML information."""
        node_config = self.context.nodes_config.get(node_name, {}) or {}
        if not self.is_ml_node(node_config, ml_info):
            copied = dict(ml_info)
            if isinstance(ml_info.get("hyperparams"), dict):
                copied["hyperparams"] = dict(ml_info["hyperparams"])
            return copied

        node_ml_config = self.context.get_node_ml_config(node_name)
        enhanced_ml_info = ml_info.copy()
        node_hyperparams = enhanced_ml_info.get("hyperparams", {}).copy()
        node_hyperparams.update(node_ml_config.get("hyperparams", {}))
        enhanced_ml_info["hyperparams"] = node_hyperparams
        enhanced_ml_info["node_config"] = node_ml_config

        return enhanced_ml_info
