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

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

from loguru import logger  # type: ignore


class CircuitBreakerState(Enum):
    """States of the circuit breaker."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Blocking requests due to failures
    HALF_OPEN = "half_open"  # Testing if system recovered


class CircuitBreaker:
    """Circuit breaker with auto-reset and half-open state."""

    def __init__(
        self,
        failure_threshold: int = 3,
        timeout: timedelta = timedelta(minutes=5),
        half_open_max_calls: int = 1,
    ):
        """Initialize circuit breaker."""
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.half_open_max_calls = half_open_max_calls

        self._lock = threading.RLock()
        self.state = CircuitBreakerState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: Optional[datetime] = None
        self.half_open_calls = 0

    def record_success(self) -> None:
        """Record successful operation."""
        with self._lock:
            self.failure_count = 0

            if self.state == CircuitBreakerState.HALF_OPEN:
                self.success_count += 1
                logger.info(
                    f"Circuit breaker success in HALF_OPEN state "
                    f"({self.success_count}/{self.half_open_max_calls})"
                )

                if self.success_count >= self.half_open_max_calls:
                    self._close_circuit()

    def record_failure(self) -> bool:
        """Record failed operation."""
        with self._lock:
            self.failure_count += 1
            self.last_failure_time = datetime.now()

            if self.state == CircuitBreakerState.HALF_OPEN:
                logger.warning("Circuit breaker failure in HALF_OPEN state - reopening circuit")
                self._open_circuit()
                return True

            elif self.state == CircuitBreakerState.CLOSED:
                if self.failure_count >= self.failure_threshold:
                    logger.error(
                        f"Circuit breaker threshold exceeded "
                        f"({self.failure_count}/{self.failure_threshold}) - opening circuit"
                    )
                    self._open_circuit()
                    return True

            return False

    def can_execute(self) -> bool:
        """Check if execution is allowed."""
        with self._lock:
            if self.state == CircuitBreakerState.CLOSED:
                return True

            elif self.state == CircuitBreakerState.OPEN:
                if self.last_failure_time is None:
                    return False

                time_since_failure = datetime.now() - self.last_failure_time
                if time_since_failure >= self.timeout:
                    logger.info(
                        f"Circuit breaker timeout expired ({time_since_failure.total_seconds():.1f}s) "
                        "- transitioning to HALF_OPEN"
                    )
                    self._transition_to_half_open()
                    self.half_open_calls = 1
                    return True

                return False

            elif self.state == CircuitBreakerState.HALF_OPEN:
                if self.half_open_calls < self.half_open_max_calls:
                    self.half_open_calls += 1
                    return True
                return False

            return False

    def _open_circuit(self) -> None:
        """Transition to OPEN state."""
        self.state = CircuitBreakerState.OPEN
        logger.critical("Circuit breaker OPEN - blocking operations")

    def _close_circuit(self) -> None:
        """Transition to CLOSED state (normal operation)."""
        self.state = CircuitBreakerState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.half_open_calls = 0
        logger.info("Circuit breaker CLOSED - normal operation resumed")

    def _transition_to_half_open(self) -> None:
        """Transition to HALF_OPEN state (testing recovery)."""
        self.state = CircuitBreakerState.HALF_OPEN
        self.success_count = 0
        self.half_open_calls = 0
        logger.info("Circuit breaker HALF_OPEN - testing system recovery")

    def get_state(self) -> CircuitBreakerState:
        """Get current circuit breaker state."""
        with self._lock:
            return self.state

    def get_failure_count(self) -> int:
        """Get current failure count (thread-safe)."""
        with self._lock:
            return self.failure_count

    def reset(self) -> None:
        """Manually reset circuit breaker to CLOSED state."""
        with self._lock:
            self._close_circuit()
            logger.info("Circuit breaker manually reset")


class NodeStatus(Enum):
    """Status of a node in the pipeline execution."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"
    CANCELLED = "cancelled"


class NodeType(Enum):
    """Type of pipeline node."""

    BATCH = "batch"
    STREAMING = "streaming"


@dataclass
class NodeExecutionInfo:
    """Information about a node's execution state."""

    node_name: str
    node_type: NodeType
    status: NodeStatus = NodeStatus.PENDING
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    output_path: Optional[str] = None
    error: Optional[str] = None
    dependencies: List[str] = field(default_factory=list)
    dependents: Set[str] = field(default_factory=set)
    execution_metadata: Dict[str, Any] = field(default_factory=dict)
    resources: List[Any] = field(default_factory=list)


class UnifiedPipelineState:
    """Unified state for coordinating batch and streaming pipeline execution."""

    def __init__(
        self,
        circuit_breaker_threshold: int = 3,
        circuit_breaker_timeout_minutes: int = 5,
    ):
        """Initialize the unified pipeline state."""
        self._lock = threading.RLock()
        self._nodes: Dict[str, NodeExecutionInfo] = {}
        self._circuit_breaker = CircuitBreaker(
            failure_threshold=circuit_breaker_threshold,
            timeout=timedelta(minutes=circuit_breaker_timeout_minutes),
            half_open_max_calls=2,
        )

        self._pipeline_status: str = "initializing"
        self._batch_outputs: Dict[str, str] = {}
        self._streaming_queries: Dict[str, Any] = {}
        self._streaming_stopper: Optional[Callable[[str], bool]] = None
        self._cross_dependencies: Dict[str, Set[str]] = {}

    def register_node(
        self,
        node_name: str,
        node_type: NodeType,
        dependencies: Optional[List[str]] = None,
    ) -> None:
        """Register a node in the unified state."""
        with self._lock:
            if node_name in self._nodes:
                raise ValueError(f"Node '{node_name}' already registered")

            deps = dependencies or []
            self._nodes[node_name] = NodeExecutionInfo(
                node_name=node_name,
                node_type=node_type,
                dependencies=list(deps),
            )

            for dep in deps:
                if dep in self._nodes:
                    self._nodes[dep].dependents.add(node_name)

            for other_name, other_info in self._nodes.items():
                if other_name == node_name:
                    continue
                if node_name in other_info.dependencies:
                    self._nodes[node_name].dependents.add(other_name)

            if node_type == NodeType.STREAMING:
                batch_deps = [
                    dep
                    for dep in deps
                    if dep in self._nodes and self._nodes[dep].node_type == NodeType.BATCH
                ]
                if batch_deps:
                    self._cross_dependencies[node_name] = set(batch_deps)

            logger.debug(
                f"Registered {node_type.value} node '{node_name}' with dependencies: {dependencies}"
            )

    def start_node_execution(self, node_name: str) -> bool:
        """Start execution of a node if dependencies are ready and circuit allows."""
        with self._lock:
            if node_name not in self._nodes:
                raise ValueError(f"Node '{node_name}' not registered")

            node = self._nodes[node_name]

            if not self._circuit_breaker.can_execute():
                logger.warning(
                    f"Circuit breaker blocked execution of node '{node_name}' - "
                    f"state: {self._circuit_breaker.get_state().value}"
                )
                return False

            if not self._are_dependencies_ready(node_name):
                return False

            node.status = NodeStatus.RUNNING
            node.start_time = time.time()

            logger.info(f"Started execution of {node.node_type.value} node '{node_name}'")
            return True

    def complete_node_execution(
        self,
        node_name: str,
        output_path: Optional[str] = None,
        execution_metadata: Optional[Dict[str, Any]] = None,
        quality_score: Optional[float] = None,
    ) -> None:
        """Mark a node as completed successfully."""
        with self._lock:
            if node_name not in self._nodes:
                raise ValueError(f"Node '{node_name}' not registered")

            node = self._nodes[node_name]
            node.status = NodeStatus.COMPLETED
            node.end_time = time.time()
            node.output_path = output_path
            meta = dict(execution_metadata or {})
            if quality_score is not None:
                meta["quality_score"] = quality_score
            node.execution_metadata = meta

            self._circuit_breaker.record_success()

            if node.node_type == NodeType.BATCH and output_path:
                self._batch_outputs[node_name] = output_path

            execution_time = node.end_time - (node.start_time or node.end_time)
            logger.info(
                f"Completed {node.node_type.value} node '{node_name}' in {execution_time:.2f}s"
            )

            self._notify_dependents(node_name)

    def fail_node_execution(self, node_name: str, error: str) -> None:
        """Record a node failure and propagate it to dependent nodes."""
        with self._lock:
            if node_name not in self._nodes:
                raise ValueError(f"Node '{node_name}' not registered")

            node = self._nodes[node_name]

            should_open = self._circuit_breaker.record_failure()

            node.status = NodeStatus.FAILED
            node.end_time = time.time()
            if should_open:
                logger.critical(
                    f"Circuit breaker triggered for node '{node_name}' - "
                    f"state: {self._circuit_breaker.get_state().value}"
                )
                node.error = f"Circuit breaker triggered: {error}"
            else:
                node.error = error

        self._propagate_failure(node_name)

    def register_streaming_query(self, node_name: str, query: Any) -> None:
        """Register a streaming query for tracking."""
        with self._lock:
            self._streaming_queries[node_name] = query
            logger.debug(f"Registered streaming query for node '{node_name}'")

    def set_streaming_stopper(self, stopper: Callable[[str], bool]) -> None:
        """Register a stopper function to stop queries by execution_id (string)."""
        with self._lock:
            self._streaming_stopper = stopper

    def get_batch_output_path(self, node_name: str) -> Optional[str]:
        """Get the output path of a batch node."""
        with self._lock:
            return self._batch_outputs.get(node_name)

    def is_node_ready(self, node_name: str) -> bool:
        """Check if a node is ready to execute."""
        with self._lock:
            return self._are_dependencies_ready(node_name)

    def get_node_status(self, node_name: str) -> Optional[NodeStatus]:
        """Get the status of a node."""
        with self._lock:
            node = self._nodes.get(node_name)
            return node.status if node else None

    def list_nodes(self, node_type: Optional[NodeType] = None) -> List[str]:
        """Registered node names, optionally narrowed to one node type.

        Callers that need "which batch nodes are in this run" were otherwise
        reaching into ``_nodes`` directly, outside the lock that guards it.
        """
        with self._lock:
            return [
                name
                for name, info in self._nodes.items()
                if node_type is None or info.node_type == node_type
            ]

    def get_ready_nodes(self) -> List[str]:
        """Get list of nodes ready for execution."""
        with self._lock:
            ready_nodes = []
            for node_name, node in self._nodes.items():
                if node.status == NodeStatus.PENDING and self._are_dependencies_ready(node_name):
                    ready_nodes.append(node_name)
            return ready_nodes

    def get_pipeline_summary(self) -> Dict[str, Any]:
        """Get summary of the pipeline state."""
        with self._lock:
            summary = {
                "total_nodes": len(self._nodes),
                "batch_nodes": len(
                    [n for n in self._nodes.values() if n.node_type == NodeType.BATCH]
                ),
                "streaming_nodes": len(
                    [n for n in self._nodes.values() if n.node_type == NodeType.STREAMING]
                ),
                "status_breakdown": {},
                "cross_dependencies": len(self._cross_dependencies),
                "pipeline_status": self._pipeline_status,
                "circuit_breaker_state": self._circuit_breaker.get_state().value,
                "circuit_breaker_failure_count": self._circuit_breaker.get_failure_count(),
                # Legacy field for backward compatibility
                "circuit_breaker_open": self._circuit_breaker.get_state()
                == CircuitBreakerState.OPEN,
            }

            for status in NodeStatus:
                count = len([n for n in self._nodes.values() if n.status == status])
                summary["status_breakdown"][status.value] = count

            return summary

    def validate_cross_dependencies(self) -> List[str]:
        """Validate cross-dependencies between batch and streaming nodes."""
        warnings = []

        with self._lock:
            for streaming_node, batch_deps in self._cross_dependencies.items():
                for batch_dep in batch_deps:
                    batch_node = self._nodes.get(batch_dep)
                    if not batch_node:
                        warnings.append(
                            f"Streaming node '{streaming_node}' depends on "
                            f"non-existent batch node '{batch_dep}'"
                        )
                    elif batch_node.node_type != NodeType.BATCH:
                        warnings.append(
                            f"Cross-dependency error: '{streaming_node}' -> '{batch_dep}' "
                            f"but '{batch_dep}' is not a batch node"
                        )

        return warnings

    @staticmethod
    def _stop_streaming_query(query_or_id: Any, stopper: Optional[Callable[[str], Any]]) -> bool:
        """Stop a streaming query by handle (``.stop()``) or, for a string id,
        via *stopper*. Returns whether the stop succeeded; exceptions from
        ``.stop()``/*stopper* propagate to the caller, which owns logging and
        any status bookkeeping."""
        if hasattr(query_or_id, "stop"):
            query_or_id.stop()
            return True
        if stopper is None:
            return False
        return bool(stopper(query_or_id))

    def _attempt_stop_by_handle(
        self,
        streaming_node: str,
        streaming_query: Any,
        stopped_nodes: List[str],
        failed_batch_node: str,
    ) -> None:
        """Called with no lock held — `.stop()` can block (e.g. Spark waits
        for the current micro-batch); only the status write is locked."""
        try:
            self._stop_streaming_query(streaming_query, None)
            with self._lock:
                self._nodes[streaming_node].status = NodeStatus.CANCELLED
            stopped_nodes.append(streaming_node)
            logger.warning(
                f"Stopped streaming node '{streaming_node}' due to "
                f"failed dependency '{failed_batch_node}'"
            )
        except Exception as e:
            logger.error(f"Failed to stop streaming node '{streaming_node}': {e}")

    def _attempt_stop_by_id(
        self,
        streaming_node: str,
        query_id: str,
        stopped_nodes: List[str],
        failed_batch_node: str,
    ) -> None:
        """Called with no lock held — the stopper call can block; only the
        status write is locked."""
        try:
            if not self._streaming_stopper:
                logger.error(f"No stopper configured to stop streaming node '{streaming_node}'")
                return

            if self._stop_streaming_query(query_id, self._streaming_stopper):
                with self._lock:
                    self._nodes[streaming_node].status = NodeStatus.CANCELLED
                stopped_nodes.append(streaming_node)
                logger.warning(
                    f"Stopped streaming node '{streaming_node}' by id due to "
                    f"failed dependency '{failed_batch_node}'"
                )
            else:
                logger.error(f"Stopper failed to stop streaming node '{streaming_node}'")
        except Exception as e:
            logger.error(f"Error invoking stopper for '{streaming_node}': {e}")

    def stop_dependent_streaming_nodes(self, failed_batch_node: str) -> List[str]:
        """Stop streaming nodes that depend on a failed batch node."""
        stopped_nodes: List[str] = []
        to_stop: List[Any] = []

        with self._lock:
            for streaming_node, batch_deps in self._cross_dependencies.items():
                if failed_batch_node not in batch_deps:
                    continue

                streaming_query = self._streaming_queries.get(streaming_node)
                if not streaming_query:
                    continue

                to_stop.append((streaming_node, streaming_query))

        for streaming_node, streaming_query in to_stop:
            if hasattr(streaming_query, "stop"):
                self._attempt_stop_by_handle(
                    streaming_node,
                    streaming_query,
                    stopped_nodes,
                    failed_batch_node,
                )
            elif isinstance(streaming_query, str):
                self._attempt_stop_by_id(
                    streaming_node,
                    streaming_query,
                    stopped_nodes,
                    failed_batch_node,
                )

        return stopped_nodes

    def _are_dependencies_ready(self, node_name: str) -> bool:
        """Check if all dependencies of a node are completed."""
        node = self._nodes.get(node_name)
        if not node:
            return False

        for dep in node.dependencies:
            dep_node = self._nodes.get(dep)
            if not dep_node or dep_node.status != NodeStatus.COMPLETED:
                return False

        return True

    def _notify_dependents(self, completed_node: str) -> None:
        """Notify dependent nodes that a node has completed."""
        node = self._nodes.get(completed_node)
        if not node:
            return

        for dependent in node.dependents:
            if self._are_dependencies_ready(dependent):
                logger.debug(
                    f"Node '{dependent}' is now ready (dependency '{completed_node}' completed)"
                )

    def _propagate_failure(self, failed_node: str) -> None:
        """Propagate failure to dependent nodes with circuit breaker awareness."""
        circuit_state = self._circuit_breaker.get_state()
        if circuit_state == CircuitBreakerState.OPEN:
            logger.error(
                "Circuit breaker OPEN - propagating failure to all dependent nodes. "
                f"System will attempt recovery in {self._circuit_breaker.timeout.total_seconds():.0f}s"
            )

        node = self._nodes.get(failed_node)
        if node and node.node_type == NodeType.BATCH:
            self.stop_dependent_streaming_nodes(failed_node)

    def set_pipeline_status(self, status: str) -> None:
        """Set the overall pipeline status."""
        with self._lock:
            self._pipeline_status = status
            logger.debug(f"Pipeline status changed to: {status}")

    def register_resource(self, node_name: str, resource_type: str, resource: Any):
        """Register a resource for cleanup tracking"""
        with self._lock:
            if node_name not in self._nodes:
                raise ValueError(f"Node '{node_name}' not registered")

            self._nodes[node_name].resources.append((resource_type, resource))
            logger.debug(f"Registered {resource_type} resource for node '{node_name}'")

    def _stop_query_by_handle(self, node_name: str, query: Any) -> None:
        try:
            self._stop_streaming_query(query, None)
            logger.info(f"Stopped streaming query handle for node '{node_name}'")
        except Exception as e:
            logger.warning(f"Error stopping streaming query handle for '{node_name}': {e}")

    def _stop_query_by_id(self, node_name: str, query_id: str) -> None:
        try:
            if self._streaming_stopper:
                self._stop_streaming_query(query_id, self._streaming_stopper)
                logger.info(f"Requested stop by id for streaming node '{node_name}'")
            else:
                logger.error(f"No stopper configured to stop streaming node '{node_name}'")
        except Exception as e:
            logger.warning(f"Error requesting stop by id for '{node_name}': {e}")

    def _stop_query(self, node_name: str, query: Any) -> None:
        if hasattr(query, "stop"):
            self._stop_query_by_handle(node_name, query)
        elif isinstance(query, str):
            self._stop_query_by_id(node_name, query)

    def _release_resource(self, node, res_type: str, resource: Any) -> None:
        try:
            if res_type == "spark_dataframe" and hasattr(resource, "unpersist"):
                resource.unpersist()
            elif hasattr(resource, "close"):
                resource.close()
            logger.debug(f"Released {res_type} for node '{node.node_name}'")
        except Exception as e:
            logger.error(f"Error releasing resource for '{node.node_name}': {str(e)}")

    def cleanup(self) -> None:
        """Clean up all resources and stop active streaming queries"""
        with self._lock:
            queries_to_stop = list(self._streaming_queries.items())
            resources_to_release = [
                (node, res_type, resource)
                for node in self._nodes.values()
                for res_type, resource in node.resources
            ]
            self._reset_state()
            logger.debug("Pipeline state has been reset")

        # Stopping queries can block (e.g. Spark waits for the current
        # micro-batch) and unpersist()/close() can be slow I/O — done outside
        # the lock, same pattern as stop_dependent_streaming_nodes, so
        # another thread touching pipeline state isn't blocked for however
        # long these take.
        for node_name, query in queries_to_stop:
            self._stop_query(node_name, query)

        for node, res_type, resource in resources_to_release:
            self._release_resource(node, res_type, resource)

    def _reset_state(self):
        """Reset all state containers."""
        self._streaming_queries.clear()
        self._nodes.clear()
        self._batch_outputs.clear()
        self._cross_dependencies.clear()
        self._pipeline_status = "initializing"
        self._circuit_breaker.reset()
