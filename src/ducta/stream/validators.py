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

import re
from collections import deque
from typing import Any, Dict, List, Optional, Set

from loguru import logger  # type: ignore

from ducta.setting.dependency_inference import get_node_dependencies
from ducta.stream.constants import (
    STREAMING_FORMAT_CONFIGS,
    STREAMING_VALIDATIONS,
    PipelineType,
    StreamingFormat,
    StreamingOutputMode,
    StreamingTrigger,
)
from ducta.stream.exceptions import StreamingValidationError, handle_streaming_error

# Common field name constants
INPUT_OPTIONS_FIELD = "input.options"
NON_EMPTY_STRING = "non-empty string"
TRIGGER_INTERVAL_FIELD = "streaming.trigger.interval"
DEFAULT_SUPPORTED_OUTPUT_FORMATS = ["console", "delta", "parquet", "kafka", "json", "csv"]
ALLOWED_FILE_FORMATS = {"parquet", "json", "csv", "orc", "text", "avro"}
RESERVED_OUTPUT_KEYS = {"trigger", "outputMode", "checkpointLocation", "queryName"}


class StreamingValidator:
    """Validates streaming pipeline configurations with enhanced error handling."""

    def __init__(
        self,
        format_policy: Optional[Any] = None,
        max_batch_nodes: int = 10,
        max_streaming_nodes: int = 5,
    ) -> None:
        """
        format_policy is optional. If provided, it will be used to validate input/output formats
        (e.g., Context.format_policy). Otherwise, default enums/constants are used.
        """
        self.policy = format_policy
        self.max_batch_nodes = max_batch_nodes
        self.max_streaming_nodes = max_streaming_nodes

    @handle_streaming_error
    def validate_streaming_pipeline_config(self, pipeline_config: Dict[str, Any]) -> None:
        """Validate streaming pipeline configuration with comprehensive checks."""
        self._ensure_pipeline_is_dict(pipeline_config)

        pipeline_type = pipeline_config.get("type", PipelineType.STREAMING.value)
        self._ensure_valid_pipeline_type(pipeline_type)

        nodes = pipeline_config.get("nodes", [])
        self._ensure_nodes_list(nodes)

        for i, node in enumerate(nodes):
            self._validate_node_entry(i, node)

        streaming_config = pipeline_config.get("streaming", {})
        if streaming_config:
            self._validate_pipeline_streaming_config(streaming_config)

        satisfied = set(pipeline_config.get("satisfied_dependencies") or ())
        self._validate_pipeline_dependencies(nodes, satisfied_dependencies=satisfied)
        logger.info("Streaming pipeline configuration validated successfully")

    def _ensure_pipeline_is_dict(self, pipeline_config: Any) -> None:
        if not isinstance(pipeline_config, dict):
            raise StreamingValidationError(
                "Pipeline configuration must be a dictionary",
                expected="dict",
                actual=str(type(pipeline_config)),
            )

    def _ensure_valid_pipeline_type(self, pipeline_type: Any) -> None:
        valid_types = [PipelineType.STREAMING.value, PipelineType.HYBRID.value]
        if pipeline_type not in valid_types:
            raise StreamingValidationError(
                f"Pipeline type must be one of {valid_types} for streaming pipelines",
                field="type",
                expected=str(valid_types),
                actual=pipeline_type,
            )

    def _ensure_nodes_list(self, nodes: Any) -> None:
        if not nodes:
            raise StreamingValidationError(
                "Streaming pipeline must have at least one node", field="nodes"
            )
        if not isinstance(nodes, list):
            raise StreamingValidationError(
                "Pipeline nodes must be a list",
                field="nodes",
                expected="list",
                actual=str(type(nodes)),
            )

    def _validate_node_entry(self, index: int, node: Any) -> None:
        try:
            if isinstance(node, dict):
                self.validate_streaming_node_config(node)
            elif isinstance(node, str):
                # Node reference - basic validation
                if not node.strip():
                    raise StreamingValidationError(
                        f"Node reference at index {index} cannot be empty string"
                    )
            else:
                raise StreamingValidationError(
                    f"Invalid node configuration at index {index}",
                    expected="dict or str",
                    actual=str(type(node)),
                )
        except StreamingValidationError as e:
            # Add context about which node failed
            e.add_context("node_index", index)
            e.add_context("node_type", type(node).__name__)
            raise

    @handle_streaming_error
    def validate_streaming_node_config(self, node_config: Dict[str, Any]) -> None:
        """Validate streaming node configuration with modular validation approach."""
        if not isinstance(node_config, dict):
            raise StreamingValidationError(
                "Node configuration must be a dictionary",
                expected="dict",
                actual=str(type(node_config)),
            )

        node_name = node_config.get("name", "unknown")
        self._validate_node_structure(node_config, node_name)
        self._validate_node_io_config(node_config, node_name)
        self._validate_node_streaming_config(node_config, node_name)
        self._validate_node_function_config(node_config, node_name)

    def _validate_node_structure(self, node_config: Dict[str, Any], node_name: str) -> None:
        """Validate basic node structure (Phase 1)."""
        # Accept either singular or plural forms (normalized or raw TOML)
        has_input = "input" in node_config or "inputs" in node_config
        has_output = "output" in node_config or "outputs" in node_config

        missing_fields = []
        if not has_input:
            missing_fields.append("input/inputs")
        if not has_output:
            missing_fields.append("output/outputs")

        if missing_fields:
            raise StreamingValidationError(
                f"Node '{node_name}' missing required fields: {missing_fields}",
                field="required_fields",
                expected="input/inputs and output/outputs",
                actual=str(list(node_config.keys())),
            )

    def _validate_node_io_config(self, node_config: Dict[str, Any], node_name: str) -> None:
        """Validate input/output configuration (Phase 2)."""
        try:
            # ── Input Validation ──────────────────────────────────────────────
            input_val = node_config.get("input")
            inputs_val = node_config.get("inputs")

            # Prioritize plural 'inputs', then singular 'input'
            final_inputs = inputs_val if inputs_val is not None else input_val

            if final_inputs is None:
                raise StreamingValidationError(
                    f"Node '{node_name}' must have input configuration",
                    field="input/inputs",
                )

            if isinstance(final_inputs, list):
                if not final_inputs:
                    raise StreamingValidationError(
                        f"Node '{node_name}' input list cannot be empty",
                        field="input/inputs",
                    )
                for idx, input_spec in enumerate(final_inputs):
                    self._validate_streaming_input_config(input_spec, f"{node_name}[input:{idx}]")
            else:
                self._validate_streaming_input_config(final_inputs, node_name)

            # ── Output Validation ─────────────────────────────────────────────
            output_val = node_config.get("output")
            outputs_val = node_config.get("outputs")

            # Prioritize plural 'outputs', then singular 'output'
            final_outputs = outputs_val if outputs_val is not None else output_val

            if final_outputs is None:
                raise StreamingValidationError(
                    f"Node '{node_name}' must have output configuration",
                    field="output/outputs",
                )

            if isinstance(final_outputs, list):
                if not final_outputs:
                    raise StreamingValidationError(
                        f"Node '{node_name}' output list cannot be empty",
                        field="output/outputs",
                    )
                for idx, output_spec in enumerate(final_outputs):
                    self._validate_streaming_output_config(
                        output_spec, f"{node_name}[output:{idx}]"
                    )
            else:
                self._validate_streaming_output_config(final_outputs, node_name)

        except StreamingValidationError as e:
            e.add_context("validation_phase", "I/O")
            raise

    def _validate_node_streaming_config(self, node_config: Dict[str, Any], node_name: str) -> None:
        """Validate streaming-specific configuration (Phase 3)."""
        try:
            streaming_config = node_config.get("streaming", {})
            if streaming_config:
                self._validate_streaming_config(streaming_config, node_name)
        except StreamingValidationError as e:
            e.add_context("validation_phase", "streaming")
            raise

    def _validate_node_function_config(self, node_config: Dict[str, Any], node_name: str) -> None:
        """Validate function configuration if present (Phase 4)."""
        try:
            function_config = node_config.get("function")
            if function_config:
                self._validate_function_config(function_config, node_name)
        except StreamingValidationError as e:
            e.add_context("validation_phase", "function")
            raise

    def _validate_streaming_input_config(self, input_config: Any, node_name: str) -> None:
        """Validate streaming input configuration with format-specific checks.

        Supports both dictionary configurations and simplified string references (paths/tables).
        """
        try:
            # Handle shorthand string configuration (treat as path/reference)
            if isinstance(input_config, str):
                if not input_config.strip():
                    raise StreamingValidationError(
                        f"Node '{node_name}' input configuration cannot be an empty string",
                        field="input",
                    )
                return  # Basic string references are valid shorthands

            if not isinstance(input_config, dict):
                raise StreamingValidationError(
                    f"Node '{node_name}' input configuration must be a dictionary or string",
                    field="input",
                    expected="dict or str",
                    actual=str(type(input_config)),
                )

            # Validate format
            format_type = input_config.get("format")
            if not format_type:
                raise StreamingValidationError(
                    f"Node '{node_name}' input must specify 'format'",
                    field="input.format",
                )

            # Use policy if available, otherwise use default enums
            valid_formats = (
                self.policy.get_supported_input_formats()
                if self.policy
                else [fmt.value for fmt in StreamingFormat]
            )
            if format_type not in valid_formats:
                raise StreamingValidationError(
                    f"Node '{node_name}' has unsupported input format '{format_type}'",
                    field="input.format",
                    expected=str(valid_formats),
                    actual=format_type,
                )

            # Validate options dict
            options = input_config.get("options", {})
            if not isinstance(options, dict):
                raise StreamingValidationError(
                    f"Node '{node_name}' input options must be a dictionary",
                    field=INPUT_OPTIONS_FIELD,
                    expected="dict",
                    actual=str(type(options)),
                )

            format_config = STREAMING_FORMAT_CONFIGS.get(format_type, {})

            # Check required options
            required_options = format_config.get("required_options", [])
            missing_options = []
            for opt in required_options:
                if (
                    format_type == StreamingFormat.FILE_STREAM.value
                    and opt == "path"
                    and input_config.get("path")
                ):
                    continue
                if opt not in options:
                    missing_options.append(opt)
            if missing_options:
                raise StreamingValidationError(
                    f"Node '{node_name}' missing required options for {format_type}: {missing_options}",
                    field=INPUT_OPTIONS_FIELD,
                    expected=str(required_options),
                    actual=str(list(options.keys())),
                )

            # Validate format-specific constraints
            if format_type == StreamingFormat.KAFKA.value:
                self._validate_kafka_options(options, node_name)
            elif format_type == StreamingFormat.FILE_STREAM.value:
                self._validate_file_stream_options(options, node_name, input_config)
            elif format_type == StreamingFormat.KINESIS.value:
                self._validate_kinesis_options(options, node_name)

            # Validate watermark configuration
            watermark = input_config.get("watermark")
            if watermark:
                self._validate_watermark_config(watermark, node_name)

        except StreamingValidationError:
            raise
        except Exception as e:
            raise StreamingValidationError(
                f"Error validating input config for node '{node_name}': {str(e)}",
                cause=e,
            )

    def _validate_streaming_output_config(self, output_config: Any, node_name: str) -> None:
        """Validate streaming output configuration with comprehensive checks.

        Supports both dictionary configurations and simplified string references.
        """
        try:
            # Handle shorthand string configuration
            if isinstance(output_config, str):
                if not output_config.strip():
                    raise StreamingValidationError(
                        f"Node '{node_name}' output configuration cannot be an empty string",
                        field="output",
                    )
                return

            if not isinstance(output_config, dict):
                raise StreamingValidationError(
                    f"Node '{node_name}' output configuration must be a dictionary or string",
                    field="output",
                    expected="dict or str",
                    actual=str(type(output_config)),
                )

            # Validate format
            format_type = output_config.get("format")
            if not format_type:
                raise StreamingValidationError(
                    f"Node '{node_name}' output must specify 'format'",
                    field="output.format",
                )

            # Optional policy validation for output formats
            valid_outputs = (
                self.policy.get_supported_output_formats()
                if self.policy
                else DEFAULT_SUPPORTED_OUTPUT_FORMATS
            )
            if format_type not in valid_outputs:
                raise StreamingValidationError(
                    f"Node '{node_name}' has unsupported output format '{format_type}'",
                    field="output.format",
                    expected=str(valid_outputs),
                    actual=format_type,
                )

            # Delegate checks to specialized helpers
            file_formats = ["delta", "parquet", "json", "csv"]
            if format_type in file_formats:
                self._validate_file_output_path(output_config.get("path"), node_name, format_type)
            elif format_type == "kafka":
                self._validate_kafka_output_options(output_config, node_name)

            # Validate partitioning configuration regardless of format
            partition_by = output_config.get("partitionBy")
            self._validate_partition_by(partition_by, node_name)

            # Reject streaming.* settings misplaced under output.*
            reserved_present = RESERVED_OUTPUT_KEYS.intersection(output_config.keys())
            if reserved_present:
                raise StreamingValidationError(
                    f"Node '{node_name}' output config must not set {sorted(reserved_present)} "
                    f"directly; use 'streaming.trigger' / 'streaming.output_mode' / "
                    f"'streaming.checkpoint_location' / 'streaming.query_name' instead.",
                    field="output",
                    expected="none of " + str(sorted(RESERVED_OUTPUT_KEYS)),
                    actual=str(sorted(reserved_present)),
                )

        except StreamingValidationError:
            raise
        except Exception as e:
            raise StreamingValidationError(
                f"Error validating output config for node '{node_name}': {str(e)}",
                cause=e,
            )

    def _validate_file_output_path(
        self, path: Optional[str], node_name: str, format_type: str
    ) -> None:
        """Validate path for file-based outputs (helper)."""
        if not path:
            raise StreamingValidationError(
                f"Node '{node_name}' output format '{format_type}' requires 'path'",
                field="output.path",
                expected=NON_EMPTY_STRING,
                actual=str(path),
            )

        if not isinstance(path, str) or not path.strip():
            raise StreamingValidationError(
                f"Node '{node_name}' output path must be a non-empty string",
                field="output.path",
                expected=NON_EMPTY_STRING,
                actual=str(path),
            )

    def _validate_partition_by(self, partition_by: Optional[Any], node_name: str) -> None:
        """Validate partitionBy clause (helper)."""
        if partition_by is None:
            return
        if not isinstance(partition_by, (str, list)):
            raise StreamingValidationError(
                f"Node '{node_name}' partitionBy must be string or list of strings",
                field="output.partitionBy",
                expected="str or list",
                actual=str(type(partition_by)),
            )

    def _validate_streaming_config(self, streaming_config: Dict[str, Any], node_name: str) -> None:
        """Validate streaming-specific configuration with detailed checks."""
        if not isinstance(streaming_config, dict):
            raise StreamingValidationError(
                f"Node '{node_name}' streaming configuration must be a dictionary",
                field="streaming",
                expected="dict",
                actual=str(type(streaming_config)),
            )

        trigger = streaming_config.get("trigger", {})
        if trigger:
            self._validate_trigger_config(trigger, node_name)

        output_mode = streaming_config.get("output_mode")
        if output_mode:
            valid_modes = [mode.value for mode in StreamingOutputMode]
            if output_mode not in valid_modes:
                raise StreamingValidationError(
                    f"Node '{node_name}' has invalid output_mode '{output_mode}'",
                    field="streaming.output_mode",
                    expected=str(valid_modes),
                    actual=output_mode,
                )

        checkpoint = streaming_config.get("checkpoint_location")
        if checkpoint and not isinstance(checkpoint, str):
            raise StreamingValidationError(
                f"Node '{node_name}' checkpoint_location must be a string",
                field="streaming.checkpoint_location",
                expected="str",
                actual=str(type(checkpoint)),
            )

        query_name = streaming_config.get("query_name")
        if query_name is not None and not isinstance(query_name, str):
            raise StreamingValidationError(
                f"Node '{node_name}' query_name must be a string",
                field="streaming.query_name",
                expected="str",
                actual=str(type(query_name)),
            )

        watermark = streaming_config.get("watermark")
        if watermark:
            self._validate_watermark_config(
                watermark, node_name, field_prefix="streaming.watermark"
            )

    def _validate_function_config(self, function_config: Any, node_name: str) -> None:
        """Validate function configuration for registered transformations.

        Supports both dictionary configurations and simplified string references (function names).
        """
        # Handle shorthand string configuration
        if isinstance(function_config, str):
            if not function_config.strip():
                raise StreamingValidationError(
                    f"Node '{node_name}' function configuration cannot be an empty string",
                    field="function",
                )
            return

        if not isinstance(function_config, dict):
            raise StreamingValidationError(
                f"Node '{node_name}' function configuration must be a dictionary or string",
                field="function",
                expected="dict or str",
                actual=str(type(function_config)),
            )

        legacy_keys = {"function"}
        has_legacy = legacy_keys.intersection(function_config)
        has_key = "key" in function_config
        if has_legacy and not has_key:
            raise StreamingValidationError(
                f"Node '{node_name}' function config must use 'key', not legacy keys {sorted(has_legacy)}",
                field="function",
                expected="{'key': ...}",
                actual=str(list(function_config.keys())),
            )
        if has_legacy and has_key:
            logger.warning(
                f"Node '{node_name}' function config has both 'key' and legacy keys {sorted(has_legacy)}. "
                f"Using 'key' value."
            )

        key_value = function_config.get("key")
        if not isinstance(key_value, str) or not key_value.strip():
            raise StreamingValidationError(
                f"Node '{node_name}' function.key must be a non-empty string",
                field="function.key",
                expected=NON_EMPTY_STRING,
                actual=str(key_value),
            )

        module_value = function_config.get("module")
        if module_value is not None:
            if not isinstance(module_value, str) or not module_value.strip():
                raise StreamingValidationError(
                    f"Node '{node_name}' function.module must be a non-empty string",
                    field="function.module",
                    expected=NON_EMPTY_STRING,
                    actual=str(module_value),
                )

    def _validate_pipeline_streaming_config(self, streaming_config: Dict[str, Any]) -> None:
        """Validate pipeline-level streaming configuration."""
        if not isinstance(streaming_config, dict):
            raise StreamingValidationError(
                "Pipeline streaming configuration must be a dictionary",
                field="streaming",
                expected="dict",
                actual=str(type(streaming_config)),
            )

        max_concurrent_queries = streaming_config.get("max_concurrent_queries")
        if max_concurrent_queries is not None:
            try:
                max_concurrent_queries = int(max_concurrent_queries)
                if max_concurrent_queries <= 0:
                    raise ValueError()
            except (ValueError, TypeError):
                raise StreamingValidationError(
                    "max_concurrent_queries must be a positive integer",
                    field="streaming.max_concurrent_queries",
                    expected="positive integer",
                    actual=str(max_concurrent_queries),
                )

    def _validate_kafka_options(self, options: Dict[str, Any], node_name: str) -> None:
        """Validate Kafka-specific options with comprehensive checks."""

        for subscription_options in STREAMING_VALIDATIONS.get(
            "mutually_exclusive_kafka_options", []
        ):
            provided_subscriptions = [opt for opt in subscription_options if opt in options]

            if len(provided_subscriptions) == 0:
                raise StreamingValidationError(
                    f"Node '{node_name}' Kafka input must specify one of: {subscription_options}",
                    field=INPUT_OPTIONS_FIELD,
                    expected=f"one of {subscription_options}",
                    actual="none provided",
                )

            if len(provided_subscriptions) > 1:
                raise StreamingValidationError(
                    f"Node '{node_name}' Kafka input cannot specify multiple subscription options: {provided_subscriptions}",
                    field=INPUT_OPTIONS_FIELD,
                    expected=f"only one of {subscription_options}",
                    actual=str(provided_subscriptions),
                )

        # Validate bootstrap servers format
        bootstrap_servers = options.get("kafka.bootstrap.servers")
        if bootstrap_servers:
            if not isinstance(bootstrap_servers, str):
                raise StreamingValidationError(
                    f"Node '{node_name}' kafka.bootstrap.servers must be a string",
                    field=f"{INPUT_OPTIONS_FIELD}.kafka.bootstrap.servers",
                    expected="string",
                    actual=str(type(bootstrap_servers)),
                )

            # Basic format validation
            if not bootstrap_servers.strip():
                raise StreamingValidationError(
                    f"Node '{node_name}' kafka.bootstrap.servers cannot be empty",
                    field=f"{INPUT_OPTIONS_FIELD}.kafka.bootstrap.servers",
                )

        # Validate subscription values
        subscribe = options.get("subscribe")
        if subscribe and not isinstance(subscribe, str):
            raise StreamingValidationError(
                f"Node '{node_name}' Kafka subscribe must be a string",
                field=f"{INPUT_OPTIONS_FIELD}.subscribe",
                expected="string",
                actual=str(type(subscribe)),
            )

    def _validate_kafka_output_options(self, output_config: Dict[str, Any], node_name: str) -> None:
        """Validate Kafka output-specific options."""
        options = output_config.get("options", {})

        required_kafka_options = ["kafka.bootstrap.servers", "topic"]
        missing_options = [opt for opt in required_kafka_options if opt not in options]
        if missing_options:
            raise StreamingValidationError(
                f"Node '{node_name}' Kafka output missing required options: {missing_options}",
                field="output.options",
                expected=str(required_kafka_options),
                actual=str(list(options.keys())),
            )

        # Validate topic name
        topic = options.get("topic")
        if topic and not isinstance(topic, str):
            raise StreamingValidationError(
                f"Node '{node_name}' Kafka topic must be a string",
                field="output.options.topic",
                expected="string",
                actual=str(type(topic)),
            )

    def _validate_file_stream_options(
        self, options: Dict[str, Any], node_name: str, input_config: Dict[str, Any]
    ) -> None:
        """Validate file stream-specific options."""
        path_value = options.get("path") or input_config.get("path")
        if not path_value:
            raise StreamingValidationError(
                f"Node '{node_name}' file stream requires 'path' in input.options or input.path",
                field=f"{INPUT_OPTIONS_FIELD}.path",
                expected=NON_EMPTY_STRING,
                actual=str(path_value),
            )

        if not isinstance(path_value, str) or not path_value.strip():
            raise StreamingValidationError(
                f"Node '{node_name}' file stream path must be a non-empty string",
                field=f"{INPUT_OPTIONS_FIELD}.path",
                expected=NON_EMPTY_STRING,
                actual=str(path_value),
            )

        if input_config.get("path") and not options.get("path"):
            logger.warning(
                f"Node '{node_name}' uses deprecated input.path for file_stream. "
                "Use input.options.path instead."
            )

        # Validate file_format
        file_format = input_config.get("file_format", "parquet")
        if file_format not in ALLOWED_FILE_FORMATS:
            raise StreamingValidationError(
                f"Node '{node_name}' has unsupported file format '{file_format}'",
                field="input.file_format",
                expected=str(sorted(ALLOWED_FILE_FORMATS)),
                actual=file_format,
            )

        # Validate numeric options
        numeric_options = ["maxFilesPerTrigger"]
        for opt in numeric_options:
            if opt in options:
                try:
                    int(options[opt])
                except (ValueError, TypeError):
                    raise StreamingValidationError(
                        f"Node '{node_name}' file stream option '{opt}' must be numeric",
                        field=f"{INPUT_OPTIONS_FIELD}.{opt}",
                        expected="numeric",
                        actual=str(options[opt]),
                    )

    def _validate_pipeline_dependencies(
        self, nodes: List[Any], satisfied_dependencies: Optional[Set[str]] = None
    ) -> None:
        """Validate depends_on declarations across pipeline nodes.

        Names in ``satisfied_dependencies`` completed outside this pipeline and
        are exempt from the "undefined node" check — see
        :meth:`topological_sort`.
        """
        satisfied = satisfied_dependencies or set()
        node_names: List[str] = []
        node_by_name: Dict[str, Dict[str, Any]] = {}

        for idx, node in enumerate(nodes):
            if isinstance(node, str):
                node_name = node.strip()
            else:
                node_name = node.get("name", f"node_{idx}")

            if node_name in node_by_name:
                raise StreamingValidationError(
                    f"Duplicate node name '{node_name}' in streaming pipeline",
                    field="nodes.name",
                    actual=node_name,
                )

            node_names.append(node_name)
            node_by_name[node_name] = node if isinstance(node, dict) else {"name": node_name}

        names_set = set(node_names)

        for node_name, node in node_by_name.items():
            depends_on = node.get("depends_on", node.get("dependencies", []))
            if depends_on is None:
                continue

            if not isinstance(depends_on, list):
                raise StreamingValidationError(
                    f"Node '{node_name}' depends_on must be a list",
                    field="depends_on",
                    expected="list",
                    actual=str(type(depends_on)),
                )

            for dependency in depends_on:
                if dependency == node_name:
                    raise StreamingValidationError(
                        f"Node '{node_name}' cannot depend on itself",
                        field="depends_on",
                    )

                if dependency not in names_set and dependency not in satisfied:
                    raise StreamingValidationError(
                        f"Node '{node_name}' depends on undefined node '{dependency}'",
                        field="depends_on",
                        expected=str(sorted(names_set)),
                        actual=dependency,
                    )

        self._validate_acyclic_dependencies(node_by_name, satisfied_dependencies=satisfied)

    def _validate_acyclic_dependencies(
        self,
        node_by_name: Dict[str, Dict[str, Any]],
        satisfied_dependencies: Optional[Set[str]] = None,
    ) -> None:
        """Detect cycles in the depends_on graph."""
        self.topological_sort(node_by_name, satisfied_dependencies=satisfied_dependencies)

    def topological_sort(
        self,
        node_by_name: Dict[str, Dict[str, Any]],
        satisfied_dependencies: Optional[Set[str]] = None,
    ) -> List[str]:
        """Return topologically sorted node names using Kahn's algorithm."""
        satisfied = satisfied_dependencies or set()
        node_names = list(node_by_name.keys())
        in_degree: Dict[str, int] = {name: 0 for name in node_names}
        graph: Dict[str, List[str]] = {name: [] for name in node_names}

        for name, node in node_by_name.items():
            for dep in get_node_dependencies(node):
                if dep in satisfied:
                    continue
                if dep not in node_by_name:
                    raise StreamingValidationError(
                        f"Node '{name}' depends on undefined node '{dep}'",
                        field="depends_on",
                        expected=str(sorted(node_by_name.keys())),
                        actual=dep,
                    )
                graph[dep].append(name)
                in_degree[name] += 1

        queue: deque = deque([name for name in node_names if in_degree[name] == 0])
        ordered: List[str] = []

        while queue:
            current = queue.popleft()
            ordered.append(current)
            for downstream in graph[current]:
                in_degree[downstream] -= 1
                if in_degree[downstream] == 0:
                    queue.append(downstream)

        if len(ordered) != len(node_names):
            cyclic = [name for name in node_names if in_degree[name] > 0]
            raise StreamingValidationError(
                f"Circular dependency detected in streaming pipeline: {cyclic}",
                field="depends_on",
            )

        return ordered

    def _validate_kinesis_options(self, options: Dict[str, Any], node_name: str) -> None:
        """Validate Kinesis-specific options."""
        required_options = ["streamName", "region"]
        missing_options = [opt for opt in required_options if opt not in options]
        if missing_options:
            raise StreamingValidationError(
                f"Node '{node_name}' Kinesis input missing required options: {missing_options}",
                field=INPUT_OPTIONS_FIELD,
                expected=str(required_options),
                actual=str(list(options.keys())),
            )

        # Validate stream name
        stream_name = options.get("streamName")
        if stream_name and not isinstance(stream_name, str):
            raise StreamingValidationError(
                f"Node '{node_name}' Kinesis streamName must be a string",
                field=f"{INPUT_OPTIONS_FIELD}.streamName",
                expected="string",
                actual=str(type(stream_name)),
            )

        # Validate region
        region = options.get("region")
        if region and not isinstance(region, str):
            raise StreamingValidationError(
                f"Node '{node_name}' Kinesis region must be a string",
                field=f"{INPUT_OPTIONS_FIELD}.region",
                expected="string",
                actual=str(type(region)),
            )

    def _validate_watermark_config(
        self, watermark: Dict[str, Any], node_name: str, field_prefix: str = "input.watermark"
    ) -> None:
        """Validate watermark configuration with enhanced checks."""
        if not isinstance(watermark, dict):
            raise StreamingValidationError(
                f"Node '{node_name}' watermark configuration must be a dictionary",
                field=field_prefix,
                expected="dict",
                actual=str(type(watermark)),
            )

        # Validate column name
        column = watermark.get("column")
        if not column:
            raise StreamingValidationError(
                f"Node '{node_name}' watermark must specify 'column'",
                field=f"{field_prefix}.column",
            )
        if not isinstance(column, str) or not column.strip():
            raise StreamingValidationError(
                f"Node '{node_name}' watermark column must be a non-empty string",
                field=f"{field_prefix}.column",
                expected=NON_EMPTY_STRING,
                actual=str(column),
            )

        delay = watermark.get("delay", "10 seconds")
        if not self.validate_time_interval(delay):
            raise StreamingValidationError(
                f"Node '{node_name}' watermark delay '{delay}' is invalid",
                field=f"{field_prefix}.delay",
                expected="time interval like '10 seconds', '5 minutes', '1 hour'",
                actual=delay,
            )

        delay_minutes = self._parse_time_to_minutes(delay)
        max_delay = STREAMING_VALIDATIONS["max_watermark_delay_minutes"]
        if delay_minutes > max_delay:
            raise StreamingValidationError(
                f"Node '{node_name}' watermark delay '{delay}' exceeds maximum allowed delay of {max_delay} minutes",
                field=f"{field_prefix}.delay",
                expected=f"<= {max_delay} minutes",
                actual=f"{delay_minutes} minutes",
            )

    def _validate_trigger_config(self, trigger: Dict[str, Any], node_name: str) -> None:
        """Validate trigger configuration with comprehensive validation."""
        if not isinstance(trigger, dict):
            raise StreamingValidationError(
                f"Node '{node_name}' trigger configuration must be a dictionary",
                field="streaming.trigger",
                expected="dict",
                actual=str(type(trigger)),
            )

        # Validate trigger type — defaults to processing_time when omitted,
        # matching TriggerScheduler.configure_trigger's runtime behavior.
        trigger_type = trigger.get("type", StreamingTrigger.PROCESSING_TIME.value)

        valid_triggers = [t.value for t in StreamingTrigger]
        if trigger_type not in valid_triggers:
            raise StreamingValidationError(
                f"Node '{node_name}' has invalid trigger type '{trigger_type}'",
                field="streaming.trigger.type",
                expected=str(valid_triggers),
                actual=trigger_type,
            )

        if trigger_type in [
            StreamingTrigger.PROCESSING_TIME.value,
            StreamingTrigger.CONTINUOUS.value,
        ]:
            interval = trigger.get("interval")
            if not interval:
                raise StreamingValidationError(
                    f"Node '{node_name}' trigger type '{trigger_type}' requires 'interval'",
                    field=TRIGGER_INTERVAL_FIELD,
                )

            if not self.validate_time_interval(interval):
                raise StreamingValidationError(
                    f"Node '{node_name}' trigger interval '{interval}' is invalid",
                    field=TRIGGER_INTERVAL_FIELD,
                    expected="time interval like '10 seconds', '5 minutes'",
                    actual=interval,
                )

            # Check minimum interval
            interval_seconds = self.parse_time_to_seconds(interval)
            min_interval = STREAMING_VALIDATIONS["min_trigger_interval_seconds"]
            if interval_seconds < min_interval:
                raise StreamingValidationError(
                    f"Node '{node_name}' trigger interval '{interval}' is below minimum allowed interval of {min_interval} seconds",
                    field=TRIGGER_INTERVAL_FIELD,
                    expected=f">= {min_interval} seconds",
                    actual=f"{interval_seconds} seconds",
                )

    # Multipliers used by both _validate_time_interval and _parse_time_to_seconds
    _UNIT_MULTIPLIERS: Dict[str, float] = {
        "millisecond": 0.001,
        "milliseconds": 0.001,
        "microsecond": 0.000001,
        "microseconds": 0.000001,
        "second": 1.0,
        "seconds": 1.0,
        "minute": 60.0,
        "minutes": 60.0,
        "hour": 3600.0,
        "hours": 3600.0,
        "day": 86400.0,
        "days": 86400.0,
    }

    _TIME_INTERVAL_RE = re.compile(
        r"^(\d+(?:\.\d+)?)\s+(second|seconds|minute|minutes|hour|hours|day|days"
        r"|millisecond|milliseconds|microsecond|microseconds)$",
        re.IGNORECASE,
    )

    def validate_time_interval(self, interval: str) -> bool:
        """Validate time interval format and value constraints.

        Valid ranges: 0 seconds < interval <= 365 days (1 year)
        """
        if not isinstance(interval, str):
            return False

        match = self._TIME_INTERVAL_RE.match(interval.strip())
        if not match:
            return False

        try:
            value = float(match.group(1))
            if value <= 0:
                logger.warning(f"Time interval '{interval}' must be positive (> 0)")
                return False

            # Compute seconds directly from the regex match — avoids double-parse
            unit = match.group(2).lower()
            seconds = value * self._UNIT_MULTIPLIERS.get(unit, 0.0)

            min_seconds = 0.000001  # Allow microseconds
            if seconds < min_seconds:
                logger.warning(f"Time interval '{interval}' is below minimum ({min_seconds}s)")
                return False

            max_seconds = 86400 * 365  # 1 year
            if seconds > max_seconds:
                logger.warning(
                    f"Time interval '{interval}' exceeds maximum (1 year / {max_seconds}s)"
                )
                return False
        except (ValueError, TypeError):
            return False

        return True

    # Backward-compat alias so existing callers using the private name still work.
    _validate_time_interval = validate_time_interval

    def parse_time_to_seconds(self, interval: str) -> float:
        """Parse time interval to seconds. Reuses the precompiled multiplier table."""
        if not isinstance(interval, str):
            return 0.0

        parts = interval.strip().split()
        if len(parts) != 2:
            return 0.0

        try:
            number = float(parts[0])
            unit = parts[1].lower()
            return number * self._UNIT_MULTIPLIERS.get(unit, 0.0)
        except (ValueError, TypeError):
            return 0.0

    # Backward-compat alias so existing callers using the private name still work.
    _parse_time_to_seconds = parse_time_to_seconds

    def _parse_time_to_minutes(self, interval: str) -> float:
        """Parse time interval to minutes."""
        seconds = self.parse_time_to_seconds(interval)
        return seconds / 60.0

    def _build_compatibility_warnings(
        self,
        batch_outputs: set,
        streaming_outputs: set,
        streaming_nodes: List[Any],
        batch_nodes: List[Any],
    ) -> List[str]:
        """Build all compatibility warnings in one method."""
        warnings: List[str] = []
        self._append_shared_output_warning(warnings, batch_outputs, streaming_outputs)
        self._append_duplicate_checkpoint_warnings(warnings, streaming_nodes)
        self._append_resource_usage_warning(warnings, batch_nodes, streaming_nodes)
        return warnings

    def validate_pipeline_compatibility(
        self, batch_config: Dict[str, Any], streaming_config: Dict[str, Any]
    ) -> List[str]:
        """Validate compatibility between batch and streaming configurations."""
        try:
            batch_nodes = batch_config.get("nodes", [])
            streaming_nodes = streaming_config.get("nodes", [])

            batch_outputs = self._extract_output_paths(batch_nodes)
            streaming_outputs = self._extract_output_paths(streaming_nodes)

            return self._build_compatibility_warnings(
                batch_outputs, streaming_outputs, streaming_nodes, batch_nodes
            )

        except Exception as e:
            logger.error(f"Error validating pipeline compatibility: {str(e)}")
            return [f"Error during compatibility validation: {str(e)}"]

    def _extract_output_paths(self, nodes: List[Any]) -> set:
        """Extract output path strings from a list of nodes."""
        outputs = set()
        for node in nodes:
            if not isinstance(node, dict):
                continue
            output_cfg = node.get("outputs", node.get("output"))
            if output_cfg is None:
                continue
            specs = output_cfg if isinstance(output_cfg, list) else [output_cfg]
            for spec in specs:
                if isinstance(spec, dict):
                    output_path = spec.get("path")
                    if output_path:
                        outputs.add(output_path)
        return outputs

    def _append_shared_output_warning(
        self, warnings: List[str], batch_outputs: set, streaming_outputs: set
    ) -> None:
        """Append a warning if there are shared output resources."""
        shared = batch_outputs.intersection(streaming_outputs)
        if shared:
            warnings.append(
                f"Shared output resources detected: {shared}. "
                f"Ensure proper coordination to avoid conflicts."
            )

    def _append_duplicate_checkpoint_warnings(
        self, warnings: List[str], streaming_nodes: List[Any]
    ) -> None:
        """Detect duplicate checkpoint locations across streaming nodes and append warnings."""
        checkpoint_locations = set()
        for node in streaming_nodes:
            if not isinstance(node, dict):
                continue
            checkpoint = node.get("streaming", {}).get("checkpoint_location")
            if not checkpoint:
                continue
            if checkpoint in checkpoint_locations:
                warnings.append(
                    f"Duplicate checkpoint location: {checkpoint}. "
                    f"Each streaming query should have a unique checkpoint."
                )
            checkpoint_locations.add(checkpoint)

    def _append_resource_usage_warning(
        self, warnings: List[str], batch_nodes: List[Any], streaming_nodes: List[Any]
    ) -> None:
        """Append a resource usage warning when node counts indicate potential issues."""
        if (
            len(batch_nodes) > self.max_batch_nodes
            and len(streaming_nodes) > self.max_streaming_nodes
        ):
            warnings.append(
                f"High resource usage detected: {len(batch_nodes)} batch nodes and "
                f"{len(streaming_nodes)} streaming nodes. Consider resource allocation."
            )
