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

from typing import Any, Dict, List, Optional, Tuple

from loguru import logger  # type: ignore

from ducta.core.utils import extract_pipeline_nodes as _extract_pipeline_nodes_util
from ducta.core.utils import get_node_dependencies as _get_node_dependencies_util
from ducta.setting.validators import FormatPolicy


def _output_as_dict(node_config: Dict[str, Any]) -> Dict[str, Any]:
    """Return a node's ``output`` as a dict for inline-path/format inspection."""
    output = node_config.get("output")
    return output if isinstance(output, dict) else {}


class PipelineValidator:
    """Validator supporting hybrid batch/streaming pipelines."""

    @staticmethod
    def validate_required_params(
        pipeline_name: Optional[str],
        start_date: Optional[str],
        end_date: Optional[str],
        context_start_date: Optional[str],
        context_end_date: Optional[str],
        requires_dates: bool = True,
    ) -> None:
        """Validate required parameters for pipeline execution."""
        if not pipeline_name:
            raise ValueError("Pipeline name is required")

        logger.debug(
            f"Validating params for '{pipeline_name}': requires_dates={requires_dates}, start_date={start_date}, end_date={end_date}, context_start_date={context_start_date}, context_end_date={context_end_date}"
        )

        if requires_dates:
            PipelineValidator._validate_date_params(
                start_date, context_start_date, end_date, context_end_date
            )

    @staticmethod
    def _validate_date_params(
        start_date: Optional[str],
        context_start_date: Optional[str],
        end_date: Optional[str],
        context_end_date: Optional[str],
    ) -> None:
        """Validate that either user or context dates are provided."""
        if not (start_date or context_start_date):
            raise ValueError("Start date is required")
        if not (end_date or context_end_date):
            raise ValueError("End date is required")

    @staticmethod
    def validate_pipeline_config(pipeline: Dict[str, Any]) -> None:
        """Validate basic pipeline configuration."""
        if not isinstance(pipeline, dict):
            raise ValueError("Pipeline configuration must be a dictionary")

        if "nodes" not in pipeline:
            raise ValueError("Pipeline must contain 'nodes' key")

        nodes = pipeline["nodes"]
        if not nodes:
            raise ValueError("Pipeline must have at least one node")

        if not isinstance(nodes, list):
            raise ValueError("Pipeline 'nodes' must be a list")

    @staticmethod
    def validate_node_configs(
        pipeline_nodes: List[str], node_configs: Dict[str, Dict[str, Any]]
    ) -> None:
        """Validate that all pipeline nodes have configurations."""
        missing_nodes = []
        for node_name in pipeline_nodes:
            if node_name not in node_configs:
                missing_nodes.append(node_name)

        if missing_nodes:
            raise ValueError(f"Missing node configurations: {', '.join(missing_nodes)}")

    @staticmethod
    def validate_no_dag_cycles(
        pipeline_nodes: List[str],
        node_configs: Dict[str, Dict[str, Any]],
    ) -> None:
        """Detect circular dependencies in the node execution graph using DFS.

        Raises ValueError if a cycle is found, with the cycle path in the message.

        Uses the same explicit ∪ dataset-inferred dependency merge as
        ``DependencyResolver.build_dependency_graph`` (the graph the executor
        actually runs against) — checking only explicit ``dependencies`` would
        miss a cycle created purely by two nodes' shared dataset input/output
        keys, letting it pass preflight and fail only once the pipeline starts.
        """
        from ducta.core.dependency_inference import resolve_node_dependencies
        from ducta.core.dependency_resolver import detect_cycles_dfs

        resolved = resolve_node_dependencies(pipeline_nodes, node_configs)

        # Build adjacency list: node -> deps that exist in this pipeline
        graph: Dict[str, List[str]] = {}
        for node in pipeline_nodes:
            deps = resolved.get(node, [])
            graph[node] = [d for d in deps if d in node_configs]

        detect_cycles_dfs(graph)

    @staticmethod
    def validate_hybrid_pipeline(
        pipeline: Dict[str, Any],
        node_configs: Dict[str, Dict[str, Any]],
        format_policy: Optional[FormatPolicy] = None,
    ) -> Dict[str, Any]:
        """Validate hybrid pipeline and return detailed analysis."""
        policy = format_policy or FormatPolicy()

        validation_result = {
            "is_valid": True,
            "errors": [],
            "warnings": [],
            "batch_nodes": [],
            "streaming_nodes": [],
            "cross_dependencies": [],
            "format_compatibility": [],
            "resource_conflicts": [],
        }

        try:
            batch_nodes, streaming_nodes = PipelineValidator._classify_nodes(
                pipeline, node_configs, policy
            )

            validation_result["batch_nodes"] = batch_nodes
            validation_result["streaming_nodes"] = streaming_nodes

            cross_deps, cross_errors = PipelineValidator._validate_cross_dependencies(
                batch_nodes, streaming_nodes, node_configs
            )

            validation_result["cross_dependencies"] = cross_deps
            validation_result["errors"].extend(cross_errors)

            format_issues = PipelineValidator._validate_format_compatibility(
                cross_deps, node_configs, policy
            )

            validation_result["format_compatibility"] = format_issues
            validation_result["errors"].extend(
                [issue for issue in format_issues if issue["severity"] == "error"]
            )
            validation_result["warnings"].extend(
                [issue for issue in format_issues if issue["severity"] == "warning"]
            )

            bidirectional_errors = PipelineValidator._validate_hybrid_format_compatibility(
                batch_nodes, streaming_nodes, node_configs, policy
            )
            validation_result["errors"].extend(bidirectional_errors)

            resource_conflicts = PipelineValidator._validate_resource_conflicts(
                batch_nodes, streaming_nodes, node_configs
            )

            validation_result["resource_conflicts"] = resource_conflicts
            validation_result["warnings"].extend(resource_conflicts)

            streaming_errors = PipelineValidator._validate_streaming_requirements(
                streaming_nodes, node_configs, policy
            )

            validation_result["errors"].extend(streaming_errors)

            validation_result["is_valid"] = len(validation_result["errors"]) == 0

        except Exception as e:
            validation_result["is_valid"] = False
            validation_result["errors"].append(f"Validation failed with error: {str(e)}")

        return validation_result

    @staticmethod
    def _classify_nodes(
        pipeline: Dict[str, Any],
        node_configs: Dict[str, Dict[str, Any]],
        policy: FormatPolicy,
    ) -> Tuple[List[str], List[str]]:
        """Classify nodes into batch and streaming."""

        batch_nodes = []
        streaming_nodes = []

        pipeline_nodes = _extract_pipeline_nodes_util(pipeline)

        for node_name in pipeline_nodes:
            node_config = node_configs.get(node_name, {})

            if PipelineValidator._is_streaming_node(node_config, policy):
                streaming_nodes.append(node_name)
            else:
                batch_nodes.append(node_name)

        return batch_nodes, streaming_nodes

    @staticmethod
    def _is_streaming_node(node_config: Dict[str, Any], policy: FormatPolicy) -> bool:
        """Determine if a node is streaming by explicit type or input format."""
        node_type = node_config.get("type", "").lower()
        if node_type == "streaming":
            return True

        if node_config.get("streaming"):
            return True

        input_config = node_config.get("input", {})
        if isinstance(input_config, dict):
            input_format = input_config.get("format", "")
            return policy.is_supported_input(input_format)

        return False

    @staticmethod
    def _validate_cross_dependencies(
        batch_nodes: List[str],
        streaming_nodes: List[str],
        node_configs: Dict[str, Dict[str, Any]],
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        """Validate cross-dependencies between batch and streaming nodes."""

        cross_dependencies = []
        errors = []

        for streaming_node in streaming_nodes:
            node_config = node_configs.get(streaming_node, {})
            dependencies = _get_node_dependencies_util(node_config)

            batch_deps = [dep for dep in dependencies if dep in batch_nodes]

            if batch_deps:
                cross_dependencies.append(
                    {
                        "streaming_node": streaming_node,
                        "batch_dependencies": batch_deps,
                        "type": "streaming_depends_on_batch",
                    }
                )

                for batch_dep in batch_deps:
                    batch_config = node_configs.get(batch_dep, {})
                    batch_output = batch_config.get("output")
                    inline_output = _output_as_dict(batch_config)

                    # A batch node must declare *some* output for a streaming node
                    # to consume. It may be a catalog-key list (data flows through
                    # the IO catalog / filesystem) or an inline dict with a path.
                    has_catalog_output = isinstance(batch_output, (list, str)) and bool(
                        batch_output
                    )
                    if not has_catalog_output and not inline_output.get("path"):
                        errors.append(
                            f"Batch node '{batch_dep}' (dependency of streaming node '{streaming_node}') "
                            f"must declare an output for cross-pipeline data flow"
                        )

        for batch_node in batch_nodes:
            node_config = node_configs.get(batch_node, {})
            dependencies = _get_node_dependencies_util(node_config)

            streaming_deps = [dep for dep in dependencies if dep in streaming_nodes]

            if streaming_deps:
                errors.append(
                    f"Batch node '{batch_node}' cannot depend on streaming nodes: {streaming_deps}. "
                    f"This creates an invalid dependency pattern."
                )

        return cross_dependencies, errors

    @staticmethod
    def _validate_format_compatibility(
        cross_dependencies: List[Dict[str, Any]],
        node_configs: Dict[str, Dict[str, Any]],
        policy: FormatPolicy,
    ) -> List[Dict[str, Any]]:
        """Validate format compatibility between batch and streaming nodes."""
        format_issues: List[Dict[str, Any]] = []

        for cross_dep in cross_dependencies:
            streaming_node = cross_dep["streaming_node"]
            batch_deps = cross_dep["batch_dependencies"]

            streaming_config = node_configs.get(streaming_node, {})
            for batch_dep in batch_deps:
                batch_config = node_configs.get(batch_dep, {})
                batch_output = _output_as_dict(batch_config)
                batch_format = batch_output.get("format")

                streaming_input = streaming_config.get("input", {})
                streaming_format = streaming_input.get("format")

                if batch_format and streaming_format:
                    if policy.are_compatible(batch_format, streaming_format):
                        format_issues.append(
                            {
                                "severity": "info",
                                "message": f"Compatible formats: '{batch_format}' -> '{streaming_format}'",
                                "batch_node": batch_dep,
                                "streaming_node": streaming_node,
                                "batch_format": batch_format,
                                "streaming_format": streaming_format,
                            }
                        )
                    else:
                        format_issues.append(
                            {
                                "severity": "error",
                                "message": f"Incompatible formats: batch node '{batch_dep}' outputs "
                                f"'{batch_format}' but streaming node '{streaming_node}' expects "
                                f"'{streaming_format}'.",
                                "batch_node": batch_dep,
                                "streaming_node": streaming_node,
                                "batch_format": batch_format,
                                "streaming_format": streaming_format,
                            }
                        )

                if streaming_format == "file_stream":
                    batch_path = batch_output.get("path")
                    streaming_path = streaming_input.get("options", {}).get("path")
                    if batch_path and streaming_path and batch_path != streaming_path:
                        format_issues.append(
                            {
                                "severity": "warning",
                                "message": f"Path mismatch: batch node '{batch_dep}' writes to "
                                f"'{batch_path}' but streaming node '{streaming_node}' reads from "
                                f"'{streaming_path}'. Ensure paths are coordinated.",
                                "batch_node": batch_dep,
                                "streaming_node": streaming_node,
                            }
                        )

        return format_issues

    @staticmethod
    def _validate_resource_conflicts(
        batch_nodes: List[str],
        streaming_nodes: List[str],
        node_configs: Dict[str, Dict[str, Any]],
    ) -> List[str]:
        """Validate resource conflicts between batch and streaming nodes."""
        (
            output_paths,
            kafka_topics,
            warnings,
        ) = PipelineValidator._collect_batch_resources(batch_nodes, node_configs)

        for streaming_node in streaming_nodes:
            node_config = node_configs.get(streaming_node, {})
            warnings.extend(
                PipelineValidator._check_streaming_conflicts_for_node(
                    streaming_node, node_config, output_paths, kafka_topics
                )
            )

        return warnings

    @staticmethod
    def _collect_batch_resources(
        batch_nodes: List[str], node_configs: Dict[str, Dict[str, Any]]
    ) -> Tuple[Dict[str, str], Dict[str, str], List[str]]:
        """Collects output paths and kafka topics used by batch nodes and reports conflicts."""
        output_paths: Dict[str, str] = {}
        kafka_topics: Dict[str, str] = {}
        warnings: List[str] = []

        def _register_output_path(path: str, node: str) -> None:
            """Register an output path and record a warning if already used."""
            existing = output_paths.get(path)
            if existing:
                warnings.append(
                    f"Output path conflict: batch nodes '{existing}' and "
                    f"'{node}' both write to '{path}'"
                )
            else:
                output_paths[path] = node

        def _register_kafka_topic(topic: str, node: str) -> None:
            """Register a kafka topic and record a warning if already used."""
            existing = kafka_topics.get(topic)
            if existing:
                warnings.append(
                    f"Kafka topic conflict: batch nodes '{existing}' and "
                    f"'{node}' both write to topic '{topic}'"
                )
            else:
                kafka_topics[topic] = node

        for batch_node in batch_nodes:
            node_config = node_configs.get(batch_node, {})
            output_config = _output_as_dict(node_config)

            output_path = output_config.get("path")
            if output_path:
                _register_output_path(output_path, batch_node)

            if output_config.get("format") == "kafka":
                topic = output_config.get("options", {}).get("topic")
                if topic:
                    _register_kafka_topic(topic, batch_node)

        return output_paths, kafka_topics, warnings

    @staticmethod
    def _check_streaming_conflicts_for_node(
        streaming_node: str,
        node_config: Dict[str, Any],
        output_paths: Dict[str, str],
        kafka_topics: Dict[str, str],
    ) -> List[str]:
        """Checks a single streaming node for conflicts against batch resources."""
        warnings: List[str] = []
        input_config = node_config.get("input", {})
        if input_config.get("format") == "file_stream":
            input_path = input_config.get("options", {}).get("path")
            if input_path and input_path in output_paths:
                # Intentionally no warning here per original logic (kept for compatibility)
                pass

        output_config = node_config.get("output", {})
        output_path = output_config.get("path")
        if output_path and output_path in output_paths:
            warnings.append(
                f"Output path conflict: batch node '{output_paths[output_path]}' and "
                f"streaming node '{streaming_node}' both write to '{output_path}'"
            )

        kafka_options = [
            input_config.get("options", {}),
            output_config.get("options", {}),
        ]
        for options in kafka_options:
            topic = options.get("topic")
            if topic and topic in kafka_topics:
                warnings.append(
                    f"Kafka topic conflict: batch node '{kafka_topics[topic]}' and "
                    f"streaming node '{streaming_node}' both use topic '{topic}'"
                )

        return warnings

    @staticmethod
    def _validate_streaming_requirements(
        streaming_nodes: List[str],
        node_configs: Dict[str, Dict[str, Any]],
        policy: FormatPolicy,
    ) -> List[str]:
        """Validate specific requirements for streaming nodes."""
        errors: List[str] = []
        for streaming_node in streaming_nodes:
            node_config = node_configs.get(streaming_node, {})
            node_errors: List[str] = []

            input_config = node_config.get("input", {})
            if not input_config:
                node_errors.append(
                    f"Streaming node '{streaming_node}' must have input configuration"
                )
                errors.extend(node_errors)
                continue

            input_format = input_config.get("format")
            if not input_format:
                node_errors.append(f"Streaming node '{streaming_node}' must specify input format")
                errors.extend(node_errors)
                continue

            if not policy.is_supported_input(input_format):
                node_errors.append(
                    f"Streaming node '{streaming_node}' has invalid input format '{input_format}'. "
                    f"Valid formats: {policy.get_supported_input_formats()}"
                )

            output_config = node_config.get("output", {})
            if not output_config:
                node_errors.append(
                    f"Streaming node '{streaming_node}' must have output configuration"
                )
                errors.extend(node_errors)
                continue

            output_format = output_config.get("format")
            if not output_format:
                node_errors.append(f"Streaming node '{streaming_node}' must specify output format")

            if input_format in policy.checkpoint_required_inputs:
                streaming_config = node_config.get("streaming", {})
                checkpoint = streaming_config.get("checkpoint_location")
                if not checkpoint:
                    node_errors.append(
                        f"Streaming node '{streaming_node}' with format '{input_format}' "
                        f"must specify checkpoint_location"
                    )

            errors.extend(node_errors)
        return errors

    @staticmethod
    def _validate_hybrid_format_compatibility(
        batch_nodes: List[str],
        streaming_nodes: List[str],
        node_configs: Dict[str, Dict[str, Any]],
        policy: FormatPolicy,
    ) -> List[str]:
        """Validate format compatibility in hybrid pipelines bidirectionally."""
        errors = []

        for streaming_node in streaming_nodes:
            streaming_config = node_configs.get(streaming_node, {})
            streaming_input = streaming_config.get("input", {})
            streaming_format = streaming_input.get("format", "").lower()

            dependencies = _get_node_dependencies_util(streaming_config)
            batch_deps = [dep for dep in dependencies if dep in batch_nodes]

            for batch_dep in batch_deps:
                batch_config = node_configs.get(batch_dep, {})
                batch_output = _output_as_dict(batch_config)
                batch_format = batch_output.get("format", "").lower()

                if batch_format and streaming_format:
                    if not policy.are_compatible(batch_format, streaming_format):
                        errors.append(
                            f"Incompatible format in hybrid pipeline: batch node '{batch_dep}' "
                            f"outputs format '{batch_format}' but streaming node '{streaming_node}' "
                            f"expects format '{streaming_format}'. "
                            f"Please ensure output format from batch matches expected input format for streaming."
                        )
                    else:
                        logger.debug(
                            f"Format compatibility OK: {batch_dep} ({batch_format}) -> "
                            f"{streaming_node} ({streaming_format})"
                        )
                else:
                    if not batch_format:
                        logger.warning(
                            f"Batch node '{batch_dep}' output format not specified. "
                            f"Cannot validate compatibility with streaming node '{streaming_node}'."
                        )
                    if not streaming_format:
                        logger.warning(
                            f"Streaming node '{streaming_node}' input format not specified. "
                            f"Cannot validate compatibility with batch node '{batch_dep}'."
                        )

        return errors

    @staticmethod
    def validate_dataframe_schema(result_df: Any) -> None:
        """Validate that the result DataFrame has a non-empty schema."""
        if result_df is None:
            raise ValueError("Result DataFrame is None")

        if isinstance(result_df, str):
            logger.debug("Result is a string (artifact URI). Skipping schema validation.")
            return

        if hasattr(result_df, "schema") and hasattr(result_df.schema, "fields"):
            PipelineValidator._validate_spark_df(result_df)
            return

        if hasattr(result_df, "columns") and hasattr(result_df, "empty"):
            PipelineValidator._validate_pandas_df(result_df)
            return

        if hasattr(result_df, "columns"):
            if not result_df.columns:
                raise ValueError("DataFrame has no columns defined")
            return

        raise ValueError(
            f"Unsupported DataFrame type: {type(result_df)}. "
            "Expected Spark or Pandas DataFrame with schema/columns."
        )

    @staticmethod
    def _validate_spark_df(result_df: Any) -> None:
        """Validate Spark DataFrame schema.

        Schema-only on purpose: probing for rows here (limit(1).count()) launches a
        Spark job per node that re-executes every upstream shuffle stage, and the
        save path immediately repeats the same probe via ``df.isEmpty()`` — which
        already warns and skips the write for empty frames.
        """
        if not result_df.schema.fields:
            raise ValueError("Spark DataFrame schema is empty - no fields defined")

    @staticmethod
    def _validate_pandas_df(result_df: Any) -> None:
        """Validate Pandas DataFrame columns and warn if empty."""
        if result_df.empty:
            logger.warning("Pandas DataFrame is empty (no rows)")
        if not list(result_df.columns):
            raise ValueError("Pandas DataFrame has no columns defined")
