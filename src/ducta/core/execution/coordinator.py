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

DAG-aware parallel execution: submission, completion, cascades.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from concurrent.futures import as_completed as thread_as_completed
from typing import Any, Callable, Dict, List, Optional, Set

from loguru import logger  # type: ignore

from ducta.core.errors import NodeTimeoutError, PipelineExecutionError
from ducta.core.execution.ml_builder import MLContextBuilder
from ducta.core.execution.state import ThreadSafeExecutionState
from ducta.core.ledger import ledger_for
from ducta.core.settings import CoreSettings


class ParallelCoordinator:
    """Coordinates parallel execution of nodes respecting DAG dependencies."""

    def __init__(
        self,
        context: Any,
        max_workers: int,
        node_timeout: int,
        is_ml_layer: bool,
        execute_callback: Callable,
        ml_builder: MLContextBuilder,
        settings: Optional[CoreSettings] = None,
    ) -> None:
        self.context = context
        self.settings = settings or CoreSettings.from_context(context)
        self._ledger = ledger_for(context)
        self.max_workers = max_workers
        self.node_timeout = node_timeout
        self.is_ml_layer = is_ml_layer
        self._execute_single_node = execute_callback
        self._ml_builder = ml_builder

    def coordinate(
        self,
        executor: ThreadPoolExecutor,
        execution_state: ThreadSafeExecutionState,
        dag: Dict[str, Set[str]],
        node_configs: Dict[str, Dict[str, Any]],
        start_date: str,
        end_date: str,
        ml_info: Dict[str, Any],
    ) -> None:
        """Coordinate the main execution loop until all nodes complete or failure occurs."""
        while execution_state.has_work_pending():
            self._submit_ready_nodes(
                execution_state=execution_state,
                executor=executor,
                start_date=start_date,
                end_date=end_date,
                ml_info=ml_info,
                node_configs=node_configs,
            )

            if execution_state.get_running_count() > 0:
                self._process_completed_nodes(
                    execution_state=execution_state,
                    dag=dag,
                )

        if execution_state.get_running_count() > 0:
            logger.warning(
                "Pipeline ended with {} unfinished futures",
                execution_state.get_running_count(),
            )
            self._handle_unfinished_futures(execution_state)

    def cleanup(
        self,
        execution_state: ThreadSafeExecutionState,
        ml_info: Dict[str, Any],
    ) -> None:
        """Cleanup resources and handle final state after execution completes."""
        self._cleanup_futures(execution_state.get_running_items_snapshot())

        if execution_state.is_failed():
            raise self._build_failure_error(execution_state)

        unexecuted = execution_state.get_unaccounted_nodes()
        if unexecuted:
            raise RuntimeError(
                f"Pipeline ended with {len(unexecuted)} node(s) never executed: "
                f"{sorted(unexecuted)}. Check that their dependencies are part of "
                "this pipeline."
            )

        if self.is_ml_layer:
            self._log_ml_pipeline_summary(execution_state.execution_results, ml_info)

        try:
            from ducta.console.ux.rich_logger import RichLoggerManager, print_process_separator

            console = RichLoggerManager.get_console()
            console.print()
            total_nodes = execution_state.get_completed_count()
            print_process_separator("summary", "EXECUTION SUMMARY", f"{total_nodes} nodes", console)
            console.print()
        except Exception:
            pass

        logger.info(
            f"Pipeline execution completed. Processed {execution_state.get_completed_count()} nodes."
        )

    @staticmethod
    def _build_failure_error(execution_state: ThreadSafeExecutionState) -> RuntimeError:
        """Build the pipeline-level error, chained to the node error that caused it."""
        first_failure = execution_state.get_first_failure()
        failed_nodes = sorted(
            name
            for name, result in execution_state.get_execution_results_copy().items()
            if isinstance(result, dict) and result.get("status") == "failed"
        )
        if not first_failure:
            return PipelineExecutionError(
                pipeline="", message="Pipeline execution failed due to node failures"
            )

        node_name, exception = first_failure
        detail = f"{type(exception).__name__}: {exception}" if exception else "unknown error"
        others = [n for n in failed_nodes if n != node_name]
        suffix = f" (also failed: {others})" if others else ""

        return PipelineExecutionError(
            pipeline="",
            message=f"Pipeline execution failed: node '{node_name}' raised {detail}{suffix}",
            failed_nodes=failed_nodes,
            cause=exception,
        )

    def cancel_all(self, running_snapshot: List) -> None:
        """Cancel all running futures from a snapshot of (future, node_info) pairs."""
        logger.warning("Cancelling {} running futures", len(running_snapshot))
        for future, node_info in running_snapshot:
            node_name = node_info["node_name"]
            logger.warning("Cancelling future for node '{}'", node_name)
            try:
                future.cancel()
            except Exception:
                logger.debug("Could not cancel future for node '{}'", node_name)

    def _submit_ready_nodes(
        self,
        execution_state: ThreadSafeExecutionState,
        executor: ThreadPoolExecutor,
        start_date: str,
        end_date: str,
        ml_info: Dict[str, Any],
        node_configs: Dict[str, Dict[str, Any]],
    ) -> None:
        """Submit ready nodes for execution with enhanced context."""
        while execution_state.get_running_count() < self.max_workers:
            node_name = execution_state.pop_ready_node()
            if not node_name:
                break

            try:
                from ducta.console.ux.rich_logger import log_node_start

                node_display = node_name.split(".")[-1] if "." in node_name else node_name
                log_node_start(node_display, "")
            except Exception:
                logger.info("Starting execution of node: {}", node_name)

            node_ml_info = self._ml_builder.prepare_node_ml_info(node_name, ml_info)

            future = executor.submit(
                self._execute_single_node, node_name, start_date, end_date, node_ml_info
            )
            execution_state.add_running_future(
                future,
                {
                    "node_name": node_name,
                    "start_time": time.time(),
                    "config": node_configs.get(node_name, {}),
                },
            )

    def _process_completed_nodes(
        self,
        execution_state: ThreadSafeExecutionState,
        dag: Dict[str, Set[str]],
    ) -> None:
        """Process completed nodes with timeout protection to prevent deadlock."""
        if execution_state.get_running_count() == 0:
            return

        future_list = execution_state.get_running_futures_snapshot()
        completed_futures = []
        max_timeout = self.settings.execution_timeout_seconds
        processing_timeout = min(30, max_timeout / 2)  # 30s or half of max

        # Never wait past the earliest running node's deadline. `_fail_timed_out_nodes`
        # only runs after this wait returns, so a flat 30s poll meant a
        # `node_timeout_seconds` below 30 was never enforced at all: the node ran
        # to completion and was recorded as a success, however far over budget.
        # Anything above 30s was already enforced (to within one poll) and is
        # unaffected.
        next_deadline = self._seconds_until_next_deadline(execution_state)
        if next_deadline is not None:
            processing_timeout = max(0.05, min(processing_timeout, next_deadline))

        try:
            for future in thread_as_completed(future_list, timeout=processing_timeout):
                completed_futures.append(future)
                node_info = execution_state.remove_running_future(future)
                if not node_info:
                    continue

                node_name = node_info["node_name"]
                should_break = self._handle_completed_future(
                    future, node_name, node_info, execution_state, dag
                )
                if should_break:
                    break

                if execution_state.has_ready_nodes():
                    break

        except TimeoutError:
            logger.warning(
                "Timeout ({}s) waiting for node completion. {} nodes still running.",
                processing_timeout,
                execution_state.get_running_count(),
            )
        except Exception as e:
            logger.error("Unexpected error in _process_completed_nodes: {}", e)
            execution_state.set_failed()

        for future in completed_futures:
            if execution_state.check_running_future(future):
                execution_state.remove_running_future(future)

        self._fail_timed_out_nodes(execution_state)

        if execution_state.is_failed():
            self.cancel_all(execution_state.get_running_items_snapshot())

    def _seconds_until_next_deadline(
        self, execution_state: ThreadSafeExecutionState
    ) -> Optional[float]:
        """Time until the earliest-expiring running node hits ``node_timeout``.

        None when nothing is running. Zero (or negative, clamped by the caller)
        when a node is already over budget.
        """
        now = time.time()
        remaining = [
            self.node_timeout - (now - info["start_time"])
            for _, info in execution_state.get_running_items_snapshot()
        ]
        return min(remaining) if remaining else None

    def _fail_timed_out_nodes(self, execution_state: ThreadSafeExecutionState) -> None:
        """Mark any running node that exceeded ``node_timeout`` as failed."""
        now = time.time()
        for future, node_info in execution_state.get_running_items_snapshot():
            # A finished future can still sit in `running`: `_process_completed_nodes`
            # breaks out of its `as_completed` loop as soon as new nodes become
            # ready, deferring the rest to the next pass. Judging those by elapsed
            # time alone reported a node that had completed inside its budget as a
            # timeout. The next pass reads its real result.
            if future.done():
                continue

            elapsed = now - node_info["start_time"]
            if elapsed <= self.node_timeout:
                continue

            node_name = node_info["node_name"]
            logger.error(
                "Node '{}' exceeded node timeout ({:.0f}s > {}s) — aborting pipeline. "
                "The underlying thread cannot be killed and may keep running until "
                "the process exits.",
                node_name,
                elapsed,
                self.node_timeout,
            )
            timeout_error = NodeTimeoutError(node_name, self.node_timeout)
            execution_state.mark_failed(
                node_name,
                {
                    "status": "failed",
                    "error": f"Node execution timeout exceeded ({self.node_timeout}s)",
                    "error_type": "TimeoutError",
                    "start_time": node_info["start_time"],
                    "end_time": now,
                    "config": node_info.get("config", {}),
                },
                exception=timeout_error,
            )
            execution_state.remove_running_future(future)
            try:
                future.cancel()
            except Exception:
                logger.debug("Could not cancel timed-out future for node '{}'", node_name)

    def _handle_completed_future(
        self,
        future,
        node_name: str,
        node_info: Dict[str, Any],
        execution_state: ThreadSafeExecutionState,
        dag: Dict[str, Set[str]],
    ) -> bool:
        """Handle a single completed future. Returns True if execution should break."""
        from ducta.check.core import QualityGateBlocked
        from ducta.gate.exceptions import MissingDependencyError

        try:
            future.result(timeout=5)
            self._handle_node_success(node_name, node_info, execution_state, dag)
            return False

        except TimeoutError as te:
            if future.done():
                self._handle_node_failure(node_name, node_info, execution_state, te)
            else:
                self._handle_node_timeout(node_name, node_info, execution_state, te)
            return True

        except QualityGateBlocked as gb:
            return self._handle_gate_block(node_name, node_info, execution_state, dag, gb)

        except MissingDependencyError as mde:
            return self._handle_missing_deps_skip(node_name, execution_state, dag, mde)

        except Exception as e:
            self._handle_node_failure(node_name, node_info, execution_state, e)
            return True

    def _handle_gate_block(
        self,
        node_name: str,
        node_info: Dict[str, Any],
        execution_state: ThreadSafeExecutionState,
        dag: Dict[str, Set[str]],
        gate_blocked: Exception,
    ) -> bool:
        """Apply a blocking quality gate's behavior. Returns True to abort the run."""
        gate_result = getattr(gate_blocked, "gate_result", None)
        behavior = (
            getattr(getattr(gate_result, "behavior", None), "value", None) or "skip_downstream"
        )

        if behavior == "stop_all":
            self._handle_node_failure(node_name, node_info, execution_state, gate_blocked)
            return True

        info = {
            "status": "gate_blocked",
            "error": str(gate_blocked),
            "start_time": node_info.get("start_time"),
            "end_time": time.time(),
            "config": node_info.get("config", {}),
        }
        execution_state.mark_gate_blocked(node_name, info)
        descendants = self._transitive_descendants(node_name, dag)
        for dep in descendants:
            reason = f"skipped: upstream quality gate blocked at '{node_name}'"
            execution_state.mark_skipped(dep, reason)
            self._record_trace(dep, "skipped", reason)

        logger.warning(
            "Quality gate blocked node '{}' (behavior=skip_downstream); skipping {} "
            "descendant(s): {}",
            node_name,
            len(descendants),
            sorted(descendants),
        )
        return False

    def _handle_missing_deps_skip(
        self,
        node_name: str,
        execution_state: ThreadSafeExecutionState,
        dag: Dict[str, Set[str]],
        missing_deps: Exception,
    ) -> bool:
        """Skip a node whose declared inputs aren't available yet (e.g. an
        upstream dependency hasn't run), and cascade the skip to its
        transitive descendants — same mechanism as a blocked quality gate,
        different trigger. Never a failure; returns False (doesn't abort the
        run).
        """
        reason = f"skipped: missing inputs — {missing_deps}"
        execution_state.mark_skipped(node_name, reason)
        self._record_trace(node_name, "skipped", reason)

        descendants = self._transitive_descendants(node_name, dag)
        for dep in descendants:
            dep_reason = f"skipped: missing inputs — upstream node '{node_name}' skipped"
            execution_state.mark_skipped(dep, dep_reason)
            self._record_trace(dep, "skipped", dep_reason)

        logger.warning(
            "Node '{}' skipped (missing dependencies); skipping {} descendant(s): {}",
            node_name,
            len(descendants),
            sorted(descendants),
        )
        return False

    def _record_trace(self, node_name: str, status: str, error: Optional[str]) -> None:
        """Append a node outcome to ``context._run_node_details`` (for the certificate).

        Runs in the single coordinate loop; ``list.append`` is atomic under the GIL.
        """
        node_config = (getattr(self.context, "nodes_config", {}) or {}).get(node_name, {}) or {}
        raw_out = node_config.get("output", [])
        outputs = list(raw_out.values()) if isinstance(raw_out, dict) else list(raw_out or [])
        self._ledger.record_node(
            name=node_name,
            status=status,
            outputs=outputs,
            error=error,
            node_type=node_config.get("type", "batch"),
        )

    @staticmethod
    def _transitive_descendants(node_name: str, dag: Dict[str, Set[str]]) -> Set[str]:
        """All nodes reachable from ``node_name`` via the dependents adjacency ``dag``."""
        seen: Set[str] = set()
        stack = list(dag.get(node_name, set()))
        while stack:
            nxt = stack.pop()
            if nxt in seen:
                continue
            seen.add(nxt)
            stack.extend(dag.get(nxt, set()))
        return seen

    def _handle_node_success(
        self,
        node_name: str,
        node_info: Dict[str, Any],
        execution_state: ThreadSafeExecutionState,
        dag: Dict[str, Set[str]],
    ) -> None:
        """Handle successful node completion."""
        result_dict = {
            "status": "success",
            "start_time": node_info["start_time"],
            "end_time": time.time(),
            "config": node_info["config"],
        }
        execution_state.mark_completed(node_name, result_dict)

        try:
            from ducta.console.ux.rich_logger import log_node_complete

            duration = time.time() - node_info["start_time"]
            node_display = node_name.split(".")[-1] if "." in node_name else node_name
            log_node_complete(node_display, duration)
        except Exception:
            logger.info("Node '{}' completed successfully", node_name)

        newly_ready = self._find_newly_ready_nodes(node_name, dag, execution_state)
        execution_state.add_to_ready_queue(newly_ready)

    def _handle_node_timeout(
        self,
        node_name: str,
        node_info: Dict[str, Any],
        execution_state: ThreadSafeExecutionState,
        timeout_error: BaseException,
    ) -> None:
        """Handle node timeout failure."""
        error_info = {
            "status": "failed",
            "error": "Node execution timeout exceeded",
            "error_type": "TimeoutError",
            "start_time": node_info["start_time"],
            "end_time": time.time(),
            "config": node_info["config"],
        }
        execution_state.mark_failed(node_name, error_info, exception=timeout_error)
        logger.error("Node '{}' exceeded timeout: {}", node_name, timeout_error)

    def _handle_node_failure(
        self,
        node_name: str,
        node_info: Dict[str, Any],
        execution_state: ThreadSafeExecutionState,
        error: Exception,
    ) -> None:
        """Handle node execution failure with elegant error reporting."""
        error_info = {
            "status": "failed",
            "error": str(error),
            "error_type": type(error).__name__,
            "start_time": node_info["start_time"],
            "end_time": time.time(),
            "config": node_info.get("config", {}),
        }
        execution_state.mark_failed(node_name, error_info, exception=error)

        try:
            from ducta.console.ux.error_analyzer import format_error_for_developer
            from ducta.console.ux.rich_logger import RichLoggerManager

            console = RichLoggerManager.get_console()
            format_error_for_developer(error, node_name, console)
        except Exception:
            logger.error("Node '{}' failed: {}", node_name, error)

    def _find_newly_ready_nodes(
        self,
        completed_node: str,
        dag: Dict[str, Set[str]],
        execution_state: ThreadSafeExecutionState,
    ) -> List[str]:
        """Find nodes that became ready after completing a node."""
        newly_ready = []
        running_nodes = execution_state.get_running_node_names()
        queued_nodes = execution_state.get_queued_node_names()

        for dependent in dag.get(completed_node, set()):
            if (
                execution_state.is_completed(dependent)
                or dependent in running_nodes
                or dependent in queued_nodes
            ):
                continue

            dependencies = execution_state.node_deps.get(dependent, [])

            if all(execution_state.is_completed(dep) for dep in dependencies):
                newly_ready.append(dependent)

        return newly_ready

    def _handle_unfinished_futures(self, execution_state: ThreadSafeExecutionState) -> None:
        """Handle any unfinished futures at the end of execution."""
        snapshot = execution_state.get_running_items_snapshot()
        if not snapshot:
            return

        logger.warning("Handling {} unfinished futures", len(snapshot))

        future_to_info = {future: info for future, info in snapshot}
        futures = list(future_to_info)

        try:
            for future in thread_as_completed(futures, timeout=5):
                node_info = future_to_info[future]
                node_name = node_info["node_name"]
                try:
                    future.result()
                    logger.info("Late completion of node '{}'", node_name)
                except Exception as e:
                    logger.error("Late failure of node '{}': {}", node_name, e)
                execution_state.remove_running_future(future)
        except TimeoutError:
            logger.warning("Grace period (5s) expired; cancelling remaining futures")

        for future in futures:
            if not future.done():
                node_info = future_to_info.get(future)
                if node_info:
                    logger.warning(
                        "Cancelling unfinished future for node '{}'",
                        node_info["node_name"],
                    )
                try:
                    future.cancel()
                except Exception:
                    pass

    def _cleanup_futures(self, running_snapshot: List) -> None:
        """Ensure all futures are properly cleaned up from a snapshot."""
        if not running_snapshot:
            return

        logger.debug("Cleaning up {} remaining futures", len(running_snapshot))

        for future, node_info in running_snapshot:
            node_name = node_info["node_name"]
            try:
                if not future.done():
                    future.cancel()
                else:
                    try:
                        future.result(timeout=0.1)
                    except Exception:
                        pass
            except Exception as e:
                logger.debug("Error during cleanup of future for '{}': {}", node_name, e)

    def _log_ml_pipeline_summary(
        self, execution_results: Dict[str, Any], ml_info: Dict[str, Any]
    ) -> None:
        """Log comprehensive ML pipeline execution summary."""
        successful_nodes = [
            name for name, result in execution_results.items() if result.get("status") == "success"
        ]
        failed_nodes = [
            name for name, result in execution_results.items() if result.get("status") == "failed"
        ]
        total_time = sum(
            r.get("end_time", 0) - r.get("start_time", 0) for r in execution_results.values()
        )

        logger.info(
            "ML pipeline summary — success: {}, failed: {}, project: {}, time: {:.2f}s",
            len(successful_nodes),
            len(failed_nodes),
            ml_info.get("project_name", "Unknown"),
            total_time,
        )
        if successful_nodes:
            logger.info("Successful nodes: {}", ", ".join(successful_nodes))
        if failed_nodes:
            logger.error("Failed nodes: {}", ", ".join(failed_nodes))

        try:
            from ducta.console.ux.rich_logger import RichLoggerManager, print_process_separator

            console = RichLoggerManager.get_console()
            console.print()
            print_process_separator(
                "summary",
                "ML PIPELINE SUMMARY",
                f"{len(successful_nodes)}/{len(successful_nodes) + len(failed_nodes)} nodes",
                console,
            )
            console.print()
        except Exception:
            pass
