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

PipelineExecutor: the public facade that picks an executor, runs chains and emits certificates.
"""

from __future__ import annotations

import gc
import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from loguru import logger  # type: ignore

from ducta.core.errors import (
    ChainExecutionError,
    ChainStepNotRefreshedError,
    PipelineExecutionError,
    PreflightError,
)
from ducta.core.executors.batch import BatchExecutor
from ducta.core.executors.hybrid import HybridExecutor
from ducta.core.executors.streaming import StreamingExecutor
from ducta.core.ledger import RunLedger
from ducta.core.pipeline_validator import PipelineValidator
from ducta.core.results import PipelineRunResult, RunStatus
from ducta.core.run_lock import RunLock, RunLockSettings, output_keys
from ducta.core.settings import CHAIN_ON_GATE_BLOCKED_CONTINUE, EVIDENCE_SIGNED, CoreSettings
from ducta.core.utils import extract_pipeline_nodes
from ducta.gate.constants import WriteMode
from ducta.setting.contexts import Context
from ducta.setting.environments import sanitize_env_for_path
from ducta.stream.constants import PipelineType


class PipelineExecutor:
    """Orchestrator that delegates to specialized executors."""

    def __init__(
        self,
        context: Context,
        config_directory: Optional[str] = None,
        settings: Optional[CoreSettings] = None,
    ):
        self.context = context
        self.config_directory = config_directory
        # Resolved once and handed to every sub-executor, so the facade and the
        # executors it builds can never disagree about the configuration.
        self.settings = settings or CoreSettings.from_context(context)
        self._batch_executor: Optional[BatchExecutor] = None
        self._streaming_executor: Optional[StreamingExecutor] = None
        self._hybrid_executor: Optional[HybridExecutor] = None
        self._reuse_materialized_global = self.settings.chain_reuse_materialized
        self._staleness_check = self.settings.chain_staleness_check
        self._force_reuse = False
        self._force_rerun_all = False
        self.reused_pipelines: List[str] = []

    @property
    def batch_executor(self) -> BatchExecutor:
        """Lazy initialization of BatchExecutor."""
        if self._batch_executor is None:
            self._batch_executor = BatchExecutor(self.context, settings=self.settings)
        return self._batch_executor

    @property
    def streaming_executor(self) -> StreamingExecutor:
        """Lazy initialization of StreamingExecutor."""
        if self._streaming_executor is None:
            self._streaming_executor = StreamingExecutor(self.context, settings=self.settings)
        return self._streaming_executor

    @property
    def hybrid_executor(self) -> HybridExecutor:
        """Lazy initialization of HybridExecutor."""
        if self._hybrid_executor is None:
            self._hybrid_executor = HybridExecutor(self.context, settings=self.settings)
        return self._hybrid_executor

    def run_pipeline(
        self,
        pipeline_name: str,
        node_name: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        model_version: Optional[str] = None,
        hyperparams: Optional[Dict[str, Any]] = None,
        execution_mode: Optional[str] = "async",
        node_names: Optional[List[str]] = None,
    ) -> PipelineRunResult:
        """Execute one pipeline and return a typed description of what happened.

        ``node_names`` runs only those nodes of a batch pipeline, in dependency
        order among themselves; what they read from outside the set is read as
        it was last materialized — like a single node, but several.
        """
        # A long-lived process (the API) re-imports edited project code between
        # runs; fingerprints cached from an earlier run would certify the old
        # source. Each run hashes the code it actually executes.
        from ducta.core.code_fingerprint import clear_cache

        clear_cache()
        self._run_preflight(pipeline_name)

        pipeline = self.batch_executor._get_pipeline_config(pipeline_name)
        pipeline_type = pipeline.get("type", PipelineType.BATCH.value)

        if pipeline_type in [
            PipelineType.BATCH.value,
            PipelineType.ML.value,
            PipelineType.HYBRID.value,
        ]:
            requires_dates = pipeline.get("requires_dates", True)
            PipelineValidator.validate_required_params(
                pipeline_name,
                start_date,
                end_date,
                self.settings.start_date,
                self.settings.end_date,
                requires_dates=requires_dates,
            )

        if pipeline_type == PipelineType.STREAMING.value and execution_mode != "sync":
            execution_id = self.streaming_executor.execute(pipeline_name, execution_mode)
            return PipelineRunResult(
                pipeline=pipeline_name,
                status=RunStatus.RUNNING,
                streaming_execution_ids=[execution_id] if execution_id else [],
                # A continuous query has no end, so nothing here can seal a
                # certificate over it. Said out loud rather than left as an
                # unexplained `certificate_path is None`.
                certificate_error=("asynchronous streaming runs do not emit a run certificate"),
            )

        import uuid
        from datetime import datetime, timezone

        run_id = uuid.uuid4().hex
        # Before anything reads data: a run that cannot get its outputs to
        # itself must not start. Raises PipelineLockedError — nothing ran, so
        # no ledger and no certificate.
        run_lock = self._acquire_run_lock(pipeline, pipeline_name, node_name, run_id)
        ledger = RunLedger.start(self.context, run_id)
        started_at = datetime.now(timezone.utc)
        result = PipelineRunResult(pipeline=pipeline_name, run_id=run_id)
        try:
            if pipeline_type in (PipelineType.BATCH.value, PipelineType.ML.value):
                self.batch_executor.node_subset = list(node_names) if node_names else None
                try:
                    self.batch_executor.execute(
                        pipeline_name, node_name, start_date, end_date, model_version, hyperparams
                    )
                finally:
                    self.batch_executor.node_subset = None
                self._collect_batch_outcome(result)
            elif pipeline_type == PipelineType.HYBRID.value:
                hybrid_result = self.hybrid_executor.execute(
                    pipeline_name, start_date, end_date, model_version, hyperparams, execution_mode
                )
                self._collect_hybrid_outcome(result, hybrid_result)
            elif pipeline_type == PipelineType.STREAMING.value:
                execution_id = self.streaming_executor.execute(pipeline_name, execution_mode)
                if execution_id:
                    result.streaming_execution_ids.append(execution_id)
            else:
                raise ValueError(f"Unsupported pipeline type: {pipeline_type}")
        except Exception as e:
            result.add_error(str(e))
            raise
        finally:
            try:
                result.absorb_trace(ledger.node_details)
                result.resolve_status()
            except Exception as bookkeeping_exc:  # noqa: BLE001 — never mask the real error
                logger.debug("Could not fold the run trace into the result: {}", bookkeeping_exc)
            if run_lock.lost:
                ledger.note_gap(
                    "the run lock lease was lost during the run; another run may have "
                    "written the same outputs concurrently"
                )
            run_lock.release()
            cert_path, cert_error = self._emit_run_certificate(
                pipeline_name=pipeline_name,
                run_id=run_id,
                started_at=started_at,
                ended_at=datetime.now(timezone.utc),
                status=result.status.value,
                error=result.primary_error,
            )
            result.certificate_path = cert_path
            result.certificate_error = cert_error
            if cert_error and self.settings.require_run_certificate and result.ok:
                result.add_error(f"run certificate required but not written: {cert_error}")
            # Only a whole-pipeline run makes the pipeline "materialized".
            if result.ok and node_name is None and not node_names:
                self._record_chain_state(pipeline_name, pipeline_type, start_date, end_date)

        if result.failed:
            failure = PipelineExecutionError(
                pipeline=pipeline_name,
                message=(
                    f"Pipeline '{pipeline_name}' failed: "
                    f"{result.primary_error or 'no error detail'}"
                ),
                failed_nodes=[n.name for n in result.failed_nodes],
            )
            failure.run_result = result  # type: ignore[attr-defined]
            raise failure
        return result

    def _acquire_run_lock(
        self,
        pipeline: Dict[str, Any],
        pipeline_name: str,
        node_name: Optional[str],
        run_id: str,
    ) -> RunLock:
        """Lock every output this run will write (see ``ducta.core.run_lock``)."""
        s = self.settings
        lock = RunLock(
            RunLockSettings(
                enabled=s.run_lock_enabled,
                backend=s.run_lock_backend,
                ttl_seconds=s.run_lock_ttl_seconds,
                on_conflict=s.run_lock_on_conflict,
                wait_timeout_seconds=s.run_lock_wait_timeout_seconds,
                lock_dir=s.run_lock_dir,
            ),
            output_keys(self.context, pipeline, node_name),
            pipeline=pipeline_name,
            run_id=run_id,
        )
        lock.acquire()
        return lock

    def _collect_batch_outcome(self, result: PipelineRunResult) -> None:
        """Fold the batch executor's non-raising outcomes into the run result."""
        batch = self._batch_executor
        if batch is None:
            return
        node_executor = getattr(batch, "node_executor", None)
        gate_blocked = getattr(node_executor, "gate_blocked", None) or {}
        result.gate_blocked.update(gate_blocked)

        result.skipped.update(getattr(node_executor, "skipped", None) or {})

        skipped = getattr(batch, "_skipped_atomic_node", None)
        if skipped:
            result.skipped[skipped["node"]] = skipped["reason"]

        self._collect_mlops_outcome(result, batch)

    @staticmethod
    def _collect_mlops_outcome(result: PipelineRunResult, executor: Any) -> None:
        """Copy the tracked run's id and final metrics onto the result."""
        result.metrics.update(getattr(executor, "last_run_metrics", None) or {})
        mlops_run_id = getattr(executor, "last_mlops_run_id", None)
        if mlops_run_id:
            result.mlops_run_id = mlops_run_id

    def _collect_hybrid_outcome(self, result: PipelineRunResult, hybrid_result: Any) -> None:
        """Fold HybridExecutor's result dict into the typed run result."""
        hybrid = self._hybrid_executor
        node_executor = getattr(hybrid, "node_executor", None)
        result.gate_blocked.update(getattr(node_executor, "gate_blocked", None) or {})
        self._collect_mlops_outcome(result, hybrid)

        if not isinstance(hybrid_result, dict):
            return

        result.streaming_execution_ids.extend(hybrid_result.get("streaming_execution_ids") or [])
        for error in hybrid_result.get("errors") or []:
            result.errors.append(str(error))
        for node, info in (hybrid_result.get("batch_execution") or {}).items():
            if isinstance(info, dict) and info.get("status") == "skipped":
                result.skipped[node] = str(info.get("reason", "skipped"))
        if hybrid_result.get("status") == "failed":
            result.status = RunStatus.FAILED
            if not result.errors:
                result.errors.append("hybrid pipeline failed")

    def _emit_run_certificate(
        self,
        *,
        pipeline_name: str,
        run_id: str,
        started_at: Any,
        ended_at: Any,
        status: str,
        error: Optional[str],
    ) -> Tuple[Optional[str], Optional[str]]:
        """Assemble and persist the Run Certificate."""
        try:
            from ducta.core import certificate as cert_mod

            for problem in self.settings.evidence_problems:
                logger.error("Evidence policy: {}", problem)
            if not cert_mod.is_enabled(self.context):
                logger.warning(
                    "Run Certificate disabled by configuration (evidence_level=off); "
                    "run {} leaves no evidence behind.",
                    run_id,
                )
                return None, "disabled by configuration (evidence_level=off)"
            try:
                from ducta import __version__ as ducta_version
            except Exception:  # noqa: BLE001
                ducta_version = "unknown"

            env_name = self.settings.env or "base"

            cert = cert_mod.build_certificate(
                self.context,
                run_id=run_id,
                pipeline=pipeline_name,
                environment_name=str(env_name),
                status=status,
                started_at=started_at,
                ended_at=ended_at,
                ducta_version=ducta_version,
                error=error,
            )
            signing_key = cert_mod.resolve_signing_key(self.context)
            if signing_key is not None:
                cert.sign(signing_key)
            elif self.settings.evidence_level == EVIDENCE_SIGNED:
                reason = "evidence_level is 'signed' but no signing key is configured"
                logger.error("Run Certificate NOT written for run {}: {}", run_id, reason)
                return None, reason
            run_dir = cert_mod.certificate_dir(self.context, run_id)
            path = cert_mod.write_certificate(cert, run_dir)
            logger.info("Run Certificate written: {} (run_id={}, status={})", path, run_id, status)
            return str(path), None
        except Exception as e:  # noqa: BLE001 — a certificate must never break a run
            logger.opt(exception=True).error(
                "Run Certificate could NOT be written for run {} (pipeline '{}'): {}. "
                "This run has left no verifiable evidence. Set "
                "evidence_level: required to make this fail the run.",
                run_id,
                pipeline_name,
                e,
            )
            return None, f"certificate emission failed: {e}"

    def _run_preflight(self, pipeline_name: str) -> None:
        """Validate the pipeline's configuration before executing it."""
        if not self.settings.preflight_enabled:
            return
        try:
            from ducta.core.preflight import validate_pipeline

            report = validate_pipeline(self.context, pipeline_name)
        except Exception as e:  # noqa: BLE001 — never let a preflight bug block a valid run
            logger.warning(
                "Preflight validation itself raised an exception and was skipped "
                "for pipeline '{}' (continuing without preflight checks): {}",
                pipeline_name,
                e,
            )
            return

        for warn in report.warnings:
            logger.warning("Preflight: {}", warn)
        if not report.ok:
            raise PreflightError(pipeline_name, report.errors)

    def wait_for_streaming_startup(
        self, execution_id: str, timeout: Optional[float] = None
    ) -> Dict[str, Any]:
        """Block until the startup pass finishes, then report what actually ran."""
        report: Dict[str, Any] = {"started": [], "skipped": {}, "failed": {}, "status": "unknown"}
        if not execution_id:
            return report
        try:
            manager = self.streaming_executor.streaming_manager
            manager.wait_for_pipeline_started(execution_id, timeout=timeout)
            status = manager.get_pipeline_status(execution_id) or {}
            report["started"] = sorted(status.get("query_statuses") or {})
            report["skipped"] = dict(status.get("skipped_nodes") or {})
            report["failed"] = dict(status.get("failed_nodes") or {})
            report["status"] = str(status.get("status") or "unknown")
        except Exception as e:  # noqa: BLE001 — reporting must not break the run
            logger.debug("Could not read streaming startup status: {}", e)
        return report

    def get_active_streaming_execution_id(self) -> Optional[str]:
        """Return the internal execution_id of the running streaming pipeline."""
        if self._streaming_executor is None:
            return None

        stored_id = self.streaming_executor.active_execution_id
        if stored_id:
            return stored_id

        try:
            running = self._streaming_executor.streaming_manager.list_running_pipelines()
            if running:
                return running[0].get("execution_id")
        except Exception:
            pass
        return None

    @staticmethod
    def _safe_streaming(fn: Callable[[], Any], default: Any) -> Any:
        """Call ``fn()``, returning ``default`` if the streaming manager raises."""
        try:
            return fn()
        except Exception:
            return default

    def get_streaming_pipeline_status(self, execution_id: str) -> Dict[str, Any]:
        """Return status info for a streaming pipeline execution."""
        return self._safe_streaming(
            lambda: self.streaming_executor.streaming_manager.get_pipeline_status(execution_id)
            or {},
            {},
        )

    def streaming_snapshot(self) -> List[Dict[str, Any]]:
        """Status of every pipeline this engine has streamed, in whatever state — from
        the streaming executor and the hybrid one, each of which keeps its own
        queries. Neither is created just to be asked: an engine that never streamed
        has nothing to say."""
        snapshot: List[Dict[str, Any]] = []
        for executor in (self._streaming_executor, self._hybrid_executor):
            manager = getattr(executor, "streaming_manager", None)
            if manager is not None:
                snapshot.extend(self._safe_streaming(manager.list_pipelines, []))
        return snapshot

    def list_streaming_pipelines(self) -> List[Dict[str, Any]]:
        """List running streaming pipelines."""
        return self._safe_streaming(
            lambda: self.streaming_executor.streaming_manager.list_running_pipelines(), []
        )

    def stop_streaming_pipeline(self, execution_id: str, graceful: bool = True) -> bool:
        """Stop a running streaming pipeline."""
        return self._safe_streaming(
            lambda: self.streaming_executor.streaming_manager.stop_pipeline(execution_id, graceful),
            False,
        )

    def restart_streaming_node(self, execution_id: str, node_name: str) -> bool:
        """Restart a specific node in a running streaming pipeline."""
        return self._safe_streaming(
            lambda: self.streaming_executor.streaming_manager.restart_node(execution_id, node_name),
            False,
        )

    def get_streaming_pipeline_metrics(self, execution_id: str) -> Dict[str, Any]:
        """Get metrics for a streaming pipeline."""
        return self._safe_streaming(
            lambda: self.streaming_executor.streaming_manager.get_pipeline_metrics(execution_id)
            or {},
            {},
        )

    def run_streaming_pipeline(
        self,
        pipeline_name: str,
        mode: str = "async",
        model_version: Optional[str] = None,
        hyperparams: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Execute a streaming pipeline (convenience wrapper for CLI)."""
        execution_mode = "sync" if mode == "sync" else "async"
        result = self.run_pipeline(
            pipeline_name=pipeline_name,
            model_version=model_version,
            hyperparams=hyperparams,
            execution_mode=execution_mode,
        )
        ids = result.streaming_execution_ids
        return ids[0] if ids else ""

    def register_streaming_transforms(self, module_paths: List[str]) -> None:
        """Import Python modules and call register_transforms(registry) on each."""
        import importlib
        import os
        import sys

        cwd = os.getcwd()
        if cwd not in sys.path:
            sys.path.insert(0, cwd)

        registry = self.streaming_executor.streaming_manager.query_manager.transformation_registry
        for module_path in module_paths:
            try:
                module = importlib.import_module(module_path)
                if hasattr(module, "register_transforms") and callable(module.register_transforms):
                    module.register_transforms(registry)
                    logger.info("Registered transforms from module: {}", module_path)
                else:
                    logger.info(
                        "Imported module '{}' (no register_transforms function found — "
                        "relying on import-time registration)",
                        module_path,
                    )
            except ImportError as e:
                raise RuntimeError(
                    f"Cannot import transforms module '{module_path}': {e}. "
                    f"Ensure the module is on PYTHONPATH or run from the directory "
                    f"that contains it."
                ) from e

    def get_running_execution_ids(self) -> List[str]:
        """Get list of running execution IDs from streaming manager."""
        pipelines = self._safe_streaming(
            lambda: self.streaming_executor.streaming_manager.list_running_pipelines(), []
        )
        return [p.get("execution_id") for p in pipelines if p.get("execution_id")]

    def run_pipeline_chain(
        self,
        pipeline_name: str,
        node_name: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        model_version: Optional[str] = None,
        hyperparams: Optional[Dict[str, Any]] = None,
        execution_mode: Optional[str] = "async",
        reuse_upstream: bool = False,
        rerun_all: bool = False,
        node_names: Optional[List[str]] = None,
    ) -> PipelineRunResult:
        """Execute *pipeline_name* and its transitive dependencies in topological order.

        ``node_names`` (a subset of the target's nodes) runs only those: no
        upstream pipelines, as for a single node."""
        from ducta.setting.dependency_inference import merge_pipeline_depends_on
        from ducta.setting.pipeline_dependency_resolver import PipelineDependencyResolver

        self._force_reuse = bool(reuse_upstream)
        self._force_rerun_all = bool(rerun_all)
        self.reused_pipelines = []
        pipelines_config = getattr(self.context, "pipelines_config", {}) or {}
        nodes_config = getattr(self.context, "nodes_config", {}) or {}
        depends_on_map = merge_pipeline_depends_on(pipelines_config, nodes_config)

        if not depends_on_map.get(pipeline_name) or node_names:
            return self.run_pipeline(
                pipeline_name,
                node_name,
                start_date,
                end_date,
                model_version,
                hyperparams,
                execution_mode,
                node_names=node_names,
            )

        chain = PipelineDependencyResolver.resolve_execution_chain(
            pipeline_name, pipelines_config, depends_on_map
        )
        logger.info("Pipeline chain resolved: {}", " → ".join(chain))

        last_result = PipelineRunResult(pipeline=pipeline_name)
        for step, current_pipeline in enumerate(chain, 1):
            is_target = current_pipeline == pipeline_name

            if (
                not is_target
                and node_name is None
                and self._reuse_enabled_for(pipelines_config.get(current_pipeline, {}))
                and self._pipeline_is_up_to_date(current_pipeline, start_date, end_date)
            ):
                logger.info(
                    "[{}/{}] Reusing materialized '{}' (skip, up-to-date)",
                    step,
                    len(chain),
                    current_pipeline,
                )
                self.reused_pipelines.append(current_pipeline)
                continue

            logger.info("[{}/{}] Running pipeline '{}'", step, len(chain), current_pipeline)
            try:
                last_result = self.run_pipeline(
                    pipeline_name=current_pipeline,
                    node_name=node_name if is_target else None,
                    start_date=start_date,
                    end_date=end_date,
                    model_version=model_version if is_target else None,
                    hyperparams=hyperparams if is_target else None,
                    execution_mode=execution_mode,
                )
            except Exception as e:
                raise ChainExecutionError(
                    failed_pipeline=current_pipeline,
                    step=step,
                    total=len(chain),
                    cancelled=chain[step:],
                    cause=e,
                ) from e

            if last_result.ok:
                logger.info("Pipeline '{}' completed successfully", current_pipeline)
            else:
                logger.warning(
                    "Pipeline '{}' finished with status '{}'",
                    current_pipeline,
                    last_result.status.value,
                )

            if not is_target:
                self._enforce_chain_step_outcome(
                    last_result, step=step, chain=chain, pipeline=current_pipeline
                )

        last_result.reused_pipelines = list(self.reused_pipelines)
        return last_result

    def _enforce_chain_step_outcome(
        self,
        result: PipelineRunResult,
        *,
        step: int,
        chain: List[str],
        pipeline: str,
    ) -> None:
        """Decide whether an unsuccessful *ancestor* step lets the chain go on."""
        if result.ok or result.status is RunStatus.RUNNING:
            return

        blocked = ", ".join(sorted(result.gate_blocked)) or "-"
        skipped = ", ".join(sorted(result.skipped)) or "-"
        detail = (
            f"upstream pipeline '{pipeline}' did not refresh its outputs "
            f"(status={result.status.value}, gate-blocked nodes: {blocked}, "
            f"skipped nodes: {skipped})"
        )
        cancelled = chain[step:]

        if self.settings.chain_on_gate_blocked == CHAIN_ON_GATE_BLOCKED_CONTINUE:
            logger.warning(
                "{}. chain.on_gate_blocked=continue, so {} will run on whatever "
                "an earlier run left on disk: {}",
                detail,
                "the remaining pipeline(s)" if cancelled else "the chain",
                cancelled or "-",
            )
            return

        raise ChainExecutionError(
            failed_pipeline=pipeline,
            step=step,
            total=len(chain),
            cancelled=cancelled,
            cause=ChainStepNotRefreshedError(detail),
        )

    def _reuse_enabled_for(self, pipeline_cfg: Any) -> bool:
        """Whether chain reuse is enabled for a given ancestor pipeline."""
        if self._force_rerun_all:
            return False
        per_pipeline = self._get_pipeline_field(pipeline_cfg, "reuse_if_materialized")
        if per_pipeline is False:
            return False
        if self._force_reuse:
            return True
        if per_pipeline is True:
            return True
        return self._reuse_materialized_global

    @staticmethod
    def _get_pipeline_field(pipeline_cfg: Any, field: str) -> Any:
        """Read a field from a pipeline config (dict or schema), None if absent."""
        if isinstance(pipeline_cfg, dict):
            return pipeline_cfg.get(field)
        return getattr(pipeline_cfg, field, None)

    def _pipeline_is_up_to_date(
        self, pipeline_name: str, start_date: Optional[str], end_date: Optional[str]
    ) -> bool:
        """True if *pipeline_name* can be safely skipped as already materialized."""
        try:
            pipeline = self.batch_executor._get_pipeline_config(pipeline_name)
        except Exception:
            return False

        if not self._is_skip_eligible(pipeline):
            return False

        state = self._load_chain_state(pipeline_name)

        if pipeline.get("requires_dates", True):
            if not state:
                return False
            eff_start, eff_end = self._effective_dates(start_date, end_date)
            if state.get("start_date") != eff_start or state.get("end_date") != eff_end:
                return False

        if not self._provenance_still_matches(pipeline_name, state):
            return False

        out_keys = self._resolve_pipeline_output_keys(pipeline)
        if not out_keys:
            return False  # nothing to verify → re-run

        env = self._pipeline_env()
        output_manager = self.batch_executor.output_manager

        for out_key in out_keys:
            if not output_manager.is_output_materialized(out_key, env):
                return False

        if self._staleness_check:
            newest_input = self._max_pipeline_input_mtime(pipeline)
            if newest_input is not None:
                oldest_output = self._min_pipeline_output_mtime(out_keys, env)
                if oldest_output is None or oldest_output < newest_input:
                    return False

        return True

    def _provenance_still_matches(
        self, pipeline_name: str, state: Optional[Dict[str, Any]]
    ) -> bool:
        """Whether the recorded outputs were produced by today's config and code."""
        if state is None:
            logger.info(
                "Not reusing '{}': no chain-state marker records what produced its outputs.",
                pipeline_name,
            )
            return False

        for label, recorded, current in (
            ("configuration", state.get("config_fingerprint"), self._config_fingerprint()),
            ("node code", state.get("code_fingerprint"), self._code_fingerprint(pipeline_name)),
        ):
            if recorded is None:
                logger.info(
                    "Not reusing '{}': its chain-state marker records no {} fingerprint "
                    "(written by an older Ducta). Re-running once will record one.",
                    pipeline_name,
                    label,
                )
                return False
            if current is None or current != recorded:
                logger.info(
                    "Not reusing '{}': its {} changed since those outputs were written.",
                    pipeline_name,
                    label,
                )
                return False
        return True

    def _is_skip_eligible(self, pipeline: Dict[str, Any]) -> bool:
        """Guard rails: only plain batch pipelines whose outputs all overwrite."""
        pipeline_type = pipeline.get("type", PipelineType.BATCH.value)
        type_value = getattr(pipeline_type, "value", pipeline_type)
        if type_value != PipelineType.BATCH.value:
            return False

        output_config = getattr(self.context, "output_config", {}) or {}
        for out_key in self._resolve_pipeline_output_keys(pipeline):
            cfg = output_config.get(out_key, {}) or {}
            write_mode = cfg.get("write_mode", WriteMode.OVERWRITE.value)
            if getattr(write_mode, "value", write_mode) != WriteMode.OVERWRITE.value:
                return False
        return True

    def _resolve_pipeline_output_keys(self, pipeline: Dict[str, Any]) -> List[str]:
        """All output dataset keys declared across a pipeline's nodes."""
        nodes_config = getattr(self.context, "nodes_config", {}) or {}
        out_keys: List[str] = []
        seen: set = set()
        for node_name in extract_pipeline_nodes(pipeline):
            node_cfg = nodes_config.get(node_name, {}) or {}
            raw_out = node_cfg.get("output", [])
            if isinstance(raw_out, str):
                raw_out = [raw_out]
            elif isinstance(raw_out, dict):
                raw_out = list(raw_out.values())
            for key in raw_out or []:
                if isinstance(key, str) and key not in seen:
                    seen.add(key)
                    out_keys.append(key)
        return out_keys

    def _max_pipeline_input_mtime(self, pipeline: Dict[str, Any]) -> Optional[float]:
        """Newest input mtime across all nodes of a pipeline (None if no signal)."""
        nodes_config = getattr(self.context, "nodes_config", {}) or {}
        input_loader = self.batch_executor.input_loader
        newest: Optional[float] = None
        for node_name in extract_pipeline_nodes(pipeline):
            node_cfg = nodes_config.get(node_name, {}) or {}
            mtime = input_loader.max_input_mtime(node_cfg)
            if mtime is not None and (newest is None or mtime > newest):
                newest = mtime
        return newest

    def _min_pipeline_output_mtime(
        self, out_keys: List[str], env: Optional[str]
    ) -> Optional[float]:
        """Oldest output mtime across a pipeline's outputs (None if any missing)."""
        output_manager = self.batch_executor.output_manager
        oldest: Optional[float] = None
        for out_key in out_keys:
            mtime = output_manager.output_mtime(out_key, env)
            if mtime is None:
                return None
            if oldest is None or mtime < oldest:
                oldest = mtime
        return oldest

    def _pipeline_env(self) -> Optional[str]:
        """Resolve the active environment name for output-path resolution."""
        return self.settings.env

    _LEGACY_CHAIN_STATE_DIR = ".ducta/chain_state"

    def _chain_state_path(self, pipeline_name: str) -> Path:
        """Chain-state path for this pipeline.

        ``self.settings.chain_state_dir`` is already fully resolved and
        environment-scoped (``CoreSettings._resolve_scoped_dir``), so this
        just appends the pipeline's file name.
        """
        safe_name = pipeline_name.replace("/", "_")
        return Path(self.settings.chain_state_dir) / f"{safe_name}.json"

    def _legacy_per_env_chain_state_path(self, pipeline_name: str) -> Path:
        """Pre-restructure per-environment path (`.ducta/chain_state/<env>/…`,
        relative to cwd), kept for backward-compat reads only."""
        safe_name = pipeline_name.replace("/", "_")
        env = sanitize_env_for_path(self.settings.env)
        return Path(self._LEGACY_CHAIN_STATE_DIR) / env / f"{safe_name}.json"

    def _legacy_chain_state_path(self, pipeline_name: str) -> Path:
        """Pre-per-environment flat path, kept for backward-compat reads only."""
        safe_name = pipeline_name.replace("/", "_")
        return Path(self._LEGACY_CHAIN_STATE_DIR) / f"{safe_name}.json"

    def _effective_dates(
        self, start_date: Optional[str], end_date: Optional[str]
    ) -> Tuple[Optional[str], Optional[str]]:
        """Dates as the executor resolves them (explicit args, else global settings)."""
        eff_start = start_date or self.settings.start_date
        eff_end = end_date or self.settings.end_date
        return (
            str(eff_start) if eff_start is not None else None,
            str(eff_end) if eff_end is not None else None,
        )

    def _config_fingerprint(self) -> Optional[str]:
        """Hash of the five config documents, or None if it cannot be computed."""
        try:
            from ducta.core.certificate import config_fingerprint

            return config_fingerprint(self.context)
        except Exception as e:  # noqa: BLE001 — bookkeeping must never break a run
            logger.debug("Could not fingerprint the configuration: {}", e)
            return None

    def _code_fingerprint(self, pipeline_name: str) -> Optional[str]:
        """SHA-256 over the source of the modules backing a pipeline's nodes."""
        try:
            import hashlib
            import importlib.util

            nodes_config = getattr(self.context, "nodes_config", {}) or {}
            pipeline = self.batch_executor._get_pipeline_config(pipeline_name)
            modules = {
                (nodes_config.get(node) or {}).get("module")
                for node in extract_pipeline_nodes(pipeline)
            }
            modules.discard(None)
            if not modules:
                return None

            loader = self.batch_executor.node_executor._function_loader
            importer = loader.secure_importer
            search_paths = [str(path) for path in loader._gather_search_paths()]

            digest = hashlib.sha256()
            hashed_any = False
            with importer.temporary_sys_path(search_paths):
                for module_path in sorted(modules):
                    spec = importlib.util.find_spec(str(module_path))
                    origin = getattr(spec, "origin", None) if spec else None
                    if not origin:
                        return None
                    source = Path(origin)
                    if not source.is_file():
                        return None

                    digest.update(str(module_path).encode("utf-8"))
                    digest.update(b"\0")
                    digest.update(source.read_bytes())
                    digest.update(b"\0")
                    hashed_any = True
            return f"sha256:{digest.hexdigest()}" if hashed_any else None
        except Exception as e:  # noqa: BLE001 — bookkeeping must never break a run
            logger.debug("Could not fingerprint node code for '{}': {}", pipeline_name, e)
            return None

    def _record_chain_state(
        self,
        pipeline_name: str,
        pipeline_type: Any,
        start_date: Optional[str],
        end_date: Optional[str],
    ) -> None:
        """Persist the date range a successful full-pipeline run used. Best-effort."""
        type_value = getattr(pipeline_type, "value", pipeline_type)
        if type_value != PipelineType.BATCH.value:
            return  # only batch pipelines are ever skip-eligible
        try:
            from datetime import datetime, timezone

            eff_start, eff_end = self._effective_dates(start_date, end_date)
            path = self._chain_state_path(pipeline_name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "pipeline": pipeline_name,
                        "start_date": eff_start,
                        "end_date": eff_end,
                        "recorded_at": datetime.now(timezone.utc).isoformat(),
                        # What produced these outputs, so a later run can tell
                        # whether reusing them still means the same thing.
                        "config_fingerprint": self._config_fingerprint(),
                        "code_fingerprint": self._code_fingerprint(pipeline_name),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        except Exception as e:  # noqa: BLE001 — bookkeeping must never break a run
            logger.debug("Could not record chain state for '{}': {}", pipeline_name, e)

    def _load_chain_state(self, pipeline_name: str) -> Optional[Dict[str, Any]]:
        """Read the chain-state marker for a pipeline; None when absent/corrupt."""
        try:
            for candidate in (
                self._chain_state_path(pipeline_name),
                self._legacy_per_env_chain_state_path(pipeline_name),
                self._legacy_chain_state_path(pipeline_name),
            ):
                if candidate.exists():
                    data = json.loads(candidate.read_text(encoding="utf-8"))
                    return data if isinstance(data, dict) else None
            return None
        except Exception:  # noqa: BLE001
            return None

    def validate_pipeline(self, pipeline_name: str) -> bool:
        """Validate if a pipeline exists in the configuration."""
        return pipeline_name in self.context.pipelines

    def list_pipelines(self) -> List[str]:
        """List all available pipelines."""
        return list(self.context.pipelines.keys())

    def get_pipeline_info(self, pipeline_name: str) -> Dict[str, Any]:
        """Describe a pipeline for a human: its description and its node *names*."""
        if pipeline_name not in self.context.pipelines:
            return {
                "exists": False,
                "description": None,
                "nodes": [],
            }

        pipeline = self.context.pipelines[pipeline_name]
        if not isinstance(pipeline, dict):
            return {"exists": True, "description": None, "nodes": []}

        try:
            nodes = extract_pipeline_nodes(pipeline)
        except ValueError as e:  # a node entry no shape rule matches
            logger.warning(
                "Pipeline '{}' has a node entry that could not be named: {}", pipeline_name, e
            )
            nodes = []

        return {
            "exists": True,
            "description": pipeline.get("description", ""),
            "nodes": nodes,
        }

    def shutdown(self) -> None:
        """Unified shutdown with resource cleanup."""
        from concurrent.futures import ThreadPoolExecutor
        from concurrent.futures import TimeoutError as FutureTimeoutError

        shutdown_sequence = [
            (self._stop_streaming_queries, 5),
            (self._release_connection_pools, 10),
            (self._cleanup_memory, 20),
        ]

        for step, timeout in shutdown_sequence:
            ex = ThreadPoolExecutor(max_workers=1)
            try:
                logger.info("Executing shutdown step: {} (timeout={}s)", step.__name__, timeout)
                ex.submit(step).result(timeout=timeout)
            except FutureTimeoutError:
                logger.warning("Shutdown step {} timed out after {}s", step.__name__, timeout)
            except Exception as e:
                logger.error("Shutdown error in {}: {}", step.__name__, e)
            finally:
                ex.shutdown(wait=False)

    def _stop_streaming_queries(self) -> None:
        """Stop active streaming queries if the manager supports it"""

        if self._streaming_executor is None:
            return
        try:
            self.streaming_executor.shutdown()
        except Exception:
            pass

    def _release_connection_pools(self) -> None:
        """Release all database connections"""
        if hasattr(self.context, "connection_pools"):
            for pool in self.context.connection_pools.values():
                pool.shutdown()

    def _cleanup_memory(self) -> None:
        """Force memory cleanup"""
        gc.collect()
        if self.context.has_spark_session():
            try:
                self.context.spark.catalog.clearCache()
            except Exception:
                pass
