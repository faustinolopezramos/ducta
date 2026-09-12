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

HybridExecutor: a batch phase followed by a streaming phase.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Set

from loguru import logger  # type: ignore

from ducta.core.dependency_resolver import DependencyResolver
from ducta.core.executors.base import BaseExecutor
from ducta.core.ledger import ledger_for
from ducta.core.pipeline_state import NodeType, UnifiedPipelineState
from ducta.core.pipeline_validator import PipelineValidator
from ducta.core.settings import CoreSettings
from ducta.core.utils import extract_pipeline_nodes
from ducta.setting.contexts import Context
from ducta.stream.constants import PipelineType
from ducta.stream.pipeline_manager import StreamingPipelineManager


class HybridExecutor(BaseExecutor):
    """Executor for hybrid pipelines."""

    def __init__(self, context: Context, settings: Optional[CoreSettings] = None):
        super().__init__(context, settings=settings)
        max_streaming_pipelines = self.settings.max_streaming_pipelines
        self.streaming_manager = StreamingPipelineManager(context, max_streaming_pipelines)

    def execute(
        self,
        pipeline_name: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        model_version: Optional[str] = None,
        hyperparams: Optional[Dict[str, Any]] = None,
        execution_mode: Optional[str] = "async",
    ) -> Dict[str, Any]:
        self._mlops_pipeline_name = pipeline_name
        self.node_executor.pipeline_name = pipeline_name
        logger.info("Executing hybrid pipeline: {}", pipeline_name)

        pipeline = self._get_pipeline_config(pipeline_name)
        pipeline_nodes = extract_pipeline_nodes(pipeline)
        node_configs = self._get_node_configs(pipeline_nodes)

        validation_result = PipelineValidator.validate_hybrid_pipeline(
            pipeline, node_configs, self.context.format_policy
        )

        if not validation_result["is_valid"]:
            raise ValueError("Hybrid pipeline validation failed")

        self._apply_global_seed()

        self.unified_state = UnifiedPipelineState()
        self.unified_state.set_pipeline_status("running")

        ml_info = self._build_ml_info(pipeline_name, model_version, hyperparams)
        ml_info["pipeline_type"] = pipeline.get("type", PipelineType.HYBRID.value)

        self._log_pipeline_start(pipeline_name, ml_info, "HYBRID")

        sanity_reports = self._run_preflight_sanity_checks(node_configs)
        if sanity_reports:
            self._sanity_reports = sanity_reports

        mlops_integration, mlops_run_id = self._start_mlops_integration(
            pipeline, pipeline_name, ml_info
        )
        self.node_executor.set_mlops_context(
            mlops_integration.mlops_context if mlops_integration else None
        )
        if mlops_integration and mlops_run_id:
            ml_info["mlops_integration"] = mlops_integration
            ml_info["mlops_run_id"] = mlops_run_id

        try:
            self._register_nodes_in_unified_state(
                validation_result["batch_nodes"],
                validation_result["streaming_nodes"],
                node_configs,
            )
            self.unified_state.set_streaming_stopper(
                lambda eid: self.streaming_manager.stop_pipeline(eid, graceful=True)
            )
            result = self._execute_unified_hybrid_pipeline(
                validation_result["batch_nodes"],
                validation_result["streaming_nodes"],
                node_configs,
                start_date or self.settings.start_date,
                end_date or self.settings.end_date,
                ml_info,
                execution_mode,
            )
            succeeded = result.get("status") != "failed"
            self.unified_state.set_pipeline_status("completed" if succeeded else "failed")
            self._end_mlops_run(
                success=succeeded,
                mlops_integration=mlops_integration,
                mlops_run_id=mlops_run_id,
            )
            self._aggregate_and_persist_quality_summary()
            return result
        except Exception:
            self.unified_state.set_pipeline_status("failed")
            self._end_mlops_run(
                success=False,
                mlops_integration=mlops_integration,
                mlops_run_id=mlops_run_id,
            )
            raise
        finally:
            if self.unified_state:
                self.unified_state.cleanup()
            from ducta.gate import handoff

            handoff.clear(self.context)

    def _register_nodes_in_unified_state(
        self,
        batch_nodes: List[str],
        streaming_nodes: List[str],
        node_configs: Dict[str, Dict[str, Any]],
    ) -> None:
        """Register all nodes in unified state."""
        from ducta.setting.dependency_inference import resolve_node_dependencies

        all_nodes = list(batch_nodes) + list(streaming_nodes)
        resolved = resolve_node_dependencies(all_nodes, node_configs)

        for node_name in batch_nodes:
            self.unified_state.register_node(node_name, NodeType.BATCH, resolved[node_name])

        for node_name in streaming_nodes:
            self.unified_state.register_node(node_name, NodeType.STREAMING, resolved[node_name])

    def _execute_unified_hybrid_pipeline(
        self,
        batch_nodes: List[str],
        streaming_nodes: List[str],
        node_configs: Dict[str, Dict[str, Any]],
        start_date: str,
        end_date: str,
        ml_info: Dict[str, Any],
        execution_mode: str,
    ) -> Dict[str, Any]:
        """Execute hybrid pipeline with enhanced error handling."""
        execution_result = {
            "batch_execution": {},
            "streaming_execution_ids": [],
            "status": "success",
            "errors": [],
        }

        try:
            batch_results = self._execute_batch_phase(
                batch_nodes, node_configs, start_date, end_date, ml_info
            )
            execution_result["batch_execution"] = batch_results

            # Neither a skip nor a blocking quality gate is a failure: in both
            # cases the node did not run, but nothing is broken. What they do
            # mean is that the streaming phase would consume data that was never
            # produced, so both halt the run — without reporting it as an error.
            #
            # `gate_blocked` used to be lumped in with `failed` here, which made
            # the same `skip_downstream` gate abort a hybrid pipeline while
            # leaving a batch one to finish as RunStatus.GATE_BLOCKED. A
            # `stop_all` gate is unaffected: that path goes through the
            # coordinator's failure handling, so it arrives here as "failed".
            batch_failures = [
                node for node, result in batch_results.items() if result["status"] == "failed"
            ]
            batch_halts = [
                node
                for node, result in batch_results.items()
                if result["status"] in ("skipped", "gate_blocked")
            ]

            if batch_failures:
                execution_result["status"] = "failed"
                execution_result["errors"] = [
                    f"Batch node failed: {node} - {batch_results[node].get('error')}"
                    for node in batch_failures
                ]
                logger.error("Batch phase failed, skipping streaming execution")
                return execution_result

            if batch_halts:
                logger.warning(
                    "Batch phase left {} node(s) unmaterialized ({}); skipping the streaming "
                    "phase, which would otherwise consume data they never produced.",
                    len(batch_halts),
                    sorted(batch_halts),
                )
                # The facade raises the run to RunStatus.GATE_BLOCKED from
                # `node_executor.gate_blocked`; this phase reports no error.
                return execution_result

            streaming_execution_ids = self._execute_streaming_phase(
                streaming_nodes, node_configs, execution_mode
            )
            execution_result["streaming_execution_ids"] = streaming_execution_ids

            # The batch phase was clean and there were streaming nodes to start,
            # so starting none of them is a failure. This used to report success:
            # `_execute_streaming_phase` marked every node completed the moment
            # `start_pipeline` returned an id, which proves only that the startup
            # work was queued.
            if streaming_nodes and not streaming_execution_ids:
                execution_result["status"] = "failed"
                execution_result["errors"].append(
                    "Streaming phase started no queries; see the log for the per-node "
                    f"reason. Nodes: {sorted(streaming_nodes)}"
                )

        except Exception as e:
            execution_result["status"] = "failed"
            execution_result["errors"].append(f"Hybrid pipeline failed: {str(e)}")
            logger.error("Hybrid pipeline execution failed: {}", e)

        return execution_result

    def _execute_batch_phase(
        self,
        batch_nodes: List[str],
        node_configs: Dict[str, Dict[str, Any]],
        start_date: str,
        end_date: str,
        ml_info: Dict[str, Any],
    ) -> Dict[str, Dict[str, Any]]:
        """Execute the hybrid pipeline's batch nodes through the normal batch engine.

        This used to be a hand-written sequential ``for`` loop over the
        topological order, which made hybrid a second, weaker implementation of
        batch: no parallelism, no per-node ``retry``, no quality-gate skip
        cascade, no per-node tracing, and a different failure shape. Every one of
        those features had to be written twice or, in practice, only once — the
        divergence is why hybrid quietly missed six execution phases that batch
        had.

        ``UnifiedPipelineState`` still tracks the batch nodes, because that is
        what lets a *streaming* node depend on a batch node and be stopped when
        that dependency fails. It is now a bookkeeping mirror of the run rather
        than the thing that drives it.
        """
        PipelineValidator.validate_no_dag_cycles(batch_nodes, node_configs)
        dag = DependencyResolver.build_dependency_graph(batch_nodes, node_configs)
        execution_order = DependencyResolver.topological_sort(dag)

        for node in execution_order:
            self.unified_state.start_node_execution(node)

        try:
            self.node_executor.execute_nodes_parallel(
                execution_order, node_configs, dag, start_date, end_date, ml_info
            )
        except Exception as e:
            self._mirror_batch_phase_state(execution_order, failure=e)
            raise

        return self._mirror_batch_phase_state(execution_order, failure=None)

    def _mirror_batch_phase_state(
        self, execution_order: List[str], failure: Optional[BaseException]
    ) -> Dict[str, Dict[str, Any]]:
        """Reflect the batch engine's outcome into the unified state and a result map.

        The engine records each node's fate on the run trace; this replays that
        onto ``unified_state`` so cross-type dependencies (a streaming node
        waiting on a batch node) still see accurate completion, and so a failed
        batch node still stops the streaming queries that depend on it.
        """
        trace = {
            record.get("name"): record
            for record in ledger_for(self.context).node_details
            if isinstance(record, dict)
        }
        gate_blocked = getattr(self.node_executor, "gate_blocked", None) or {}

        results: Dict[str, Dict[str, Any]] = {}
        for node in execution_order:
            record = trace.get(node) or {}
            status = record.get("status")

            if node in gate_blocked:
                results[node] = {"status": "gate_blocked", "error": str(gate_blocked[node])}
                # Recorded as a failure in the unified state (which only models
                # completed/failed) so no streaming node can start on a
                # dependency that never materialized. The *run* is not a failure
                # — see `_execute_unified_hybrid_pipeline`, which halts before
                # the streaming phase without setting an error status.
                self.unified_state.fail_node_execution(node, results[node]["error"])
            elif status == "success":
                results[node] = {"status": "completed"}
                self.unified_state.complete_node_execution(node)
            elif status == "skipped":
                results[node] = {"status": "skipped", "reason": record.get("error") or "skipped"}
            elif status == "failed":
                error = record.get("error") or (str(failure) if failure else "node failed")
                results[node] = {"status": "failed", "error": error}
                self.unified_state.fail_node_execution(node, error)
            else:
                # No trace entry: the run aborted before this node ever started.
                reason = "not executed (pipeline aborted earlier)"
                results[node] = {"status": "skipped", "reason": reason}

        return results

    #: How long to wait for the streaming manager's startup pass before giving up
    #: on learning what started. Generous: a node whose source is still warming up
    #: retries for `streaming_node_start_retries` attempts by design.
    STREAMING_STARTUP_TIMEOUT_SECONDS = 300.0

    def _execute_streaming_phase(
        self,
        streaming_nodes: List[str],
        node_configs: Dict[str, Dict[str, Any]],
        execution_mode: str,
    ) -> List[str]:
        """Start the streaming nodes as a sub-pipeline and record what happened.

        Two things here used to be taken on faith. First, the batch nodes this
        phase depends on are not part of the sub-pipeline handed to the manager,
        so a streaming node declaring ``depends_on: [<a batch node>]`` had that
        name rejected as undefined — before any query was created, taking the
        whole phase down with it. ``satisfied_dependencies`` tells the manager
        which predecessors are already done.

        Second, ``start_pipeline`` is asynchronous: the execution id it returns
        means the startup work was *queued*, not that any query exists. Marking
        every node completed on the strength of that id reported a clean success
        for runs in which nothing started. Now the phase waits for the startup
        pass and reads the real per-node outcome.
        """
        execution_ids: List[str] = []
        startable = [n for n in streaming_nodes if self.unified_state.start_node_execution(n)]
        if not startable:
            return execution_ids

        satisfied = self._completed_batch_nodes()
        stream_pipeline_name = f"{self._mlops_pipeline_name or 'hybrid'}__streaming"
        try:
            execution_id = self.streaming_manager.start_pipeline(
                stream_pipeline_name,
                {"nodes": startable, "satisfied_dependencies": sorted(satisfied)},
            )
        except Exception as e:
            logger.error("Failed to start streaming nodes {}: {}", startable, e)
            for node in startable:
                self.unified_state.fail_node_execution(node, str(e))
            raise

        started = self._record_streaming_startup(execution_id, startable)
        if started:
            execution_ids.append(execution_id)

        if execution_mode == "sync" and execution_ids:
            self._wait_for_streaming_completion(execution_ids)

        return execution_ids

    def _completed_batch_nodes(self) -> Set[str]:
        """Batch nodes that finished, so the streaming phase can declare them met."""
        from ducta.core.pipeline_state import NodeStatus

        completed: Set[str] = set()
        for name in self.unified_state.list_nodes(NodeType.BATCH):
            if self.unified_state.get_node_status(name) is NodeStatus.COMPLETED:
                completed.add(name)
        return completed

    def _record_streaming_startup(self, execution_id: str, startable: List[str]) -> List[str]:
        """Wait for the startup pass and mirror its real outcome per node."""
        self.streaming_manager.wait_for_pipeline_started(
            execution_id, timeout=self.STREAMING_STARTUP_TIMEOUT_SECONDS
        )
        status = self.streaming_manager.get_pipeline_status(execution_id) or {}
        skipped = status.get("skipped_nodes") or {}
        failed = status.get("failed_nodes") or {}
        # `query_statuses`, not `queries`: get_pipeline_status strips the live
        # query handles and reports their names under this key instead.
        running = set(status.get("query_statuses") or {})

        started: List[str] = []
        for node in startable:
            if node in skipped:
                self.unified_state.fail_node_execution(node, f"not started: {skipped[node]}")
            elif node in failed:
                self.unified_state.fail_node_execution(node, f"failed to start: {failed[node]}")
            elif node in running:
                self.unified_state.register_streaming_query(node, execution_id)
                self.unified_state.complete_node_execution(node)
                started.append(node)
            else:
                # Neither started nor accounted for: say so rather than assume.
                self.unified_state.fail_node_execution(
                    node, "the streaming manager reported no outcome for this node"
                )

        if len(started) != len(startable):
            logger.error(
                "Streaming phase started {}/{} node(s); not started: {}",
                len(started),
                len(startable),
                sorted(set(startable) - set(started)),
            )
        return started

    def _wait_for_streaming_completion(self, execution_ids: List[str], timeout_minutes=60):
        """Wait for all streaming executions to reach a terminal state."""
        deadline = time.time() + timeout_minutes * 60
        for eid in execution_ids:
            remaining = max(0.0, deadline - time.time())
            if not self.streaming_manager.wait_for_pipeline_done(eid, timeout=remaining):
                logger.warning("Timeout reached while waiting for streaming queries")
                return
