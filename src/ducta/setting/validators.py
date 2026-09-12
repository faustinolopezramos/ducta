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

from typing import Any, Dict, List, Optional

from loguru import logger  # type: ignore

from ducta.setting.exceptions import ConfigValidationError, PipelineValidationError


class ConfigValidator:
    """Validator for configuration data structure and types."""

    @staticmethod
    def validate_required_keys(
        config: Dict[str, Any],
        required_keys: List[str],
        config_name: str = "configuration",
    ) -> None:
        """Validate that all required keys exist in config."""
        missing_keys = [key for key in required_keys if key not in config]
        if missing_keys:
            available_keys = list(config.keys())[:10]
            raise ConfigValidationError(
                f"Missing required keys in {config_name}: {', '.join(missing_keys)}\n"
                f"Available keys: {', '.join(available_keys)}"
                f"{'...' if len(config) > 10 else ''}"
            )

    @staticmethod
    def validate_type(config: Any, expected_type: type, config_name: str = "configuration") -> None:
        """Validate that config is of expected type."""
        if not isinstance(config, expected_type):
            raise ConfigValidationError(
                f"{config_name} must be of type {expected_type.__name__}, got {type(config).__name__}"
            )


class PipelineValidator(ConfigValidator):
    """Validator for pipeline configurations."""

    @staticmethod
    def validate_pipeline_nodes(pipelines: Dict[str, Any], nodes_config: Dict[str, Any]) -> None:
        """Validate that all pipeline nodes exist and are not empty in nodes_config."""
        missing_nodes = []
        empty_nodes = []
        for pipeline_name, pipeline in pipelines.items():
            for node in pipeline.get("nodes", []):
                if node not in nodes_config:
                    missing_nodes.append(f"{node} (in pipeline '{pipeline_name}')")
                elif nodes_config[node] is None:
                    empty_nodes.append(f"{node} (in pipeline '{pipeline_name}')")

        error_msg = []
        if missing_nodes:
            error_msg.append(f"Missing nodes: {', '.join(missing_nodes)}")
        if empty_nodes:
            error_msg.append(
                f"Nodes with missing/empty content: {', '.join(empty_nodes)}. "
                "Check your nodes.yml for empty definitions."
            )

        if error_msg:
            raise PipelineValidationError("\n".join(error_msg))

    @staticmethod
    def validate_pipeline_dependency_graph(
        pipelines: Dict[str, Any], nodes: Optional[Dict[str, Any]] = None
    ) -> None:
        """Validate inter-pipeline depends_on declarations."""
        try:
            from ducta.setting.pipeline_dependency_resolver import PipelineDependencyResolver

            depends_on_map = None
            if nodes is not None:
                from ducta.setting.dependency_inference import merge_pipeline_depends_on

                depends_on_map = merge_pipeline_depends_on(pipelines, nodes)

            PipelineDependencyResolver.validate_pipeline_dependencies(pipelines, depends_on_map)
        except ValueError as exc:
            raise PipelineValidationError(str(exc)) from exc


class FormatPolicy:
    """
    Centralizes supported formats and compatibility rules between batch and streaming pipelines,
    enabling overrides from configuration.
    """

    DEFAULT_SUPPORTED_INPUTS = [
        "kafka",
        "kinesis",
        "delta",
        "delta_stream",
        "file_stream",
        "socket",
        "rate",
        "memory",
    ]

    DEFAULT_SUPPORTED_OUTPUTS = [
        "kafka",
        "memory",
        "console",
        "delta",
        "parquet",
        "json",
        "csv",
    ]

    DEFAULT_COMPATIBILITY_MAP = {
        "parquet": ["file_stream"],
        "delta": ["delta", "delta_stream"],  # or "file_stream" if file-based reading is preferred
        "json": ["file_stream"],
        "csv": ["file_stream"],
        "kafka": ["kafka"],
    }

    DEFAULT_CHECKPOINT_REQUIRED_INPUTS = ["kafka", "kinesis", "delta", "delta_stream"]

    def __init__(self, overrides: Optional[Dict[str, Any]] = None):
        overrides = overrides or {}
        self.supported_inputs = overrides.get("supported_inputs", self.DEFAULT_SUPPORTED_INPUTS)
        self.supported_outputs = overrides.get("supported_outputs", self.DEFAULT_SUPPORTED_OUTPUTS)
        self.compatibility_map = overrides.get("compatibility_map", self.DEFAULT_COMPATIBILITY_MAP)
        self.checkpoint_required_inputs = overrides.get(
            "checkpoint_required_inputs", self.DEFAULT_CHECKPOINT_REQUIRED_INPUTS
        )

    def is_supported_input(self, fmt: Optional[str]) -> bool:
        return bool(fmt) and fmt in self.supported_inputs

    def is_supported_output(self, fmt: Optional[str]) -> bool:
        return bool(fmt) and fmt in self.supported_outputs

    def are_compatible(
        self, batch_output_fmt: Optional[str], streaming_input_fmt: Optional[str]
    ) -> bool:
        if not batch_output_fmt or not streaming_input_fmt:
            return False
        allowed = self.compatibility_map.get(batch_output_fmt, [])
        return streaming_input_fmt in allowed

    def get_supported_input_formats(self) -> List[str]:
        return list(self.supported_inputs)

    def get_supported_output_formats(self) -> List[str]:
        return list(self.supported_outputs)


class SpecializedValidator(ConfigValidator):
    """Base class for specialized validators (ML, Streaming)."""

    REQUIRED_NODE_FIELDS: List[str] = []
    SUPPORTED_MODEL_TYPES: List[str] = []

    @staticmethod
    def _assert_node_exists(
        node_name: str, pipeline_name: str, nodes_config: Dict[str, Any]
    ) -> None:
        if node_name not in nodes_config:
            raise ConfigValidationError(
                f"Node '{node_name}' in pipeline '{pipeline_name}' "
                f"is not defined in global nodes configuration"
            )

    @staticmethod
    def _raise_or_warn(msg: str, strict: bool) -> None:
        """Raise ConfigValidationError if strict, otherwise log warning."""
        if strict:
            raise ConfigValidationError(msg)
        logger.warning(msg)

    def _validate_node_config(
        self, node_config: Dict[str, Any], node_name: str, *, strict: bool = True
    ) -> None:
        """Template method for node configuration validation."""
        self._validate_required_fields(node_config, node_name, strict=strict)
        self._validate_model_type(node_config, node_name, strict=strict)
        self._validate_hyperparams(node_config, node_name, strict=strict)
        self._validate_metrics(node_config, node_name, strict=strict)

    def _validate_required_fields(
        self, node_config: Dict[str, Any], node_name: str, *, strict: bool = True
    ) -> None:
        """Validate required fields exist."""
        if not self.REQUIRED_NODE_FIELDS:
            return
        missing_fields = [f for f in self.REQUIRED_NODE_FIELDS if f not in node_config]
        if missing_fields:
            msg = f"Node '{node_name}' is missing required fields: {', '.join(missing_fields)}"
            self._raise_or_warn(msg, strict)

    def _validate_model_type(
        self, node_config: Dict[str, Any], node_name: str, *, strict: bool = True
    ) -> None:
        """Validate model type is supported."""
        if not self.SUPPORTED_MODEL_TYPES:
            return
        model_config = node_config.get("model", {})
        model_type = model_config.get("type")
        if model_type and model_type not in self.SUPPORTED_MODEL_TYPES:
            msg = (
                f"Node '{node_name}' has unsupported model type: {model_type}. "
                f"Supported: {', '.join(self.SUPPORTED_MODEL_TYPES)}"
            )
            self._raise_or_warn(msg, strict)

    def _validate_hyperparams(
        self, node_config: Dict[str, Any], node_name: str, *, strict: bool = True
    ) -> None:
        """Validate hyperparameters format."""
        hyperparams = node_config.get("hyperparams", {})
        if hyperparams and not isinstance(hyperparams, dict):
            msg = f"Node '{node_name}' has invalid hyperparams format; expected dict, got {type(hyperparams).__name__}"
            self._raise_or_warn(msg, strict)

    def _validate_metrics(
        self, node_config: Dict[str, Any], node_name: str, *, strict: bool = True
    ) -> None:
        """Validate metrics format."""
        metrics = node_config.get("metrics", [])
        if metrics and not isinstance(metrics, list):
            msg = f"Node '{node_name}' has invalid metrics format; expected list, got {type(metrics).__name__}"
            self._raise_or_warn(msg, strict)


class CrossValidator:
    """Cross-validation for dependencies between different types of nodes."""

    @staticmethod
    def _get_node_type(config: dict, policy: Optional["FormatPolicy"] = None) -> str:
        """Infer node type from its configuration."""
        if "model" in config:
            return "ml"
        _policy = policy or FormatPolicy()
        input_cfg = config.get("input", {})
        if isinstance(input_cfg, dict):
            fmt = input_cfg.get("format", "")
            if _policy.is_supported_input(fmt):
                return "streaming"
        return "batch"

    @staticmethod
    def _check_ml_node_dependency(
        node_name: str,
        dep_name: str,
        dep_config: dict,
        errors: List[str],
        policy: Optional["FormatPolicy"] = None,
    ) -> None:
        if CrossValidator._get_node_type(dep_config, policy) == "streaming":
            output_format = dep_config.get("output", {}).get("format")
            if output_format not in ["delta", "parquet"]:
                errors.append(
                    f"ML node '{node_name}' requires delta/parquet output from streaming node '{dep_name}', got {output_format}"
                )

    @staticmethod
    def _check_streaming_node_dependency(
        node_name: str,
        dep_name: str,
        dep_config: dict,
        errors: List[str],
        policy: Optional["FormatPolicy"] = None,
    ) -> None:
        if CrossValidator._get_node_type(dep_config, policy) == "ml":
            model_type = dep_config.get("model", {}).get("type")
            if model_type != "spark_ml":
                errors.append(
                    f"Streaming node '{node_name}' requires spark_ml model from ML node '{dep_name}', got {model_type}"
                )

    @staticmethod
    def validate_hybrid_dependencies(
        nodes_config: dict, policy: Optional["FormatPolicy"] = None
    ) -> None:
        """Validate cross-type node dependencies."""
        errors: List[str] = []

        for node_name, config in nodes_config.items():
            deps = config.get("dependencies", [])
            node_type = CrossValidator._get_node_type(config, policy)
            for dep in deps:
                dep_config = nodes_config.get(dep, {})
                if node_type == "ml":
                    CrossValidator._check_ml_node_dependency(
                        node_name, dep, dep_config, errors, policy
                    )
                elif node_type == "streaming":
                    CrossValidator._check_streaming_node_dependency(
                        node_name, dep, dep_config, errors, policy
                    )

        if errors:
            raise ConfigValidationError("\n".join(errors))
