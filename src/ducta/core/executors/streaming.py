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

StreamingExecutor: streaming pipelines and their resource-conflict checks.
"""

from __future__ import annotations

import json
from contextlib import ExitStack
from typing import Any, Dict, List, Optional, Set

from loguru import logger  # type: ignore

from ducta.core.executors.base import BaseExecutor
from ducta.core.settings import CoreSettings
from ducta.core.utils import extract_pipeline_nodes
from ducta.setting.contexts import Context
from ducta.stream.pipeline_manager import StreamingPipelineManager


class StreamingExecutor(BaseExecutor):
    """Executor for streaming pipelines."""

    def __init__(self, context: Context, settings: Optional[CoreSettings] = None):
        super().__init__(context, settings=settings)
        max_streaming_pipelines = self.settings.max_streaming_pipelines
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
            # `list_running_pipelines()` returns status snapshots, which carry the
            # pipeline definition under "pipeline_config" and have no top-level
            # "nodes" key. Passing the snapshot itself yielded no nodes, so every
            # resource set came back empty and this check never once reported a
            # conflict.
            running_resources = self._extract_pipeline_resources(
                running.get("pipeline_config") or {}
            )

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
