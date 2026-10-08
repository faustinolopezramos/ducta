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
from typing import Any, Callable, Dict, List, Optional

from ducta.core.commands import Command, MLNodeCommand, NodeCommand


class MLContextBuilder:
    """Builds ML commands and prepares per-node ML metadata."""

    def __init__(self, context: Any, mlops_context: Optional[Any], is_ml_layer: bool) -> None:
        self.context = context
        self.mlops_context = mlops_context
        self.is_ml_layer = is_ml_layer
        self._models: Optional[Any] = None
        # Parallel nodes reach serving_model at once; one cache per run is what
        # pins a stage to a single version for the whole run.
        self._models_lock = threading.Lock()

    def reset_models(self) -> None:
        """Forget the previous run's models (an executor can serve several runs)."""
        with self._models_lock:
            self._models = None

    def serving_model(self, node_config: Dict[str, Any]) -> Optional[Any]:
        """The node's ``model:``, resolved and loaded once per run (None without one)."""
        ref = (node_config or {}).get("model")
        if not ref:
            return None
        with self._models_lock:
            if self._models is None:
                from ducta.mlrun.serving import model_cache_for

                self._models = model_cache_for(self.context, self._model_registry)
            models = self._models
        return models.get(ref)

    def _model_registry(self) -> Any:
        """The registry the run's MLOps context uses, or the project's own."""
        registry = getattr(self.mlops_context, "model_registry", None)
        if registry is not None:
            return registry
        from ducta.mlrun.config import MLOpsContext

        return MLOpsContext.from_context(self.context).model_registry

    def is_ml_node(self, node_config: Dict[str, Any], ml_info: Dict[str, Any]) -> bool:
        """Decide whether a node must receive the ML context."""
        from ducta.core.mlops_auto_config import MLOpsAutoConfigurator

        return (
            bool(MLOpsAutoConfigurator.resolve_ml_stage(node_config))
            or self.is_ml_layer
            or ml_info.get("pipeline_type") == "ml"
            or ml_info.get("split") is not None
            or bool((node_config or {}).get("split"))
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
            "cli_hyperparams": ml_info.get("cli_hyperparams"),
            "model_ref": self.serving_model(node_config),
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

        from ducta.core.ml_contract import effective_split

        node_ml_config = self.context.get_node_ml_config(node_name)
        enhanced_ml_info = ml_info.copy()

        # Precedence, lowest first: pipeline < node < this run's CLI overrides.
        # Idempotent: the coordinator prepares a node and execute_single_node prepares
        # it again (it is the one path every run mode shares), with the same result.
        node_hyperparams = dict(enhanced_ml_info.get("hyperparams") or {})
        node_hyperparams.update(node_ml_config.get("hyperparams") or {})
        node_hyperparams.update(ml_info.get("cli_hyperparams") or {})
        enhanced_ml_info["hyperparams"] = node_hyperparams

        if ml_info.get("cli_model_version") is not None:
            enhanced_ml_info["model_version"] = ml_info["cli_model_version"]
        elif node_ml_config.get("model_version") is not None:
            enhanced_ml_info["model_version"] = node_ml_config["model_version"]

        pipeline_split = ml_info.get("pipeline_split", ml_info.get("split"))
        split, source = effective_split(node_config, pipeline_split)
        enhanced_ml_info["pipeline_split"] = pipeline_split
        enhanced_ml_info["split"] = split
        enhanced_ml_info["split_source"] = source
        enhanced_ml_info["node_config"] = node_ml_config

        return enhanced_ml_info
