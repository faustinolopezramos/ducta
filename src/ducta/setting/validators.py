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
