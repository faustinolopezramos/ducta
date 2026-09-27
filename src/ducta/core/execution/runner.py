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
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Set

from loguru import logger  # type: ignore

from ducta.check import QualityOutputManager
from ducta.core.errors import NodeCancelledError, NodeNotFoundError
from ducta.core.execution.cancellation import (
    is_cancelled,
    tag_current_thread,
    untag_current_thread,
)
from ducta.core.execution.coordinator import ParallelCoordinator
from ducta.core.execution.ingestion import IngestionExecutor
from ducta.core.execution.loader import FunctionLoader
from ducta.core.execution.ml_builder import MLContextBuilder
from ducta.core.execution.output import OutputWriter, report_node_failure
from ducta.core.execution.quality import QualityCheckExecutor
from ducta.core.execution.state import ThreadSafeExecutionState
from ducta.core.execution_context import node_id_var
from ducta.core.ledger import ledger_for
from ducta.core.resource_manager import ResourceType, get_resource_manager
from ducta.core.settings import (
    DEFAULT_NODE_TIMEOUT_SECONDS,
    MAX_TIMEOUT_SECONDS,
    CoreSettings,
    clamp_timeout,
)


class NodeExecutor:
    """Thin orchestrator: initializes the 6 helper components and provides the public API."""

    DEFAULT_NODE_TIMEOUT = DEFAULT_NODE_TIMEOUT_SECONDS
    MAX_NODE_TIMEOUT_SECONDS = MAX_TIMEOUT_SECONDS

    def __init__(
        self,
        context,
        input_loader,
        output_manager,
        max_workers: int = 4,
        timeout: Optional[int] = None,
        mlops_context: Optional[Any] = None,
        quality_output_manager: Optional[QualityOutputManager] = None,
        settings: Optional[CoreSettings] = None,
    ):
        self.context = context
        self.settings = settings or CoreSettings.from_context(context)
        self._ledger = ledger_for(context)
        self.input_loader = input_loader
        self.output_manager = output_manager
        self.quality_output_manager = quality_output_manager
        self.max_workers = max_workers
        self.mlops_context = mlops_context
        self.is_ml_layer = getattr(context, "is_ml_layer", False)
        self.pipeline_name: Optional[str] = None
        self.gate_blocked: Dict[str, Any] = {}
        #: Nodes the coordinator skipped (missing inputs, or an upstream skip
        #: cascading down). Surfaced next to gate_blocked so the run result can
        #: say the pipeline did not do all of its work.
        self.skipped: Dict[str, str] = {}
        self.node_timeout = (
            clamp_timeout("node_timeout_seconds", timeout)
            if timeout
            else self.settings.node_timeout_seconds
        )
        logger.debug("NodeExecutor initialized with timeout: {}s", self.node_timeout)

        self._function_loader = FunctionLoader(
            context, is_ml_layer=self.is_ml_layer, settings=self.settings
        )
        self._quality_executor = QualityCheckExecutor(
            context, quality_output_manager, settings=self.settings
        )
        self._output_writer = OutputWriter(
            output_manager, context, is_ml_layer=self.is_ml_layer, settings=self.settings
        )
        self._ml_builder = MLContextBuilder(context, mlops_context, self.is_ml_layer)
        self._trace_lock = threading.Lock()
        #: Live `run_in_process` worker processes, so shutdown can reap them.
        self._children: Set[Any] = set()
        self._ingestion_executor = IngestionExecutor(
            context=context,
            output_writer=self._output_writer,
            quality_executor=self._quality_executor,
            settings=self.settings,
        )
        self._coordinator = ParallelCoordinator(
            context=context,
            max_workers=max_workers,
            node_timeout=self.node_timeout,
            is_ml_layer=self.is_ml_layer,
            execute_callback=self.execute_single_node,
            ml_builder=self._ml_builder,
            settings=self.settings,
        )

    def set_mlops_context(self, mlops_context: Optional[Any]) -> None:
        """Wire the real MLOps context into node functions' ``ml_context['mlops_context']``."""
        self.mlops_context = mlops_context
        self._ml_builder.mlops_context = mlops_context

    def execute_single_node(
        self,
        node_name: str,
        start_date: str,
        end_date: str,
        ml_info: Dict[str, Any],
    ) -> None:
        """Execute a single node with enhanced ML support and error handling."""
        start_time = time.perf_counter()
        node_status = "success"
        node_error: Optional[str] = None
        resource_manager = get_resource_manager()

        node_id_var.set(node_name)

        logger.info("[node_status] node_id={} status=running", node_name)

        self._set_scheduler_pool(node_name)
        # Tag this node's Spark jobs so a timeout can cancel them on the cluster.
        tag_current_thread(self.context, node_name)

        with resource_manager.resource_context(f"node_{node_name}"):
            try:
                node_config = self._get_node_config(node_name)

                if self._should_run_in_process(node_config):
                    self._run_node_in_subprocess(
                        node_name, node_config, start_date, end_date, ml_info
                    )
                    logger.info("[node_status] node_id={} status=success", node_name)
                    return

                node_type = node_config.get("type", "batch")
                if node_type == "ingestion":
                    self._ingestion_executor.execute(
                        node_name,
                        node_config,
                        start_date,
                        end_date,
                        ml_info,
                        pipeline_name=self.pipeline_name,
                    )
                    logger.info("[node_status] node_id={} status=success", node_name)
                    return

                function = self._function_loader.load(node_config)
                input_dfs = self.input_loader.load_inputs(
                    node_config, node_name, start_date=start_date, end_date=end_date
                )
                input_param_names = self.input_loader.get_input_param_names(node_config)

                sanity_report = self._quality_executor.run_sanity_checks(
                    input_dfs,
                    node_config,
                    node_name,
                    pipeline_type=ml_info.get("pipeline_type"),
                    pipeline_name=self.pipeline_name,
                )

                self._quality_executor.persist_report(
                    sanity_report,
                    "sanity",
                    "sanity_checks",
                    node_name,
                    node_config,
                    ml_info,
                    pipeline_name=self.pipeline_name,
                )

                for idx, df in enumerate(input_dfs):
                    if df is not None:
                        resource_type = resource_manager.detect_resource_type(df)
                        resource_manager.register(
                            resource=df,
                            resource_type=resource_type,
                            context_id=f"node_{node_name}",
                            metadata={"index": idx, "stage": "input"},
                        )

                command = self._ml_builder.create_command(
                    function,
                    input_dfs,
                    start_date,
                    end_date,
                    node_name,
                    ml_info,
                    node_config,
                    input_param_names,
                )

                node_retries = int(node_config.get("retry", 0) or 0)
                if node_retries > 0:
                    from ducta.check import QualityChecksFailed
                    from ducta.check.core import QualityGateBlocked
                    from ducta.core.resilience import RetryPolicy

                    result_df = RetryPolicy(
                        max_retries=node_retries,
                        delay=1,
                        backoff_factor=2.0,
                        non_retryable=(QualityGateBlocked, QualityChecksFailed),
                    ).execute(command.execute)
                else:
                    result_df = command.execute()

                self._warn_if_split_not_applied(command, node_name)

                if result_df is not None:
                    # Register (and materialize) BEFORE the checks, not after.
                    #
                    # What follows scans this DataFrame several times over: one
                    # Spark action per quality check (`DFAdapter.count()` does not
                    # memoize), one for the fingerprint, one for the write. Without
                    # caching, Spark recomputes the node's whole lineage for each —
                    # the README's own three-check example pays for it four times.
                    # `resource_context` (above) already unpersists on exit, so
                    # caching here needs no new lifecycle.
                    resource_type = resource_manager.detect_resource_type(result_df)
                    if resource_type == ResourceType.SPARK_DF:
                        try:
                            # Cache before registering, so the registered handle is
                            # the cached one and `resource_context` unpersists it.
                            result_df = result_df.cache()
                        except Exception as exc:  # noqa: BLE001 — caching is an optimization
                            logger.debug("Could not cache '{}' output: {}", node_name, exc)
                    resource_manager.register(
                        resource=result_df,
                        resource_type=resource_type,
                        context_id=f"node_{node_name}",
                        metadata={"stage": "output"},
                    )

                dq_report = None
                if result_df is not None:
                    dq_report = self._quality_executor.run_dq_checks(
                        result_df, node_config, node_name, pipeline_name=self.pipeline_name
                    )

                self._quality_executor.persist_report(
                    dq_report,
                    "dq",
                    "data_quality",
                    node_name,
                    node_config,
                    ml_info,
                    pipeline_name=self.pipeline_name,
                )

                self._output_writer.save(
                    result_df,
                    node_config,
                    node_name,
                    start_date,
                    end_date,
                    ml_info,
                )

                logger.info("[node_status] node_id={} status=success", node_name)

            except Exception as e:
                from ducta.check.core import QualityGateBlocked
                from ducta.gate.exceptions import MissingDependencyError

                # This trace is the node's one entry in the run certificate, so
                # the status has to be what the run actually means. A node whose
                # inputs were not there is *skipped*, not failed — the
                # coordinator's _handle_missing_deps_skip treats it that way and
                # says so ("Never a failure"). Recording "failed" here put two
                # contradictory entries for one node in the certificate and
                # flipped the whole run to failed. Classifying it here also gets
                # the atomic `--node` path right, where no coordinator runs.
                if isinstance(e, QualityGateBlocked):
                    node_status = "gate_blocked"
                elif isinstance(e, MissingDependencyError):
                    node_status = "skipped"
                else:
                    node_status = "failed"
                node_error = str(e)
                logger.info("[node_status] node_id={} status={}", node_name, node_status)
                if node_status == "skipped":
                    # A skip is an expected outcome; the caller logs it. Running
                    # it through the developer error formatter would print a
                    # failure box for something that did not fail.
                    logger.debug("Node '{}' skipped: {}", node_name, e)
                else:
                    report_node_failure(e, node_name)
                raise
            finally:
                untag_current_thread(self.context)
                duration = time.perf_counter() - start_time
                logger.debug("Node '{}' executed in {:.2f}s", node_name, duration)
                self._record_node_trace(node_name, node_status, duration, node_error)

    @staticmethod
    def _warn_if_split_not_applied(command: Any, node_name: str) -> None:
        """Warn when a node declared a `split` but never called split_dataframe/kfold_splits."""
        split_config = getattr(command, "split", None)
        if not split_config:
            return
        split_was_applied = getattr(command, "split_was_applied", None)
        if split_was_applied is not None and not split_was_applied():
            logger.warning(
                "Node '{}' declared a 'split' but never called split_dataframe/"
                "kfold_splits — the run certificate records the configured split, "
                "but nothing enforces the node actually applied it.",
                node_name,
            )

    def _should_run_in_process(self, node_config: Dict[str, Any]) -> bool:
        """Whether this node opts into process isolation for CPU-bound work."""
        if not node_config.get("run_in_process", False):
            return False
        if not self.settings.env:
            logger.warning(
                "Node asked for run_in_process but the active environment could not be "
                "resolved, so a worker cannot rebuild the Context. Running inline."
            )
            return False
        return True

    def shutdown(self) -> None:
        """Terminate any `run_in_process` worker still alive (best-effort)."""
        for proc in list(getattr(self, "_children", ())):
            _stop_process(proc)
        self._children = set()

    def _run_node_in_subprocess(
        self,
        node_name: str,
        node_config: Dict[str, Any],
        start_date: str,
        end_date: str,
        ml_info: Dict[str, Any],
    ) -> None:
        """Run one node in a worker process; re-raise its failure here."""
        from ducta.check.core import QualityGateBlocked
        from ducta.core.node_worker import (
            OUTCOME_GATE_BLOCKED,
            OUTCOME_MISSING_DEPENDENCY,
            OUTCOME_SUCCESS,
            build_node_payload,
        )
        from ducta.gate.exceptions import MissingDependencyError

        payload = build_node_payload(
            node_name,
            env=self.settings.env,
            ml_info=ml_info,
            pipeline_name=self.pipeline_name,
            start_date=start_date,
            end_date=end_date,
            base_path=str(getattr(self.context, "base_path", "") or "") or None,
            output_path=str(getattr(self.context, "output_path", "") or "") or None,
        )

        logger.debug("Running node '{}' in a worker process (run_in_process)", node_name)
        outcome = self._run_child(node_name, payload)
        status = outcome.get("status")
        if status == OUTCOME_SUCCESS:
            return
        error = outcome.get("error") or "worker reported no detail"
        if status == OUTCOME_GATE_BLOCKED:
            raise QualityGateBlocked(error)
        if status == OUTCOME_MISSING_DEPENDENCY:
            raise MissingDependencyError(error)
        raise RuntimeError(f"Node '{node_name}' failed in worker process: {error}")

    def _run_child(
        self, node_name: str, payload: Dict[str, Any], target: Optional[Any] = None
    ) -> Dict[str, Any]:
        """Run the node in its own process, terminating it if the node is cancelled.

        ``target`` defaults to :func:`ducta.core.node_worker.run_node_in_child`;
        tests substitute a function that never returns.
        """
        import multiprocessing

        from ducta.core.node_worker import run_node_in_child

        ctx = multiprocessing.get_context("spawn")
        parent_conn, child_conn = ctx.Pipe(duplex=False)
        proc = ctx.Process(
            target=target or run_node_in_child,
            args=(payload, child_conn),
            name=f"ducta-node-{node_name}",
            daemon=True,
        )
        proc.start()
        child_conn.close()
        self._children.add(proc)
        try:
            while True:
                if parent_conn.poll(0.2):
                    try:
                        outcome = parent_conn.recv()
                    except EOFError:
                        outcome = None
                    proc.join(timeout=10)
                    break
                if is_cancelled(self.context, node_name):
                    _stop_process(proc)
                    raise NodeCancelledError(node_name)
                if not proc.is_alive():
                    outcome = parent_conn.recv() if parent_conn.poll(0) else None
                    break
        finally:
            parent_conn.close()
            self._children.discard(proc)
        if outcome is None:
            return {
                "status": "failed",
                "error": f"worker process exited with code {proc.exitcode} and no result",
            }
        return outcome

    def _record_node_trace(
        self, node_name: str, status: str, duration: float, error: Optional[str]
    ) -> None:
        """Append this node's outcome to ``context._run_node_details`` for the certificate."""
        node_config = self.context.nodes_config.get(node_name, {}) or {}
        raw_out = node_config.get("output", [])
        outputs = list(raw_out.values()) if isinstance(raw_out, dict) else list(raw_out or [])
        self._ledger.record_node(
            name=node_name,
            status=status,
            duration_seconds=duration,
            outputs=outputs,
            error=error,
            node_type=node_config.get("type", "batch"),
        )

    def execute_nodes_parallel(
        self,
        execution_order: List[str],
        node_configs: Dict[str, Dict[str, Any]],
        dag: Dict[str, Set[str]],
        start_date: str,
        end_date: str,
        ml_info: Dict[str, Any],
    ) -> None:
        """
        Execute nodes in parallel while respecting dependencies with ML enhancements.
        Orchestrates parallel execution by delegating to ParallelCoordinator.
        """
        execution_state = self._initialize_execution_state(execution_order, node_configs)
        executor = ThreadPoolExecutor(max_workers=self.max_workers)
        try:
            original_exc: Optional[BaseException] = None
            try:
                self._coordinator.coordinate(
                    executor=executor,
                    execution_state=execution_state,
                    dag=dag,
                    node_configs=node_configs,
                    start_date=start_date,
                    end_date=end_date,
                    ml_info=ml_info,
                )
            except Exception as e:
                original_exc = e
                logger.error("Pipeline execution failed: {}", e)
                self._coordinator.cancel_all(execution_state.get_running_items_snapshot())
                raise
            finally:
                try:
                    self._coordinator.cleanup(
                        execution_state=execution_state,
                        ml_info=ml_info,
                    )
                except Exception as cleanup_exc:
                    if original_exc is not None:
                        logger.error(
                            "cleanup() raised while an exception was already "
                            "propagating ({}); keeping the original exception: {}",
                            original_exc,
                            cleanup_exc,
                        )
                    else:
                        raise
        finally:
            executor.shutdown(wait=False)
            # Worker processes outlive the thread pool unless closed; a run
            # that used run_in_process would otherwise leak them.
            self.shutdown()
            # Inside the `finally`, not after it. These are what the run result
            # (and therefore the CLI and the API) uses to say *which* nodes were
            # gate-blocked or skipped, and `coordinate`/`cleanup` raise on any
            # node failure — so on exactly the runs where that context matters
            # most, both dicts stayed empty and the caller reported a bare
            # failure with no mention of the gate or the skipped branch.
            self.gate_blocked = dict(execution_state.gate_blocked)
            self.skipped = dict(execution_state.skipped)

    def _initialize_execution_state(
        self,
        execution_order: List[str],
        node_configs: Dict[str, Dict[str, Any]],
    ) -> ThreadSafeExecutionState:
        """Initialize thread-safe execution state with queues and tracking structures."""
        state = ThreadSafeExecutionState(execution_order, node_configs)
        logger.debug("Initial ready nodes: {}", list(state.ready_queue))
        return state

    def _set_scheduler_pool(self, node_name: str) -> None:
        """Bind the current worker thread to a per-node FAIR scheduler pool."""
        spark = getattr(self.context, "spark", None)
        if spark is None:
            return
        try:
            spark.sparkContext.setLocalProperty("spark.scheduler.pool", f"node_{node_name}")
        except Exception as e:
            logger.debug("Could not set scheduler pool for node '{}': {}", node_name, e)

    def _get_node_config(self, node_name: str) -> Dict[str, Any]:
        """Get configuration for a specific node with enhanced error handling."""
        node = self.context.nodes_config.get(node_name)
        if not node:
            raise NodeNotFoundError(node_name, list(self.context.nodes_config.keys()))
        return node


def _stop_process(proc: Any) -> None:
    """terminate(), then kill() if it does not exit within 5 seconds."""
    if not proc.is_alive():
        return
    proc.terminate()
    proc.join(timeout=5)
    if proc.is_alive():
        proc.kill()
        proc.join(timeout=5)
