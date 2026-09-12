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

Thread-safe execution state shared by the DAG coordinator's worker threads.
"""

from __future__ import annotations

import threading
from collections import deque
from typing import Any, Dict, List, Optional, Set


class ThreadSafeExecutionState:
    """Thread-safe execution state for parallel node execution."""

    def __init__(self, execution_order: List[str], node_configs: Dict[str, Dict[str, Any]]):
        self._lock = threading.RLock()
        self.ready_queue = deque()
        self.running: Dict = {}
        self.completed: Set[str] = set()
        self.failed = False
        self.execution_results: Dict[str, Any] = {}
        self.first_failure: Optional[tuple] = None
        self.skipped: Dict[str, str] = {}
        self.gate_blocked: Dict[str, Any] = {}
        from ducta.setting.dependency_inference import resolve_node_dependencies

        self.node_deps: Dict[str, List[str]] = resolve_node_dependencies(
            execution_order, node_configs, warn=False
        )
        self._initialize_ready_queue(execution_order)

    def _initialize_ready_queue(self, execution_order: List[str]) -> None:
        """Initialize queue with nodes that have no dependencies."""
        for node in execution_order:
            if not self.node_deps[node]:
                self.ready_queue.append(node)

    def mark_completed(self, node_name: str, result: Dict[str, Any]) -> None:
        """Thread-safe mark node as completed."""
        with self._lock:
            self.completed.add(node_name)
            self.execution_results[node_name] = result

    def mark_failed(
        self,
        node_name: str,
        error_info: Dict[str, Any],
        exception: Optional[BaseException] = None,
    ) -> None:
        """Thread-safe mark node as failed and store result."""
        with self._lock:
            self.failed = True
            self.execution_results[node_name] = error_info
            if self.first_failure is None:
                self.first_failure = (node_name, exception)

    def get_first_failure(self) -> Optional[tuple]:
        """Thread-safe read of the (node_name, exception) that failed the run."""
        with self._lock:
            return self.first_failure

    def mark_gate_blocked(self, node_name: str, info: Dict[str, Any]) -> None:
        """Record a node whose quality gate blocked (not a failure)."""
        with self._lock:
            self.gate_blocked[node_name] = info
            self.execution_results[node_name] = info

    def mark_skipped(self, node_name: str, reason: str) -> None:
        """Record a node skipped because an upstream gate blocked (not a failure)."""
        with self._lock:
            self.skipped[node_name] = reason

    def is_completed(self, node_name: str) -> bool:
        """Thread-safe check if node is completed."""
        with self._lock:
            return node_name in self.completed

    def add_to_ready_queue(self, nodes: List[str]) -> None:
        """Thread-safe add nodes to ready queue."""
        with self._lock:
            self.ready_queue.extend(nodes)

    def pop_ready_node(self) -> Optional[str]:
        """Thread-safe pop node from ready queue."""
        with self._lock:
            if self.ready_queue:
                return self.ready_queue.popleft()
            return None

    def add_running_future(self, future, node_info: Dict[str, Any]) -> None:
        """Thread-safe add running future."""
        with self._lock:
            self.running[future] = node_info

    def remove_running_future(self, future) -> Optional[Dict[str, Any]]:
        """Thread-safe remove running future."""
        with self._lock:
            return self.running.pop(future, None)

    def get_running_count(self) -> int:
        """Thread-safe get count of running nodes."""
        with self._lock:
            return len(self.running)

    def has_work_pending(self) -> bool:
        """Thread-safe check if there's work pending."""
        with self._lock:
            return bool(self.ready_queue or self.running) and not self.failed

    def has_ready_nodes(self) -> bool:
        """Thread-safe check if any node is waiting in the ready queue."""
        with self._lock:
            return bool(self.ready_queue)

    def get_running_futures_snapshot(self) -> List:
        """Thread-safe snapshot of running future keys."""
        with self._lock:
            return list(self.running.keys())

    def get_running_items_snapshot(self) -> List:
        """Thread-safe snapshot of running (future, node_info) pairs."""
        with self._lock:
            return list(self.running.items())

    def get_running_node_names(self) -> Set[str]:
        """Thread-safe get set of currently running node names."""
        with self._lock:
            return {info["node_name"] for info in self.running.values()}

    def get_queued_node_names(self) -> Set[str]:
        """Thread-safe get set of queued node names."""
        with self._lock:
            return set(self.ready_queue)

    def get_completed_count(self) -> int:
        """Thread-safe get count of completed nodes."""
        with self._lock:
            return len(self.completed)

    def get_execution_results_copy(self) -> Dict[str, Any]:
        """Thread-safe copy of execution results."""
        with self._lock:
            return dict(self.execution_results)

    def is_failed(self) -> bool:
        """Thread-safe check if execution has failed."""
        with self._lock:
            return self.failed

    def set_failed(self) -> None:
        """Thread-safe set failed flag."""
        with self._lock:
            self.failed = True

    def check_running_future(self, future) -> Optional[Dict[str, Any]]:
        """Thread-safe check if a future is still in running dict."""
        with self._lock:
            return self.running.get(future)

    def get_unaccounted_nodes(self) -> Set[str]:
        """Nodes with no recorded outcome (not completed, skipped, or gate-blocked)."""
        with self._lock:
            return set(self.node_deps) - self.completed - set(self.skipped) - set(self.gate_blocked)
