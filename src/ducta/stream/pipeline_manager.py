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

import os
import re
import shutil
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from loguru import logger  # type: ignore

try:
    from pyspark.sql.streaming import StreamingQuery  # type: ignore
except ImportError:
    StreamingQuery = Any  # type: ignore

from ducta.setting.dependency_inference import get_node_dependencies
from ducta.stream.checkpoints import CheckpointManager
from ducta.stream.context_utils import get_active_env, get_context_value
from ducta.stream.exceptions import (
    StreamingError,
    StreamingPipelineError,
    create_error_context,
    handle_streaming_error,
)
from ducta.stream.journal import StreamRunJournal, journal_base, recent_trigger_ms, summarize
from ducta.stream.node_state import derive_node_state, node_names
from ducta.stream.plan import describe_node
from ducta.stream.progress_listener import (
    DuctaProgressListener,
    StreamingProgressSink,
    listener_available,
)
from ducta.stream.query_manager import (
    StreamingQueryManager,
    get_query_exception,
    is_query_active,
    single_spec,
)
from ducta.stream.validators import StreamingValidator

_TRANSIENT_DELTA_ERROR_TOKENS = frozenset(
    {
        "DELTA_SCHEMA_NOT_SET",
        "IS NOT A DELTA TABLE",
        "PATH DOES NOT EXIST",
        "PATH_NOT_FOUND",
        "NO SUCH FILE OR DIRECTORY",
    }
)


_PYTHON_ERROR_LINE = re.compile(r"^\s*([A-Za-z_][\w.]*(?:Error|Exception)): (.+)$")


def short_error(error: Any, limit: int = 500) -> str:
    """One readable line for a query's failure.

    Spark wraps an error raised in a Python UDF/transform in a JVM stack trace whose
    first thousand characters never reach the Python line that says what happened
    (``ValueError: poison record 5``); that line is kept next to the first one.
    """
    text = str(error or "")
    lines = [line for line in text.splitlines() if line.strip()]
    first = lines[0].strip() if lines else ""
    cause = None
    for line in reversed(lines):
        match = _PYTHON_ERROR_LINE.match(line)
        if match and not match.group(1).startswith(("org.", "java.", "scala.")):
            cause = f"{match.group(1)}: {match.group(2).strip()}"
            break
    if cause and cause not in first:
        first = f"{cause} ({first[: max(0, limit - len(cause) - 3)]})"
    return first[:limit]


class QueryHealthMonitor:
    """Monitor health of streaming queries."""

    def __init__(self, query: Any, query_name: str, timeout_seconds: float = 300):
        self.query = query
        self.query_name = query_name
        self.timeout_seconds = timeout_seconds
        # None until the first batch arrives; we don't start the stall-timer before that.
        self.last_progress_time: Optional[float] = None
        self.last_batch_id = None
        # ``timestamp`` of the last progress report seen. An idle query keeps its
        # batchId (no new batch runs) but Spark still reports progress every few
        # seconds, so a moving timestamp is proof of life that batchId alone is not.
        self.last_progress_stamp: Optional[str] = None
        self.error_message: Optional[str] = None
        self._lock = Lock()

    def _is_query_active(self) -> bool:
        return is_query_active(self.query)

    def _get_query_exception(self) -> Optional[Exception]:
        return get_query_exception(self.query)

    def _check_progress(self) -> bool:
        with self._lock:
            try:
                last_progress = getattr(self.query, "lastProgress", None)
                if not last_progress:
                    return True

                current_batch_id = last_progress.get("batchId")
                current_stamp = last_progress.get("timestamp")
                current_time = time.time()

                batch_advanced = (
                    current_batch_id is not None and current_batch_id != self.last_batch_id
                )
                stamp_advanced = (
                    current_stamp is not None and current_stamp != self.last_progress_stamp
                )
                if batch_advanced or stamp_advanced:
                    self.last_batch_id = current_batch_id
                    self.last_progress_stamp = current_stamp
                    self.last_progress_time = current_time
                    return True

                if self.last_progress_time is None:
                    self.last_progress_time = current_time
                    return True

                return (current_time - self.last_progress_time) <= self.timeout_seconds
            except (AttributeError, RuntimeError) as e:
                logger.debug(f"Query '{self.query_name}' progress check failed: {str(e)}")
                return False
            except Exception as e:
                # Unexpected error - log but don't fail the health check
                logger.warning(
                    f"Unexpected error checking progress for '{self.query_name}': {str(e)}"
                )
                return True

    def _build_health_check_result(self) -> Tuple[bool, Optional[str]]:
        is_active = self._is_query_active()
        if not is_active:
            exception = self._get_query_exception()
            if exception:
                self.error_message = f"Query failed with exception: {str(exception)}"
                return False, self.error_message
            self.error_message = None
            return False, None

        if not self._check_progress():
            elapsed = time.time() - (self.last_progress_time or time.time())
            self.error_message = (
                f"Query stalled: no progress for {elapsed:.1f}s (timeout: {self.timeout_seconds}s)"
            )
            return False, self.error_message

        self.error_message = None
        return True, None

    def check_health(self) -> Tuple[bool, Optional[str]]:
        try:
            return self._build_health_check_result()
        except Exception as e:
            self.error_message = f"Error checking query health: {str(e)}"
            logger.error(f"Health check failed for '{self.query_name}': {self.error_message}")
            return False, self.error_message

    def get_status_dict(self) -> Dict[str, Any]:
        try:
            return {
                "query_name": self.query_name,
                "is_active": self._is_query_active(),
                "error": self.error_message,
                "last_batch_id": self.last_batch_id,
                "last_progress": getattr(self.query, "lastProgress", None),
            }
        except Exception:
            return {"query_name": self.query_name, "error": "Failed to get status"}


class StreamingPipelineManager:
    """Manages streaming pipelines with lifecycle control and monitoring."""

    def __init__(
        self,
        context,
        max_concurrent_pipelines: int = 5,
        validator: Optional[StreamingValidator] = None,
    ):
        self.context = context
        self.max_concurrent_pipelines = max_concurrent_pipelines
        policy = get_context_value(context, "format_policy", None)
        self.validator = validator or StreamingValidator(policy)
        self.progress_sink = StreamingProgressSink()
        self._progress_listener: Optional[Any] = None
        self.query_manager = StreamingQueryManager(
            context, validator=self.validator, progress_sink=self.progress_sink
        )
        self._register_progress_listener()
        self.active_environment = get_active_env(context)
        settings = get_context_value(context, "global_config", {}) or {}
        self.node_start_retry_attempts = int(settings.get("streaming_node_start_retries", 45))
        self.node_start_retry_delay_seconds = float(
            settings.get("streaming_node_start_retry_delay_seconds", 2.0)
        )
        self.node_start_parallelism = max(
            1, int(settings.get("streaming_node_start_parallelism", 8))
        )

        self._running_pipelines: Dict[str, Dict[str, Any]] = {}
        self._pipeline_threads: Dict[str, Any] = {}
        self._pipeline_events: Dict[str, Event] = {}
        self._pipeline_started_events: Dict[str, Event] = {}
        self._pipeline_stop_events: Dict[str, Event] = {}
        self._shutdown_event = Event()
        self._lock = Lock()
        self._query_monitors: Dict[str, QueryHealthMonitor] = {}
        self._status_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
        self._status_cache_lock = Lock()
        self._status_cache_ttl = float(settings.get("streaming_status_cache_ttl_seconds", 2.0))
        self._executor = ThreadPoolExecutor(
            max_workers=max_concurrent_pipelines,
            thread_name_prefix="streaming_pipeline",
        )
        # The on-disk record of each execution (ducta.stream.journal), which query
        # belongs to which node, and who is told about an execution's events.
        self._journals: Dict[str, StreamRunJournal] = {}
        self._query_owner: Dict[str, Tuple[str, str]] = {}
        self._finished: Set[str] = set()
        self._listeners: List[Callable[[Dict[str, Any]], None]] = []
        self.progress_sink.listener = self._on_progress
        self.query_manager.batch_listener = self._on_micro_batch
        # Live alerts: (execution, node) -> the kind last reported for it, and the
        # quarantine counts not yet reported. Checked by a daemon every interval.
        self._alerted: Dict[Tuple[str, str], str] = {}
        self._quarantine_pending: Dict[Tuple[str, str], Dict[str, Any]] = {}
        # 0 turns the check off (as documented); `or 30.0` used to turn 0 into 30.
        health = settings.get("streaming_health_interval_seconds")
        self.health_interval_seconds = float(30.0 if health is None else health)
        self.quarantine_alert_interval_seconds = float(
            settings.get("streaming_quarantine_alert_interval_seconds", 900.0) or 900.0
        )
        self._health_thread: Optional[Thread] = None
        # A query that dies while running is started again after a backoff that
        # doubles each time (capped), up to this many times; 0 turns it off.
        max_restarts = settings.get("streaming_restart_max_attempts")
        self.restart_max_attempts = max(0, int(3 if max_restarts is None else max_restarts))
        backoff = settings.get("streaming_restart_backoff_seconds")
        self.restart_backoff_seconds = max(0.0, float(10.0 if backoff is None else backoff))

    #: Finished executions kept for status queries; older ones are dropped when a
    #: new pipeline starts, so a long-lived manager does not grow without bound.
    MAX_FINISHED_EXECUTIONS = 50

    #: The longest wait between two automatic restarts of a node.
    RESTART_BACKOFF_CAP_SECONDS = 300.0

    #: A restarted query that runs this long without failing starts its count again.
    RESTART_RESET_SECONDS = 600.0

    #: A running query is called stalled after this long without any progress
    #: report; raised for triggers that fire less often than this.
    MIN_STALL_TIMEOUT_SECONDS = 300.0

    @property
    def is_shut_down(self) -> bool:
        """Whether :meth:`shutdown` ran; a shut-down manager cannot start pipelines."""
        return self._shutdown_event.is_set()

    def _node_summary(self, node_config: Dict[str, Any], pipeline_name: str) -> Dict[str, Any]:
        """What the node reads, writes and checkpoints to, for the status (no options)."""
        try:
            return describe_node(node_config, self.context, pipeline_name).summary()
        except Exception as e:  # noqa: BLE001 - a description must never stop a start
            logger.debug(f"Could not describe node '{node_config.get('name')}': {e}")
            return {}

    def _stall_timeout_seconds(self, node_config: Dict[str, Any]) -> float:
        """How long a node's query may go without progress before it counts as stalled.

        Never less than three trigger intervals: a query on an hourly trigger is
        idle for most of the hour by design.
        """
        trigger = ((node_config.get("streaming") or {}).get("trigger")) or {}
        interval = trigger.get("interval") if isinstance(trigger, dict) else None
        seconds = self.validator.parse_time_to_seconds(interval) if interval else 0.0
        return max(self.MIN_STALL_TIMEOUT_SECONDS, 3.0 * seconds)

    def _get_spark(self) -> Optional[Any]:
        """Resolve the SparkSession from the context (dict or object form)."""
        try:
            return get_context_value(self.context, "spark")
        except Exception:
            return None

    def _register_progress_listener(self) -> None:
        """Attach a DuctaProgressListener to the active SparkSession (best-effort)."""
        if not listener_available():
            return
        spark = self._get_spark()
        if spark is None:
            return
        try:
            listener = DuctaProgressListener(self.progress_sink)
            spark.streams.addListener(listener)
            self._progress_listener = listener
            logger.debug("Registered DuctaProgressListener on SparkSession")
        except Exception as e:
            logger.debug(f"Could not register streaming progress listener: {e}")

    def _is_transient_start_error(self, node_config: Dict[str, Any], exc: Exception) -> bool:
        """Identify startup errors that can resolve after upstream warm-up."""
        # Either spelling (input / a one-element inputs) and the "delta" alias.
        input_config = single_spec(node_config, "input")
        if not isinstance(input_config, dict):
            return False
        input_format = str(input_config.get("format", "")).strip().lower()
        if input_format not in ("delta_stream", "delta"):
            return False

        root = (
            getattr(exc, "cause", None)
            or getattr(exc, "__cause__", None)
            or getattr(exc, "__context__", None)
        )

        for candidate in (exc, root):
            if candidate is None:
                continue
            error_class = getattr(candidate, "errorClass", None) or getattr(
                candidate, "error_class", None
            )  # type: ignore[union-attr]
            if error_class:
                transient_classes = {
                    "DELTA_SCHEMA_NOT_SET",
                    "PATH_NOT_FOUND",
                    "DELTA_TABLE_NOT_FOUND",
                    "DELTA_MISSING_TRANSACTION_LOG",
                }
                if str(error_class) in transient_classes:
                    return True

            exc_type = type(candidate).__name__  # type: ignore[arg-type]
            analysis_types = (
                "AnalysisException",
                "PathNotFoundException",
                "FileNotFoundException",
                "NoSuchFileException",
            )
            if any(t in exc_type for t in analysis_types):
                if any(token in str(candidate).upper() for token in _TRANSIENT_DELTA_ERROR_TOKENS):
                    return True

        return any(token in str(exc).upper() for token in _TRANSIENT_DELTA_ERROR_TOKENS)

    def _start_node_query_with_retry(
        self,
        execution_id: str,
        pipeline_name: str,
        node_name: str,
        node_config: Dict[str, Any],
    ):
        """Start a node query with retry for known transient startup failures."""
        attempts = max(1, self.node_start_retry_attempts)
        delay = max(0.0, self.node_start_retry_delay_seconds)
        last_error: Optional[Exception] = None
        stop_event = self._pipeline_stop_events.get(execution_id)

        def _stopping() -> bool:
            return self._shutdown_event.is_set() or (stop_event is not None and stop_event.is_set())

        for attempt in range(1, attempts + 1):
            try:
                return self.query_manager.create_and_start_query(
                    node_config, execution_id, pipeline_name
                )
            except Exception as e:
                last_error = e
                should_retry = (
                    attempt < attempts
                    and self._is_transient_start_error(node_config, e)
                    and not _stopping()
                )

                if not should_retry:
                    raise

                logger.warning(
                    "Transient startup error in node '{}' (attempt {}/{}): {}. Retrying in {:.1f}s",
                    node_name,
                    attempt,
                    attempts,
                    str(e),
                    delay,
                )
                if delay > 0:
                    remaining = delay
                    poll_interval = 0.1
                    while remaining > 0 and not _stopping():
                        step = min(poll_interval, remaining)
                        self._shutdown_event.wait(step)
                        remaining -= step
                if _stopping():
                    logger.info("Shutdown/stop requested, aborting retry of node '{}'", node_name)
                    raise

        if last_error is not None:
            raise last_error

        raise StreamingPipelineError(
            f"Failed to start node '{node_name}' due to unknown retry state",
            pipeline_name=pipeline_name,
            execution_id=execution_id,
        )

    def start_pipeline(
        self, pipeline_name: str, pipeline_config: Dict[str, Any], run_id: Optional[str] = None
    ) -> str:
        """Validate and start a pipeline asynchronously.

        *run_id* is the run this execution belongs to (its certificate, its journal);
        the execution id stands in for it when none is given.
        """
        try:
            self.validator.validate_streaming_pipeline_config(pipeline_config)

            execution_id = uuid.uuid4().hex

            with self._lock:
                active = sum(
                    1
                    for info in self._running_pipelines.values()
                    if info.get("status") in ("starting", "running")
                )
                if active >= self.max_concurrent_pipelines:
                    raise StreamingPipelineError(
                        f"Maximum concurrent pipelines reached ({self.max_concurrent_pipelines})",
                        pipeline_name=pipeline_name,
                    )
                self._running_pipelines[execution_id] = {
                    "pipeline_name": pipeline_name,
                    "pipeline_config": pipeline_config,
                    "status": "starting",
                    "start_time": time.time(),
                    "queries": {},
                    "completed_nodes": 0,
                    "failed_nodes": {},
                    "skipped_nodes": {},
                    "error": None,
                    "run_id": run_id or execution_id,
                }
                self._pipeline_events[execution_id] = Event()
                self._pipeline_started_events[execution_id] = Event()
                self._pipeline_stop_events[execution_id] = Event()
                pruned = self._prune_finished_locked(keep=execution_id)
            self._forget_executions(pruned)
            self._open_journal(execution_id, pipeline_name, pipeline_config, run_id or execution_id)
            self._ensure_health_monitor()

            future = self._executor.submit(
                self._execute_pipeline, execution_id, pipeline_name, pipeline_config
            )
            with self._lock:
                self._pipeline_threads[execution_id] = future

            return execution_id

        except Exception as e:
            context = create_error_context(
                operation="start_pipeline",
                component="StreamingPipelineManager",
                pipeline_name=pipeline_name,
            )
            if isinstance(e, StreamingError):
                try:
                    e.add_context("operation_context", context)
                except Exception:
                    pass
                raise
            raise StreamingPipelineError(
                f"Failed to start pipeline: {str(e)}",
                pipeline_name=pipeline_name,
                context=context,
                cause=e,
            ) from e

    def _prune_finished_locked(self, keep: str) -> List[str]:
        """Drop the oldest finished executions beyond ``MAX_FINISHED_EXECUTIONS``.

        Caller holds ``self._lock``. "Finished" means the done event fired, so a
        pipeline that still has live queries (``partial_failure`` included) is
        never touched. Returns the dropped execution ids.
        """
        finished = [
            (info.get("start_time", 0.0), eid)
            for eid, info in self._running_pipelines.items()
            if eid != keep
            and (self._pipeline_events.get(eid) is not None and self._pipeline_events[eid].is_set())
        ]
        excess = len(finished) - self.MAX_FINISHED_EXECUTIONS
        if excess <= 0:
            return []
        dropped = [eid for _, eid in sorted(finished)[:excess]]
        for eid in dropped:
            self._running_pipelines.pop(eid, None)
            self._journals.pop(eid, None)
            self._finished.discard(eid)
            self._pipeline_events.pop(eid, None)
            self._pipeline_started_events.pop(eid, None)
            self._pipeline_stop_events.pop(eid, None)
            self._pipeline_threads.pop(eid, None)
        return dropped

    def _forget_executions(self, execution_ids: List[str]) -> None:
        """Release what other collaborators keep for dropped executions (no lock held)."""
        if not execution_ids:
            return
        with self._status_cache_lock:
            for eid in execution_ids:
                self._status_cache.pop(eid, None)
        for eid in execution_ids:
            self.query_manager.forget_execution(eid)

    def wait_for_pipeline_done(self, execution_id: str, timeout: Optional[float] = None) -> bool:
        """Block until the pipeline reaches a terminal state (stopped/error/failed)."""
        with self._lock:
            event = self._pipeline_events.get(execution_id)
        if event is None:
            return True
        return event.wait(timeout=timeout)

    def wait_for_pipeline_started(self, execution_id: str, timeout: Optional[float] = None) -> bool:
        """Block until the startup pass has finished for every node."""
        with self._lock:
            event = self._pipeline_started_events.get(execution_id)
        if event is None:
            return True
        return event.wait(timeout=timeout)

    def _signal_pipeline_started(self, execution_id: str) -> None:
        """Release anyone waiting on the startup pass. Safe to call repeatedly."""
        with self._lock:
            event = self._pipeline_started_events.get(execution_id)
        if event is not None:
            event.set()

    def has_execution(self, execution_id: str) -> bool:
        """Whether this manager started (and still remembers) *execution_id*."""
        with self._lock:
            return execution_id in self._running_pipelines

    def is_query_active(self, execution_id: str) -> bool:
        """Return True if the pipeline has active (non-terminal) status."""
        with self._lock:
            info = self._running_pipelines.get(execution_id)
            status = info.get("status") if info else None
            queries = list((info or {}).get("queries", {}).values())
        if status in ("starting", "running"):
            return True
        if status == "partial_failure":
            # Some nodes failed or stalled; the pipeline is active only while a
            # query is still up (when every node failed there is none), or one is
            # about to be restarted (its checkpoint is still in use).
            return any(
                self.query_manager._is_query_active(q) for q in queries
            ) or self._restart_pending(execution_id)
        return False

    def _signal_pipeline_done(self, execution_id: str) -> None:
        """Signal completion event and release associated resources."""
        self._signal_pipeline_started(execution_id)
        prefix = f"{execution_id}:"
        with self._lock:
            event = self._pipeline_events.get(execution_id)
            self._pipeline_threads.pop(execution_id, None)
            stale_keys = [k for k in self._query_monitors if k.startswith(prefix)]
            for k in stale_keys:
                self._query_monitors.pop(k, None)
            pipeline_info = self._running_pipelines.get(execution_id)
            queries_snapshot = dict(pipeline_info.get("queries", {})) if pipeline_info else {}
        with self._status_cache_lock:
            self._status_cache.pop(execution_id, None)
        final_totals: Dict[str, Dict[str, float]] = {}
        for node_name, query in queries_snapshot.items():
            qname = getattr(query, "name", None) or getattr(query, "queryName", None)
            if qname:
                # Kept on the execution before the sink forgets the query: what a
                # finished run processed is what its closing summary reports.
                totals = self.progress_sink.totals(qname)
                if totals:
                    final_totals[node_name] = totals
                self.progress_sink.forget(qname)
        if final_totals:
            with self._lock:
                info = self._running_pipelines.get(execution_id)
                if info is not None:
                    info.setdefault("totals", {}).update(final_totals)
        # Before the event: whoever waits on it (a synchronous run sealing its
        # certificate) must find the listeners already told.
        self._finish_execution(execution_id)
        if event is not None:
            event.set()

    def _start_completion_watcher(self, execution_id: str) -> None:
        """Spawn a daemon thread that signals done when all queries self-terminate."""
        Thread(
            target=self._watch_pipeline_until_done,
            args=(execution_id,),
            name=f"Ducta-stream-watch-{execution_id[:8]}",
            daemon=True,
        ).start()

    def _watch_pipeline_until_done(self, execution_id: str, poll_seconds: float = 1.0) -> None:
        """Poll a pipeline's queries; signal completion once none remain active."""
        with self._lock:
            event = self._pipeline_events.get(execution_id)
        if event is None:
            return

        while not event.is_set() and not self._shutdown_event.is_set():
            wait = self._supervise_restarts(execution_id)
            if wait is not None:
                # A node that failed is restarted after its backoff: not finished.
                event.wait(min(poll_seconds, wait))
                continue
            with self._lock:
                info = self._running_pipelines.get(execution_id)
                queries = list(info.get("queries", {}).values()) if info else []

            if queries and not any(self.query_manager._is_query_active(q) for q in queries):
                errors = self._collect_query_exceptions(queries)
                with self._lock:
                    info = self._running_pipelines.get(execution_id)
                    if info is not None:
                        info["end_time"] = time.time()
                        if errors:
                            info["status"] = "error"
                            info["error"] = "; ".join(errors)
                        elif info.get("failed_nodes") or info.get("skipped_nodes"):
                            # What did run has ended, but a node never started (or
                            # its upstream failed): that is not a clean completion.
                            info["status"] = "partial_failure"
                        elif info.get("status") not in ("stopped", "error"):
                            info["status"] = "completed"
                self._signal_pipeline_done(execution_id)
                return

            event.wait(poll_seconds)

    # ── automatic restarts ───────────────────────────────────────────────────

    def _restart_delay(self, attempts_done: int) -> float:
        """Seconds before restart number ``attempts_done + 1``: doubles, capped."""
        return float(
            min(self.RESTART_BACKOFF_CAP_SECONDS, self.restart_backoff_seconds * (2**attempts_done))
        )

    def _supervise_restarts(self, execution_id: str) -> Optional[float]:
        """Schedule, run or give up the restart of each node whose query died.

        A query that ended with an exception is started again (``restart_node``)
        after a backoff, at most ``streaming_restart_max_attempts`` times; then the
        node is failed for good (``failed_nodes``, the ``stream_failed`` alert). A
        query that ended cleanly (``once``/``available_now``) is left alone, and
        nothing is restarted once a stop was asked for. Returns None when no restart
        is pending, else the seconds until the next one is due: the watcher does not
        close the execution meanwhile, and wakes up for it.
        """
        if self.restart_max_attempts <= 0:
            return None
        now = time.time()
        due: List[Tuple[str, int, str]] = []
        gave_up: List[Tuple[str, int, str]] = []
        next_due: Optional[float] = None
        with self._lock:
            info = self._running_pipelines.get(execution_id)
            if info is None:
                return None
            restarts = info.setdefault("restarts", {})
            if self._stop_requested_locked(execution_id):
                for record in restarts.values():
                    record["pending"] = False
                return None
            queries = dict(info.get("queries") or {})
        for node, query in queries.items():
            active = self.query_manager._is_query_active(query)
            error = None if active else get_query_exception(query)
            with self._lock:
                record = restarts.get(node)
                if active:
                    if (
                        record
                        and not record.get("pending")
                        and now - float(record.get("restarted_at") or now)
                        >= self.RESTART_RESET_SECONDS
                    ):
                        restarts.pop(node, None)  # stable again: a fresh count
                    continue
                if error is None or (record and record.get("gave_up")):
                    continue
                if record and record.get("pending"):
                    next_at = float(record.get("next_at") or 0)
                    if now >= next_at:
                        record["pending"] = False
                        record["attempts"] = int(record.get("attempts") or 0) + 1
                        due.append((node, record["attempts"], str(record.get("last_error"))))
                    else:
                        next_due = min(next_due or next_at, next_at)
                    continue
                attempts = int((record or {}).get("attempts") or 0)
                message = short_error(error)
                if attempts >= self.restart_max_attempts:
                    restarts[node] = {
                        **(record or {}),
                        "attempts": attempts,
                        "pending": False,
                        "gave_up": True,
                        "last_error": message,
                    }
                    reason = f"gave up after {attempts} restart(s): {message}"
                    info.setdefault("failed_nodes", {})[node] = reason
                    info["error"] = reason
                    gave_up.append((node, attempts, message))
                    continue
                delay = self._restart_delay(attempts)
                restarts[node] = {
                    "attempts": attempts,
                    "pending": True,
                    "next_at": now + delay,
                    "last_error": message,
                }
                next_due = min(next_due or now + delay, now + delay)
                logger.warning(
                    "Stream node '{}' failed: {}. Restart {}/{} in {:.0f}s",
                    node,
                    message,
                    attempts + 1,
                    self.restart_max_attempts,
                    delay,
                )
        for node, attempts, message in gave_up:
            logger.error(
                f"Stream node '{node}' failed again after {attempts} restart(s): {message}"
            )
        for node, attempt, message in due:
            self._restart_failed_node(execution_id, node, attempt, message)
        if due:
            return 0.0  # look again at once: a restart that did not start is rescheduled
        return None if next_due is None else max(0.0, next_due - time.time())

    def _restart_failed_node(self, execution_id: str, node: str, attempt: int, error: str) -> None:
        """Run restart *attempt* of *node*; journal it and tell the listeners."""
        ok = self.restart_node(execution_id, node)
        with self._lock:
            info = self._running_pipelines.get(execution_id) or {}
            record = (info.get("restarts") or {}).get(node)
            if record is not None:
                record["restarted_at"] = time.time()
            journal = self._journals.get(execution_id)
            run_id, pipeline = info.get("run_id"), info.get("pipeline_name")
        line = {"node": node, "attempt": attempt, "started": ok, "error": error[:500]}
        if journal is not None:
            journal.record("restart", line)
        if ok:
            logger.info(f"Stream node '{node}' restarted (attempt {attempt})")
        self._emit(
            {
                "kind": "stream_restarted",
                "execution_id": execution_id,
                "run_id": run_id,
                "pipeline": pipeline,
                **line,
            }
        )

    def _restart_will_handle(self, execution_id: str, node: str, status: Dict[str, Any]) -> bool:
        """Whether *node*'s failure is a running query that died and will be restarted.

        A start failure (``failed_nodes`` without a restart record) and a node the
        manager gave up on are real failures; so is anything once a stop was asked.
        """
        if self.restart_max_attempts <= 0 or node not in (status.get("query_statuses") or {}):
            return False
        record = (status.get("restarts") or {}).get(node) or {}
        if record.get("gave_up"):
            return False
        if node in (status.get("failed_nodes") or {}) and not record:
            return False
        with self._lock:
            return not self._stop_requested_locked(execution_id) and (
                execution_id not in self._finished
            )

    def _restart_pending(self, execution_id: str) -> bool:
        with self._lock:
            info = self._running_pipelines.get(execution_id) or {}
            return any(r.get("pending") for r in (info.get("restarts") or {}).values())

    @staticmethod
    def _collect_query_exceptions(queries: List[Any]) -> List[str]:
        """Return string messages for any queries that terminated due to an error."""
        errors: List[str] = []
        for query in queries:
            exc = get_query_exception(query)
            if exc:
                errors.append(str(exc))
        return errors

    def _execute_pipeline(
        self, execution_id: str, pipeline_name: str, pipeline_config: Dict[str, Any]
    ) -> None:
        try:
            nodes = pipeline_config.get("nodes", [])
            satisfied = set(pipeline_config.get("satisfied_dependencies") or ())
            ordered_nodes = self._order_nodes_by_dependencies(
                nodes, satisfied_dependencies=satisfied
            )
            with self._lock:
                if execution_id in self._running_pipelines:
                    # The order a reader expects (upstream first), for status displays.
                    self._running_pipelines[execution_id]["node_order"] = [
                        n.get("name") for n in ordered_nodes
                    ]
            self._seed_adaptive_history(execution_id, pipeline_name, ordered_nodes)
            processed_nodes = self._process_pipeline_nodes(
                execution_id, pipeline_name, ordered_nodes, satisfied_dependencies=satisfied
            )
            with self._lock:
                pipeline_info = self._running_pipelines.get(execution_id)
                # A stop or an error recorded meanwhile is the final word.
                if pipeline_info and pipeline_info.get("status") not in ("stopped", "error"):
                    if not processed_nodes:
                        # No query exists, whether every node failed or was skipped.
                        pipeline_info["status"] = "failed"
                        pipeline_info["end_time"] = time.time()
                    elif pipeline_info.get("status") != "partial_failure":
                        pipeline_info["status"] = "running"
            self._journal_status(execution_id)
            self._signal_pipeline_started(execution_id)
            if not processed_nodes:
                self._signal_pipeline_done(execution_id)
            else:
                self._start_completion_watcher(execution_id)
        except Exception as e:
            logger.error(f"Error executing streaming pipeline '{execution_id}': {str(e)}")
            with self._lock:
                if execution_id in self._running_pipelines:
                    self._running_pipelines[execution_id]["status"] = "error"
                    self._running_pipelines[execution_id]["error"] = str(e)

            self._signal_pipeline_started(execution_id)
            self._signal_pipeline_done(execution_id)

    def _start_single_node(
        self,
        execution_id: str,
        pipeline_name: str,
        node_name: str,
        resolved_config: Dict[str, Any],
    ) -> str:
        """Start one node's query and do its bookkeeping. Returns the outcome."""
        try:
            logger.debug(f"Starting node '{node_name}' in pipeline '{execution_id}'")
            query = self._start_node_query_with_retry(
                execution_id=execution_id,
                pipeline_name=pipeline_name,
                node_name=node_name,
                node_config=resolved_config,
            )

            summary = self._node_summary(resolved_config, pipeline_name)
            with self._lock:
                # Checked under the lock stop_pipeline snapshots the queries with: a
                # query that finished starting after a stop is not registered, or it
                # would run on unseen (and its checkpoint could be cleared under it).
                stop_requested = self._stop_requested_locked(execution_id)
                pipeline_info = self._running_pipelines.get(execution_id)
                if pipeline_info is not None and not stop_requested:
                    pipeline_info["queries"][node_name] = query
                    self._own_query_locked(execution_id, node_name, query)
                    pipeline_info["completed_nodes"] += 1
                    if summary:
                        pipeline_info.setdefault("node_summaries", {})[node_name] = summary
                if not stop_requested:
                    self._query_monitors[self._monitor_key(execution_id, node_name)] = (
                        QueryHealthMonitor(
                            query=query,
                            query_name=node_name,
                            timeout_seconds=self._stall_timeout_seconds(resolved_config),
                        )
                    )

            if stop_requested:
                logger.info(f"Pipeline '{execution_id}' was stopped while '{node_name}' started")
                self._stop_unregistered_query(query, node_name)
                return "stopped"

            logger.info(f"Successfully started query '{node_name}'")
            return "started"
        except Exception as e:
            self._handle_node_execution_error(execution_id, node_name, str(e))
            return "failed"

    def _process_pipeline_nodes(
        self,
        execution_id: str,
        pipeline_name: str,
        nodes: List[Any],
        satisfied_dependencies: Optional[Set[str]] = None,
    ) -> List[str]:
        """Process pipeline nodes by dependency waves, starting independent
        nodes in parallel.
        """
        processed_nodes: List[str] = []
        node_outcomes: Dict[str, str] = {}
        satisfied = satisfied_dependencies or set()

        resolved_nodes = [
            (cfg.get("name", f"node_{idx}"), cfg)
            for idx, cfg in ((i, self._get_node_config(node, i)) for i, node in enumerate(nodes))
        ]
        all_names = {name for name, _ in resolved_nodes}
        remaining = resolved_nodes

        stop_event = self._pipeline_stop_events.get(execution_id)
        while remaining:
            if self._shutdown_event.is_set() or (stop_event is not None and stop_event.is_set()):
                logger.info(f"Shutdown/stop requested, stopping pipeline '{execution_id}'")
                break

            ready: List[Tuple[str, Dict[str, Any]]] = []
            deferred: List[Tuple[str, Dict[str, Any]]] = []

            for node_name, cfg in remaining:
                # Both spellings, like the batch engine: a streaming node that
                # declared `dependencies:` used to have its ordering dropped.
                depends_on = [d for d in get_node_dependencies(cfg) if d not in satisfied]
                # Dependencies that exist in this pipeline but haven't resolved yet
                # belong to a later wave — defer rather than skip.
                pending_deps = [d for d in depends_on if d in all_names and d not in node_outcomes]
                if pending_deps:
                    deferred.append((node_name, cfg))
                    continue
                # Every dependency is now resolved or unknown; any non-"started"
                # one (failed, skipped, or missing from the pipeline) blocks.
                blocking = [d for d in depends_on if node_outcomes.get(d) != "started"]
                if blocking:
                    reason = f"Skipped due to unmet/failed dependencies: {blocking}"
                    self._record_skipped_node(execution_id, node_name, reason)
                    node_outcomes[node_name] = "skipped"
                    continue
                ready.append((node_name, cfg))

            if not ready:
                # No node can make progress (dependency cycle or all deferred on
                # unresolved deps); skip the rest to avoid an infinite loop.
                for node_name, _ in deferred:
                    self._record_skipped_node(
                        execution_id, node_name, "Skipped due to unresolved dependency cycle"
                    )
                    node_outcomes[node_name] = "skipped"
                break

            started_now: List[str] = []
            for node_name, outcome in self._start_node_wave(
                execution_id, pipeline_name, ready
            ).items():
                node_outcomes[node_name] = outcome
                if outcome == "started":
                    processed_nodes.append(node_name)
                    started_now.append(node_name)

            # A node with a terminating trigger (once / available_now) processes
            # what exists and stops; a node reading its output must start after
            # it finishes, or it reads an empty source and stops too.
            needed = {d for _, cfg in deferred for d in get_node_dependencies(cfg)}
            upstream_failures = self._await_terminating_upstreams(
                execution_id,
                [(n, cfg) for n, cfg in ready if n in started_now and n in needed],
                stop_event,
            )
            for failed_name, reason in upstream_failures.items():
                # Its dependants must not start on the partial output of a node
                # that died: the next wave sees "failed" and skips them.
                node_outcomes[failed_name] = "failed"
                self._handle_node_execution_error(execution_id, failed_name, reason)

            remaining = deferred

        if len(processed_nodes) != len(resolved_nodes):
            failed = [n for n, outcome in node_outcomes.items() if outcome == "failed"]
            skipped = [n for n, outcome in node_outcomes.items() if outcome == "skipped"]
            if failed:
                logger.warning(
                    f"Failed to start {len(failed)} node(s) for execution '{execution_id}': {failed}"
                )
            if skipped:
                logger.warning(
                    f"Skipped {len(skipped)} node(s) due to unmet/failed dependencies in '{execution_id}': {skipped}"
                )

        return processed_nodes

    _TERMINATING_TRIGGERS = frozenset({"once", "available_now"})

    def _await_terminating_upstreams(
        self,
        execution_id: str,
        nodes: List[Tuple[str, Dict[str, Any]]],
        stop_event: Optional[Event],
    ) -> Dict[str, str]:
        """Wait for the queries of ``nodes`` whose trigger terminates on its own.

        Returns ``{node: error}`` for those that ended with an error.
        """
        failures: Dict[str, str] = {}
        for node_name, cfg in nodes:
            trigger = ((cfg.get("streaming") or {}).get("trigger") or {}).get("type")
            if str(trigger).lower() not in self._TERMINATING_TRIGGERS:
                continue
            with self._lock:
                info = self._running_pipelines.get(execution_id) or {}
                query = (info.get("queries") or {}).get(node_name)
            await_fn = getattr(query, "awaitTermination", None)
            if not callable(await_fn):
                continue
            logger.info(
                "Waiting for '{}' ({} trigger) to finish before starting its dependants",
                node_name,
                trigger,
            )
            while True:
                if self._shutdown_event.is_set() or (
                    stop_event is not None and stop_event.is_set()
                ):
                    return failures
                try:
                    if await_fn(1.0):
                        exc = get_query_exception(query)
                        if exc:
                            failures[node_name] = f"Query ended with an error: {exc}"
                        break
                except Exception as e:
                    logger.warning("Query '{}' ended with an error: {}", node_name, e)
                    failures[node_name] = f"Query ended with an error: {e}"
                    break
        return failures

    def _start_node_wave(
        self,
        execution_id: str,
        pipeline_name: str,
        wave: List[Tuple[str, Dict[str, Any]]],
    ) -> Dict[str, str]:
        """Start every node in a wave, in parallel, and return name -> outcome."""
        if len(wave) == 1:
            node_name, cfg = wave[0]
            return {node_name: self._start_single_node(execution_id, pipeline_name, node_name, cfg)}

        outcomes: Dict[str, str] = {}
        workers = min(len(wave), self.node_start_parallelism)
        with ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix="streaming_node_start"
        ) as pool:
            future_to_name = {
                pool.submit(
                    self._start_single_node, execution_id, pipeline_name, node_name, cfg
                ): node_name
                for node_name, cfg in wave
            }
            for future in future_to_name:
                node_name = future_to_name[future]
                try:
                    outcomes[node_name] = future.result()
                except Exception as e:  # defensive: _start_single_node already traps
                    self._handle_node_execution_error(execution_id, node_name, str(e))
                    outcomes[node_name] = "failed"
        return outcomes

    def _order_nodes_by_dependencies(
        self, nodes: List[Any], satisfied_dependencies: Optional[Set[str]] = None
    ) -> List[Dict[str, Any]]:
        """Topologically order nodes by depends_on, delegating to the validator."""
        resolved_nodes = [self._get_node_config(node, idx) for idx, node in enumerate(nodes)]
        node_names = [node.get("name", f"node_{idx}") for idx, node in enumerate(resolved_nodes)]
        name_to_node = dict(zip(node_names, resolved_nodes))

        try:
            ordered_names = self.validator.topological_sort(
                name_to_node, satisfied_dependencies=satisfied_dependencies
            )
        except StreamingError as e:
            raise StreamingPipelineError(str(e), cause=e) from e

        return [name_to_node[name] for name in ordered_names]

    def _monitor_key(self, execution_id: str, query_name: str) -> str:
        return f"{execution_id}:{query_name}"

    def _record_skipped_node(self, execution_id: str, node_name: str, reason: str) -> None:
        logger.warning(f"Skipping node '{node_name}' in pipeline '{execution_id}': {reason}")
        with self._lock:
            pipeline_info = self._running_pipelines.get(execution_id)
            if pipeline_info is not None:
                pipeline_info["status"] = "partial_failure"
                pipeline_info.setdefault("skipped_nodes", {})[node_name] = reason

    def _get_node_config(self, node_config: Any, idx: int) -> Dict[str, Any]:
        if isinstance(node_config, str):
            actual_config = getattr(self.context, "nodes_config", {}).get(node_config)
            if not actual_config:
                raise StreamingPipelineError(
                    f"Node configuration '{node_config}' not found",
                    pipeline_name=None,
                    execution_id=None,
                )
            return {**actual_config, "name": node_config}

        if isinstance(node_config, dict):
            if "name" not in node_config:
                return {**node_config, "name": f"node_{idx}"}
            return node_config

        raise StreamingPipelineError(
            f"Invalid node configuration type: {type(node_config)}",
            pipeline_name=None,
            execution_id=None,
        )

    # ── journal and events ───────────────────────────────────────────────────

    def add_listener(self, listener: Callable[[Dict[str, Any]], None]) -> None:
        """Tell *listener* about every execution event, as a dict with a ``kind``:

        ``finished`` (status, error, per-node outcome, journal dir), and the live ones
        ``stream_failed`` / ``stream_stalled`` / ``stream_quarantine`` /
        ``stream_recovered``. Called from manager threads; errors are logged.
        """
        self._listeners.append(listener)

    def _emit(self, event: Dict[str, Any]) -> None:
        for listener in list(self._listeners):
            try:
                listener(dict(event))
            except Exception as e:  # a listener must never break the stream
                logger.warning(f"Stream event listener failed on '{event.get('kind')}': {e}")

    def _open_journal(
        self, execution_id: str, pipeline_name: str, pipeline_config: Dict[str, Any], run_id: str
    ) -> None:
        base = journal_base(self.context)
        if base is None:
            return
        names = [
            node if isinstance(node, str) else (node or {}).get("name", f"node_{i}")
            for i, node in enumerate(pipeline_config.get("nodes", []) or [])
        ]
        gs = get_context_value(self.context, "global_config", {}) or {}
        try:
            journal = StreamRunJournal(
                base,
                pipeline_name,
                run_id,
                execution_id,
                [str(n) for n in names],
                api_execution_id=gs.get("api_execution_id") if isinstance(gs, dict) else None,
            )
        except OSError as e:
            logger.warning(f"Stream journal unavailable for '{pipeline_name}': {e}")
            return
        with self._lock:
            self._journals[execution_id] = journal
            if execution_id in self._running_pipelines:
                self._running_pipelines[execution_id]["journal_dir"] = str(journal.dir)

    def _journal_status(self, execution_id: str) -> None:
        with self._lock:
            journal = self._journals.get(execution_id)
            info = self._running_pipelines.get(execution_id) or {}
            status, error = info.get("status"), info.get("error")
        if journal is not None and status:
            journal.set_status(str(status), error)

    def _own_query_locked(self, execution_id: str, node_name: str, query: Any) -> None:
        """Remember which node *query* runs, for its progress reports. Caller holds the lock."""
        qname = getattr(query, "name", None) or getattr(query, "queryName", None)
        if qname:
            self._query_owner[str(qname)] = (execution_id, node_name)

    def _on_progress(self, query_name: str, summary: Dict[str, Any]) -> None:
        with self._lock:
            owner = self._query_owner.get(query_name)
            journal = self._journals.get(owner[0]) if owner else None
        if owner is None or journal is None:
            return
        journal.record(
            "progress",
            {
                "node": owner[1],
                "batch_id": summary.get("batchId"),
                "rows": summary.get("numInputRows"),
                "trigger_ms": summary.get("triggerExecutionMs"),
                "input_rows_per_second": summary.get("inputRowsPerSecond"),
                "processed_rows_per_second": summary.get("processedRowsPerSecond"),
                # Stateful queries and their sources (None when Spark has nothing).
                "watermark": summary.get("watermark"),
                "state_rows": summary.get("stateRows"),
                "state_memory_bytes": summary.get("stateMemoryBytes"),
                "late_rows_dropped": summary.get("lateRowsDropped"),
                "source_lag": summary.get("sourceLag"),
                # What Spark reads: more than the node declares when its transform joins.
                "sources": summary.get("sources"),
            },
        )

    def _on_micro_batch(self, pipeline_name: str, execution_id: str, stats: Dict[str, Any]) -> None:
        node = str(stats.get("node"))
        with self._lock:
            journal = self._journals.get(execution_id)
            info = self._running_pipelines.get(execution_id)
            if info is not None:
                seen = info.setdefault("micro_batches", {}).setdefault(
                    node, {"rows_quarantined": 0, "gate": None, "batch_id": None}
                )
                seen["rows_quarantined"] += int(stats.get("rows_quarantined") or 0)
                seen["gate"] = stats.get("gate") or seen["gate"]
                seen["batch_id"] = stats.get("batch_id")
        if journal is not None:
            journal.record("batch", stats)
        self._note_quarantine(execution_id, pipeline_name, stats)

    def _seed_adaptive_history(
        self, execution_id: str, pipeline_name: str, nodes: List[Dict[str, Any]]
    ) -> None:
        """Give each adaptive node the batch durations its previous run journaled."""
        base = journal_base(self.context)
        if base is None:
            return
        with self._lock:
            run_id = (self._running_pipelines.get(execution_id) or {}).get("run_id")
        for cfg in nodes:
            trigger = ((cfg.get("streaming") or {}).get("trigger")) or {}
            if str(trigger.get("type", "")).lower() != "adaptive":
                continue
            name = str(cfg.get("name"))
            try:
                values = recent_trigger_ms(base, pipeline_name, name, exclude_run=run_id)
            except OSError as e:
                logger.debug(f"Could not read the journal history of '{name}': {e}")
                continue
            if values:
                self.progress_sink.seed(f"{pipeline_name}::{name}", values)
                logger.info(
                    f"Adaptive trigger of '{name}' starts from {len(values)} batch "
                    "duration(s) its previous run journaled"
                )

    def _finish_execution(self, execution_id: str) -> None:
        """Journal the final status and tell the listeners, once per execution."""
        with self._lock:
            if execution_id in self._finished:
                return
            self._finished.add(execution_id)
            journal = self._journals.get(execution_id)
            for qname in [q for q, owner in self._query_owner.items() if owner[0] == execution_id]:
                self._query_owner.pop(qname, None)
        status = self._compute_pipeline_status(execution_id) or {}
        nodes: Dict[str, Dict[str, Any]] = {}
        summaries = status.get("node_summaries") or {}
        journaled = summarize(journal.dir) if journal is not None else {}
        for name in node_names(status):
            state = derive_node_state(name, status)
            nodes[name] = {
                "state": state.state,
                "error": state.error,
                "sink": (summaries.get(name) or {}).get("sink"),
                "totals": (status.get("totals") or {}).get(name),
                **({"journal": journaled[name]} if name in journaled else {}),
            }
        # A failure that ended the run between two monitor passes is still reported.
        self._report_transitions(execution_id, status)
        self._flush_quarantine(execution_id, force=True)
        final = str(status.get("status") or "error")
        if journal is not None:
            journal.set_status(final, status.get("error"), nodes=nodes)
        self._emit(
            {
                "kind": "finished",
                "execution_id": execution_id,
                "run_id": status.get("run_id"),
                "pipeline": status.get("pipeline_name"),
                "status": final,
                "error": status.get("error"),
                "start_time": status.get("start_time"),
                "end_time": status.get("end_time") or time.time(),
                "nodes": nodes,
                "journal_dir": str(journal.dir) if journal is not None else None,
            }
        )

    # ── live alerts ──────────────────────────────────────────────────────────

    def _ensure_health_monitor(self) -> None:
        """Start the daemon that checks every live execution (once per manager)."""
        if self.health_interval_seconds <= 0:
            return
        with self._lock:
            if self._health_thread is not None and self._health_thread.is_alive():
                return
            self._health_thread = Thread(
                target=self._health_loop, name="Ducta-stream-health", daemon=True
            )
            self._health_thread.start()

    def _health_loop(self) -> None:
        while not self._shutdown_event.wait(self.health_interval_seconds):
            self.check_health_now()

    def check_health_now(self) -> None:
        """One monitor pass: refresh every live execution's health and report changes."""
        with self._lock:
            live = [
                eid
                for eid, info in self._running_pipelines.items()
                if eid not in self._finished
                and info.get("status") in ("starting", "running", "partial_failure")
            ]
        for eid in live:
            try:
                status = self._compute_pipeline_status(eid)
                if status:
                    self._report_transitions(eid, status)
                self._flush_quarantine(eid)
            except Exception as e:  # noqa: BLE001 - the monitor must keep going
                logger.debug(f"Health pass failed for '{eid}': {e}")

    def _report_transitions(self, execution_id: str, status: Dict[str, Any]) -> None:
        """Emit stream_failed / stream_stalled once per episode, and stream_recovered."""
        for name in node_names(status):
            state = derive_node_state(name, status)
            if state.state == "failed" and self._restart_will_handle(execution_id, name, status):
                continue  # the watcher schedules its restart within a second
            if state.state == "failed":
                kind: Optional[str] = "stream_failed"
            elif state.health == "stalled":
                kind = "stream_stalled"
            else:
                kind = None
            key = (execution_id, name)
            with self._lock:
                previous = self._alerted.get(key)
                if kind == previous:
                    continue
                if kind is None:
                    self._alerted.pop(key, None)
                else:
                    self._alerted[key] = kind
            if kind is None and previous is None:
                continue
            self._emit(
                {
                    "kind": kind or "stream_recovered",
                    "execution_id": execution_id,
                    "run_id": status.get("run_id"),
                    "pipeline": status.get("pipeline_name"),
                    "node": name,
                    "error": state.error,
                    "previous": previous,
                }
            )

    def _note_quarantine(
        self, execution_id: str, pipeline_name: str, stats: Dict[str, Any]
    ) -> None:
        """Count quarantined rows; the first batch of an episode is reported at once."""
        rows = int(stats.get("rows_quarantined") or 0)
        if rows <= 0:
            return
        key = (execution_id, str(stats.get("node")))
        with self._lock:
            pending = self._quarantine_pending.setdefault(
                key, {"rows": 0, "batches": 0, "last_sent": None, "pipeline": pipeline_name}
            )
            pending["rows"] += rows
            pending["batches"] += 1
            first = pending["last_sent"] is None
        if first:
            self._flush_quarantine(execution_id, force=True, only=key)

    def _flush_quarantine(
        self, execution_id: str, force: bool = False, only: Optional[Tuple[str, str]] = None
    ) -> None:
        """Report the quarantine counted since the last report, at most once an interval."""
        now = time.time()
        due: List[Tuple[Tuple[str, str], Dict[str, Any]]] = []
        with self._lock:
            run_id = (self._running_pipelines.get(execution_id) or {}).get("run_id")
            for key, pending in self._quarantine_pending.items():
                if key[0] != execution_id or (only is not None and key != only):
                    continue
                if not pending["rows"]:
                    continue
                last = pending["last_sent"]
                if force or last is None or now - last >= self.quarantine_alert_interval_seconds:
                    due.append((key, dict(pending)))
                    pending.update(rows=0, batches=0, last_sent=now)
        for (eid, node), pending in due:
            self._emit(
                {
                    "kind": "stream_quarantine",
                    "execution_id": eid,
                    "run_id": run_id,
                    "pipeline": pending["pipeline"],
                    "node": node,
                    "rows": pending["rows"],
                    "batches": pending["batches"],
                }
            )

    def _stop_requested_locked(self, execution_id: str) -> bool:
        """Whether *execution_id* is being stopped (or the manager shut down). Caller holds ``self._lock``."""
        if self._shutdown_event.is_set():
            return True
        stop_event = self._pipeline_stop_events.get(execution_id)
        if stop_event is not None and stop_event.is_set():
            return True
        info = self._running_pipelines.get(execution_id)
        return info is not None and info.get("status") == "stopped"

    def _stop_unregistered_query(self, query: Any, node_name: str) -> None:
        """Stop a query that started after its pipeline was stopped (best effort)."""
        try:
            self.query_manager.stop_query(query, graceful=True, timeout_seconds=10)
        except Exception as e:
            logger.error(f"Could not stop query '{node_name}' started after a stop: {e}")

    def _has_live_queries(self, execution_id: str) -> bool:
        """Whether any query of *execution_id* still runs, whatever its status says.

        A stop that failed for one query leaves the pipeline ``stopped`` with that
        query up; what is alive, not the status, decides what may be cleared.
        """
        with self._lock:
            info = self._running_pipelines.get(execution_id) or {}
            queries = list((info.get("queries") or {}).values())
        return any(self.query_manager._is_query_active(q) for q in queries if q is not None)

    def _handle_node_execution_error(self, execution_id: str, node_name: str, error: str) -> None:
        logger.error(f"Error starting node '{node_name}' in pipeline '{execution_id}': {error}")
        with self._lock:
            if execution_id in self._running_pipelines:
                self._running_pipelines[execution_id]["status"] = "partial_failure"
                self._running_pipelines[execution_id]["error"] = error
                self._running_pipelines[execution_id].setdefault("failed_nodes", {})[node_name] = (
                    error
                )

    def _stop_pipeline_queries(
        self,
        queries: Dict[str, Any],
        execution_id: str,
        graceful: bool,
        timeout_seconds: float,
    ) -> Tuple[List[str], Dict[str, str]]:
        """Stop every query in *queries*."""
        stopped_queries: List[str] = []
        failed_queries: Dict[str, str] = {}

        for query_name, query in queries.items():
            try:
                if query is None:
                    continue
                if self.query_manager._is_query_active(query):
                    logger.debug(f"Stopping query '{query_name}' in pipeline '{execution_id}'")
                    self.query_manager.stop_query(query, graceful, timeout_seconds)
                    stopped_queries.append(query_name)
                else:
                    self.query_manager._remove_query_from_active(query)
                    stopped_queries.append(query_name)
            except Exception as e:
                logger.error(f"Error stopping query '{query_name}': {str(e)}")
                failed_queries[query_name] = str(e)

        return stopped_queries, failed_queries

    def _update_pipeline_stop_status(
        self, execution_id: str, stopped_queries: List[str], failed_queries: Dict[str, str]
    ) -> None:
        with self._lock:
            if execution_id in self._running_pipelines:
                self._running_pipelines[execution_id]["status"] = "stopped"
                self._running_pipelines[execution_id]["end_time"] = time.time()
                self._running_pipelines[execution_id]["stopped_queries"] = stopped_queries
                self._running_pipelines[execution_id]["failed_queries"] = len(failed_queries)
                if failed_queries:
                    self._running_pipelines[execution_id]["failed_query_errors"] = failed_queries
                for record in (
                    self._running_pipelines[execution_id].get("restarts") or {}
                ).values():
                    record["pending"] = False  # a stop cancels any scheduled restart

            # Drop monitors under the same lock that guards _query_monitors elsewhere.
            for query_name in stopped_queries:
                self._query_monitors.pop(self._monitor_key(execution_id, query_name), None)

        self._signal_pipeline_done(execution_id)

    def stop_pipeline(
        self,
        execution_id: str,
        graceful: bool = True,
        timeout_seconds: float = 30.0,
    ) -> bool:
        try:
            stop_event = self._pipeline_stop_events.get(execution_id)
            if stop_event is not None:
                stop_event.set()

            with self._lock:
                pipeline_info = self._running_pipelines.get(execution_id)
                future = self._pipeline_threads.get(execution_id)
                queries_snapshot = dict(pipeline_info.get("queries", {})) if pipeline_info else {}

            if not pipeline_info:
                return False

            stopped_queries, failed_queries = self._stop_pipeline_queries(
                queries_snapshot, execution_id, graceful, timeout_seconds
            )

            with self._lock:
                pipeline_info = self._running_pipelines.get(execution_id)
                current_queries = dict(pipeline_info.get("queries", {})) if pipeline_info else {}
            newly_added = {
                name: query
                for name, query in current_queries.items()
                if name not in queries_snapshot
            }
            if newly_added:
                logger.warning(
                    "Pipeline '{}': {} quer{} started after the initial stop snapshot; "
                    "stopping {} too",
                    execution_id,
                    len(newly_added),
                    "y" if len(newly_added) == 1 else "ies",
                    "it" if len(newly_added) == 1 else "them",
                )
                extra_stopped, extra_failed = self._stop_pipeline_queries(
                    newly_added, execution_id, graceful, timeout_seconds
                )
                stopped_queries.extend(extra_stopped)
                failed_queries.update(extra_failed)

            if future and not graceful:
                future.cancel()

            self._update_pipeline_stop_status(execution_id, stopped_queries, failed_queries)
            return not failed_queries

        except Exception as e:
            logger.error(f"Error stopping pipeline '{execution_id}': {str(e)}")
            with self._lock:
                if execution_id in self._running_pipelines:
                    self._running_pipelines[execution_id]["status"] = "error"
                    self._running_pipelines[execution_id]["error"] = str(e)
            self._signal_pipeline_done(execution_id)
            raise StreamingPipelineError(
                f"Failed to stop pipeline '{execution_id}': {str(e)}",
                execution_id=execution_id,
                cause=e,
            ) from e

    def _get_single_query_status(self, query):
        if query is None:
            return {"status": "unknown"}, False, False
        try:
            is_active = self.query_manager._is_query_active(query)
            status = {
                "id": getattr(query, "id", None),
                "runId": str(getattr(query, "runId", "")),
                "isActive": is_active,
                "lastProgress": getattr(query, "lastProgress", None) if is_active else None,
            }
            if is_active:
                return status, True, False

            exception = get_query_exception(query)
            if exception:
                status["exception"] = str(exception)
                return status, False, True

            return status, False, False
        except Exception as e:
            return {"error": str(e)}, False, True

    def _collect_query_statuses(self, queries: Dict[str, Any]):
        query_statuses = {}
        active_queries = 0
        failed_queries = 0

        for query_name, query in queries.items():
            status, is_active, is_failed = self._get_single_query_status(query)
            query_statuses[query_name] = status
            if is_active:
                active_queries += 1
            if is_failed:
                failed_queries += 1

        return query_statuses, active_queries, failed_queries

    def get_pipeline_status(
        self, execution_id: str, force_refresh: bool = False
    ) -> Optional[Dict[str, Any]]:
        """Return a status snapshot, served from a short-TTL cache when fresh."""
        if not force_refresh and self._status_cache_ttl > 0:
            with self._status_cache_lock:
                cached = self._status_cache.get(execution_id)
                if cached and (time.time() - cached[0]) < self._status_cache_ttl:
                    # A copy: callers may add keys to what they get back.
                    return dict(cached[1])

        status = self._compute_pipeline_status(execution_id)

        if status is not None and self._status_cache_ttl > 0:
            with self._status_cache_lock:
                # Cached as a copy: the caller owns the dict it is handed.
                self._status_cache[execution_id] = (time.time(), dict(status))
        return status

    def _compute_pipeline_status(self, execution_id: str) -> Optional[Dict[str, Any]]:
        try:
            self._refresh_query_health(execution_id)

            with self._lock:
                pipeline_info = self._running_pipelines.get(execution_id)
                if not pipeline_info:
                    return None

                # ``pipeline_config`` stays inside the manager: it holds every node's
                # connector options (broker credentials included) and the snapshot is
                # printed by the CLI and serialised by callers.
                status = {
                    k: v
                    for k, v in pipeline_info.items()
                    if k not in ("queries", "pipeline_config")
                }
                status["execution_id"] = execution_id
                if pipeline_info.get("restarts"):
                    # A copy: the watcher keeps changing the manager's own records.
                    status["restarts"] = {
                        node: dict(record) for node, record in pipeline_info["restarts"].items()
                    }
                queries_snapshot = dict(pipeline_info.get("queries", {}))

            query_statuses, active_queries, failed_queries = self._collect_query_statuses(
                queries_snapshot
            )
            status["query_statuses"] = query_statuses
            status["active_queries"] = active_queries
            status["failed_queries"] = failed_queries
            status["total_queries"] = len(queries_snapshot)
            if "start_time" in status:
                end_time = status.get("end_time", time.time())
                status["uptime_seconds"] = end_time - status["start_time"]

            prefix = f"{execution_id}:"
            with self._lock:
                monitors_snapshot = [
                    (key, monitor)
                    for key, monitor in self._query_monitors.items()
                    if key.startswith(prefix)
                ]
            monitor_statuses = {
                key.split(":", 1)[1]: monitor.get_status_dict()
                for key, monitor in monitors_snapshot
            }
            if monitor_statuses:
                status["health_monitors"] = monitor_statuses

            # Push-model batch metrics (durations / throughput) captured by the
            # progress listener — no extra py4j RPC, keyed back to node names.
            progress_metrics: Dict[str, Any] = {}
            for node_name, query in queries_snapshot.items():
                qname = getattr(query, "name", None) or getattr(query, "queryName", None)
                if not qname:
                    continue
                latest = self.progress_sink.get_latest(qname)
                if latest:
                    progress_metrics[node_name] = latest
            if progress_metrics:
                status["progress_metrics"] = progress_metrics
            # What each node has processed in total: live for running queries, the
            # figures kept at the end for the ones that stopped.
            totals = dict(status.get("totals") or {})
            for node_name, query in queries_snapshot.items():
                qname = getattr(query, "name", None) or getattr(query, "queryName", None)
                live = self.progress_sink.totals(qname) if qname else None
                if live:
                    totals[node_name] = live
            if totals:
                status["totals"] = totals
            # The model each scoring query was pinned to when it started.
            served = self.query_manager.served_models(execution_id)
            if served:
                status["served_models"] = served
            return status
        except Exception as e:
            logger.error(f"Error getting pipeline status for '{execution_id}': {str(e)}")
            return {
                "execution_id": execution_id,
                "status": "error",
                "error": f"Failed to get status: {str(e)}",
            }

    def _refresh_query_health(self, execution_id: str) -> None:
        """Update pipeline status based on query health monitors."""
        prefix = f"{execution_id}:"

        with self._lock:
            monitors = [
                (key, monitor)
                for key, monitor in self._query_monitors.items()
                if key.startswith(prefix)
            ]

        unhealthy: Dict[str, str] = {}
        for monitor_key, monitor in monitors:
            is_healthy, error = monitor.check_health()
            if not is_healthy and error:
                node_name = monitor_key.split(":", 1)[1]
                unhealthy[node_name] = error

        with self._lock:
            pipeline_info = self._running_pipelines.get(execution_id)
            if pipeline_info is None:
                return

            if unhealthy:
                pipeline_info["unhealthy_nodes"] = dict(unhealthy)
            else:
                pipeline_info.pop("unhealthy_nodes", None)

            if pipeline_info.get("status") in ("running", "partial_failure"):
                if unhealthy:
                    pipeline_info["status"] = "partial_failure"
                elif not pipeline_info.get("failed_nodes") and not pipeline_info.get(
                    "skipped_nodes"
                ):
                    pipeline_info["status"] = "running"

    def restart_node(self, execution_id: str, node_name: str) -> bool:
        """Restart a specific node in a running pipeline."""
        try:
            # Read shared state under the lock, then release it before blocking.
            with self._lock:
                pipeline_info = self._running_pipelines.get(execution_id)
                if not pipeline_info:
                    logger.error(f"Execution '{execution_id}' not found")
                    return False
                done_event = self._pipeline_events.get(execution_id)
                if self._stop_requested_locked(execution_id) or (
                    done_event is not None and done_event.is_set()
                ):
                    # Nothing watches a finished execution any more: a query
                    # started now would run unseen.
                    logger.error(
                        f"Execution '{execution_id}' has finished or is stopping; "
                        f"cannot restart '{node_name}'"
                    )
                    return False
                existing_query = pipeline_info["queries"].get(node_name)
                pipeline_config = pipeline_info["pipeline_config"]
                pipeline_name = pipeline_info["pipeline_name"]

            # Resolve node config (pipeline_config is effectively immutable here).
            node_config = None
            for idx, nc in enumerate(pipeline_config.get("nodes", [])):
                resolved = self._get_node_config(nc, idx)
                if resolved.get("name") == node_name:
                    node_config = resolved
                    break

            if not node_config:
                logger.error(f"Node '{node_name}' configuration not found in pipeline")
                return False

            # Stop the existing query without holding the lock (can block up to timeout).
            if existing_query:
                try:
                    self.query_manager.stop_query(existing_query, graceful=True, timeout_seconds=10)
                except Exception as e:
                    logger.warning(f"Error stopping existing query for node '{node_name}': {e}")

            # Start the query again without holding the lock (retry loop may sleep).
            query = self._start_node_query_with_retry(
                execution_id=execution_id,
                pipeline_name=pipeline_name,
                node_name=node_name,
                node_config=node_config,
            )

            # Re-acquire the lock to publish the new query/monitor, unless a stop
            # landed meanwhile: then the new query is stopped instead.
            summary = self._node_summary(node_config, pipeline_name)
            with self._lock:
                pipeline_info = self._running_pipelines.get(execution_id)
                published = pipeline_info is not None and not self._stop_requested_locked(
                    execution_id
                )
                if published and pipeline_info is not None:
                    pipeline_info["queries"][node_name] = query
                    self._own_query_locked(execution_id, node_name, query)
                    failed_nodes = pipeline_info.get("failed_nodes") or {}
                    failed_nodes.pop(node_name, None)
                    if not failed_nodes:
                        # The error shown was this node's; it no longer applies.
                        pipeline_info["error"] = None
                    if summary:
                        pipeline_info.setdefault("node_summaries", {})[node_name] = summary
                    self._query_monitors[self._monitor_key(execution_id, node_name)] = (
                        QueryHealthMonitor(
                            query=query,
                            query_name=node_name,
                            timeout_seconds=self._stall_timeout_seconds(node_config),
                        )
                    )
            if not published:
                logger.error(
                    f"Pipeline '{execution_id}' was stopped or dropped during the "
                    f"restart of '{node_name}'"
                )
                self._stop_unregistered_query(query, node_name)
                return False

            logger.info(f"Successfully restarted node '{node_name}' in pipeline '{execution_id}'")
            return True

        except Exception as e:
            logger.error(f"Failed to restart node '{node_name}': {str(e)}")
            return False

    #: What a Spark checkpoint directory contains; a tree with none of these is
    #: not one, and ``clear_pipeline_checkpoints`` will not delete it.
    _CHECKPOINT_MARKERS = frozenset({"offsets", "commits", "metadata"})

    def _checkpoint_bases_for(self, pipeline_name: str) -> List[str]:
        """Every base directory under which *pipeline_name*'s checkpoints can live.

        The project-wide default, plus each node's own ``streaming.checkpoint_location``
        (a node's value is a base too: the pipeline and node names are appended).
        """
        bases: List[str] = []

        def add(base: Any) -> None:
            if isinstance(base, str) and base and base not in bases:
                bases.append(base)

        try:
            add(self.query_manager._determine_checkpoint_base(None))
        except Exception:
            pass  # no project-wide default configured; node-level ones may exist

        configs: List[Any] = []
        with self._lock:
            configs.extend(
                info.get("pipeline_config")
                for info in self._running_pipelines.values()
                if info.get("pipeline_name") == pipeline_name
            )
        defined = (get_context_value(self.context, "pipelines_config", {}) or {}).get(pipeline_name)
        configs.append(defined)

        for config in configs:
            if not isinstance(config, dict):
                continue
            for idx, node in enumerate(config.get("nodes", []) or []):
                try:
                    resolved = self._get_node_config(node, idx)
                except Exception:
                    continue
                add(((resolved.get("streaming") or {}).get("checkpoint_location")))
        return bases

    def _looks_like_checkpoint_tree(self, directory: Any) -> bool:
        """Whether *directory* holds Spark checkpoint data, or no data at all.

        A tree of empty folders (a checkpoint directory created for a query that
        failed before writing anything) qualifies; one with files that are not a
        checkpoint's does not.
        """
        has_files = False
        for _root, dirs, files in os.walk(directory):
            if self._CHECKPOINT_MARKERS & (set(dirs) | set(files)):
                return True  # stops at the first marker, so a real checkpoint is cheap
            has_files = has_files or bool(files)
        return not has_files

    def clear_pipeline_checkpoints(self, pipeline_name: str) -> Dict[str, Any]:
        """Clear all checkpoint directories for a given pipeline.

        Covers the project default and every node-level ``checkpoint_location``.
        Checkpoints on cloud storage are not deleted (this manager does not
        reach it); they are listed under ``manual`` for the caller to remove.
        """
        try:
            with self._lock:
                candidates = [
                    eid
                    for eid, info in self._running_pipelines.items()
                    if info.get("pipeline_name") == pipeline_name
                ]
            # Any execution with a query still up, whatever its status says (a
            # "stopped" one whose stop failed for a query still writes there).
            active = [
                eid
                for eid in candidates
                if self.is_query_active(eid) or self._has_live_queries(eid)
            ]
            if active:
                return {
                    "status": "error",
                    "message": (
                        f"Refusing to clear checkpoints: pipeline '{pipeline_name}' has "
                        f"active execution(s) {active}. Stop them first."
                    ),
                }

            bases = self._checkpoint_bases_for(pipeline_name)
            if not bases:
                return {"status": "error", "message": "Could not determine checkpoint base"}

            safe_pipeline = self.query_manager._sanitize_path_component(pipeline_name)
            cleared: List[str] = []
            manual: List[str] = []
            refused: List[str] = []

            for base in bases:
                if CheckpointManager.is_cloud_path(base):
                    manual.append(f"{base.rstrip('/')}/{safe_pipeline}")
                    continue
                local_base = base[len("file://") :] if base.startswith("file://") else base
                base_resolved = Path(local_base).resolve()
                target = (base_resolved / safe_pipeline).resolve()

                # Containment check: the resolved target must live strictly under the
                # checkpoint base. Defends against traversal even if sanitisation changes.
                if base_resolved not in target.parents:
                    refused.append(f"{target} (outside its checkpoint base)")
                    continue
                if not target.exists():
                    continue
                # Defense in depth: only a directory that holds checkpoint data (or
                # nothing at all) is deleted.
                if not self._looks_like_checkpoint_tree(target):
                    refused.append(f"{target} (does not look like a checkpoint directory)")
                    continue
                shutil.rmtree(target)
                cleared.append(str(target))
                logger.info(f"Cleared checkpoints for pipeline '{pipeline_name}' at {target}")

            result: Dict[str, Any] = {"cleared": cleared}
            if manual:
                result["manual"] = manual
            if refused:
                result["refused"] = refused

            if refused or (manual and not cleared):
                problems = refused + [f"{m} (cloud storage: delete it manually)" for m in manual]
                result.update(
                    status="error",
                    message=f"Could not clear every checkpoint of '{pipeline_name}': {problems}",
                )
            elif cleared:
                suffix = f" Delete these on cloud storage yourself: {manual}." if manual else ""
                result.update(
                    status="success",
                    message=f"Cleared all checkpoints for pipeline '{pipeline_name}'.{suffix}",
                    path=cleared[0],
                )
            else:
                result.update(
                    status="success",
                    message=f"No checkpoint directory found for pipeline '{pipeline_name}'",
                    path=str((Path(bases[0]) / safe_pipeline)),
                )
            return result

        except Exception as e:
            logger.error(f"Failed to clear checkpoints for '{pipeline_name}': {e}")
            return {"status": "error", "message": str(e)}

    def list_pipelines(self) -> List[Dict[str, Any]]:
        """Status of every pipeline this manager has started, whatever its state.

        Unlike :meth:`list_running_pipelines`, a ``partial_failure`` pipeline — one
        node failed, the others still streaming — and a stopped or failed one are
        included: those are the states someone watching needs to see.
        """
        with self._lock:
            execution_ids = list(self._running_pipelines)
        statuses = []
        for execution_id in execution_ids:
            status = self.get_pipeline_status(execution_id)
            if status:
                statuses.append(status)
        return statuses

    def running_pipeline_configs(self) -> List[Dict[str, Any]]:
        """The definitions of the pipelines that are up, for resource-conflict checks.

        Kept apart from the status snapshots, which do not carry the definition.
        """
        with self._lock:
            candidates = [
                (eid, info["pipeline_config"])
                for eid, info in self._running_pipelines.items()
                if info.get("status") in ("running", "starting", "partial_failure")
            ]
        return [cfg for eid, cfg in candidates if self.is_query_active(eid)]

    def list_running_pipelines(self) -> List[Dict[str, Any]]:
        """Status of the pipelines that are up. A ``partial_failure`` one with
        queries still running counts: one node failed, the others stream on."""
        try:
            with self._lock:
                execution_ids = [
                    eid
                    for eid, info in self._running_pipelines.items()
                    if info.get("status") in ("running", "starting", "partial_failure")
                ]

            pipelines = []
            for execution_id in execution_ids:
                status = self.get_pipeline_status(execution_id)
                if not status:
                    continue
                if (
                    status.get("status") == "partial_failure"
                    and not status.get("active_queries")
                    and not any(r.get("pending") for r in (status.get("restarts") or {}).values())
                ):
                    continue
                pipelines.append(status)
            return pipelines
        except Exception as e:
            logger.error(f"Error listing running pipelines: {str(e)}")
            return []

    @handle_streaming_error
    def shutdown(self, timeout_seconds: int = 30) -> Dict[str, bool]:
        logger.info("Shutting down StreamingPipelineManager...")
        self._shutdown_event.set()

        results: Dict[str, bool] = {}
        with self._lock:
            by_status = [
                eid
                for eid, info in self._running_pipelines.items()
                if info.get("status") in ("running", "starting", "partial_failure")
            ]
            others = [eid for eid in self._running_pipelines if eid not in by_status]
        # A stopped/error/completed execution may still hold a live query (a stop
        # that failed for it): shutdown stops those too.
        execution_ids = by_status + [eid for eid in others if self._has_live_queries(eid)]

        for execution_id in execution_ids:
            try:
                results[execution_id] = self.stop_pipeline(
                    execution_id,
                    graceful=True,
                    timeout_seconds=timeout_seconds // 2,
                )
            except Exception as e:
                logger.error(f"Error stopping pipeline '{execution_id}' during shutdown: {str(e)}")
                results[execution_id] = False

        with self._lock:
            futures = list(self._pipeline_threads.items())

        for execution_id, future in futures:
            try:
                future.result(timeout=0)
            except FutureTimeoutError:
                future.cancel()
            except Exception:
                future.cancel()
            finally:
                with self._lock:
                    self._pipeline_threads.pop(execution_id, None)

        self._deregister_progress_listener()
        self._executor.shutdown(wait=False)
        logger.info("StreamingPipelineManager shutdown complete")
        return results

    def _deregister_progress_listener(self) -> None:
        """Detach the progress listener from the shared SparkSession (best-effort)."""
        listener = self._progress_listener
        if listener is None:
            return
        spark = self._get_spark()
        try:
            if spark is not None:
                spark.streams.removeListener(listener)
        except Exception as e:
            logger.debug(f"Could not remove streaming progress listener: {e}")
        finally:
            self._progress_listener = None
