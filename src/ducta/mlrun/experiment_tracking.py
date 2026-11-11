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

import atexit
import json
import math
import operator
import threading
import weakref
from collections import OrderedDict, defaultdict, deque
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set, cast
from uuid import uuid4

import pandas as pd  # type: ignore
from loguru import logger  # type: ignore

from ducta.mlrun.concurrency import file_lock
from ducta.mlrun.exceptions import (
    ArtifactNotFoundError,
    ExperimentNotFoundError,
    InvalidMetricError,
    ResourceLimitError,
    RunLimitExceededError,
    RunNotActiveError,
    RunNotFoundError,
)
from ducta.mlrun.storage import StorageBackend
from ducta.mlrun.validators import (
    plain_number,
    validate_description,
    validate_experiment_name,
    validate_run_name,
    validate_tags,
)

DEFAULT_MAX_ACTIVE_RUNS = 100
DEFAULT_METRIC_BUFFER_SIZE = 100
DEFAULT_STALE_RUN_AGE_SECONDS = 3600.0  # 1 hour
DEFAULT_MAX_METRICS_PER_KEY = 10000  # Max metrics per key in memory (rolling window)
DEFAULT_MAX_METRICS_PER_RUN = 100000  # Absolute limit per run

# Comparison operators accepted in metric filters (search_runs / _compare).
# `operator.gt` etc. work equally well applied to a scalar (_compare) or a
# pandas Series (_search_runs_optimized) — shared so the two call sites can't
# support a different operator set from each other.
_METRIC_OPS = {
    ">": operator.gt,
    "<": operator.lt,
    ">=": operator.ge,
    "<=": operator.le,
    "==": operator.eq,
}


class MetricRollingWindow:
    """
    Rolling window container for metrics that auto-evicts oldest when full.
    """

    def __init__(self, max_size: int = DEFAULT_MAX_METRICS_PER_KEY):
        """Initialize with max size."""
        self.max_size = max_size
        self.metrics: deque = deque(maxlen=max_size)
        self._evictions = 0

    def add(self, metric: "Metric") -> None:
        """
        Add metric to window, auto-evict oldest if full.
        """
        if len(self.metrics) >= self.max_size:
            self._evictions += 1
            if self._evictions % 1000 == 0:
                logger.warning(
                    f"Metric rolling window evicting old metrics. "
                    f"Total evictions: {self._evictions}. "
                    f"Consider increasing max_size or logging less frequently."
                )

        self.metrics.append(metric)

    def __len__(self) -> int:
        """Number of metrics currently retained in the window."""
        return len(self.metrics)

    def get_all(self) -> List["Metric"]:
        """Get all metrics in window."""
        return list(self.metrics)

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about this window."""
        return {
            "size": len(self.metrics),
            "max_size": self.max_size,
            "evictions": self._evictions,
            "is_full": len(self.metrics) >= self.max_size,
        }


class MetricIndex:
    """
    Fast index for metrics enabling O(1) lookups.
    """

    def __init__(self, max_size: int = DEFAULT_MAX_METRICS_PER_KEY):
        """Initialize empty indexes with an optional per-key capacity limit."""
        self.max_size = max_size
        self.by_key: Dict[str, deque] = {}
        self._lock = threading.RLock()

    def index_metric(self, metric: "Metric") -> None:
        """Add metric to the index (the oldest drops out past ``max_size``)."""
        with self._lock:
            if metric.key not in self.by_key:
                self.by_key[metric.key] = deque(maxlen=self.max_size)
            self.by_key[metric.key].append(metric)

    def get_latest(self, key: str) -> Optional["Metric"]:
        """Get latest metric for a key (O(1) access to deque tail)."""
        with self._lock:
            buf = self.by_key.get(key)
            return buf[-1] if buf else None

    def get_stats(self) -> Dict[str, Any]:
        """Get index statistics."""
        with self._lock:
            total_metrics = sum(len(m) for m in self.by_key.values())
            return {
                "indexed_keys": len(self.by_key),
                "total_metrics": total_metrics,
                "avg_metrics_per_key": total_metrics / len(self.by_key) if self.by_key else 0,
            }

    def clear(self) -> None:
        """Clear all indexes."""
        with self._lock:
            self.by_key.clear()


class RunStatus(str, Enum):
    """Run execution status."""

    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SCHEDULED = "SCHEDULED"


@dataclass
class Metric:
    """Metric data point."""

    key: str
    value: float
    timestamp: str
    step: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Run:
    """Experiment run."""

    run_id: str
    experiment_id: str
    name: str
    status: RunStatus
    created_at: str
    updated_at: str
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    duration_seconds: Optional[float] = None
    parameters: Dict[str, Any] = field(default_factory=dict)
    metrics: Dict[str, "MetricRollingWindow"] = field(default_factory=dict)
    artifacts: List[str] = field(default_factory=list)
    tags: Dict[str, str] = field(default_factory=dict)
    parent_run_id: Optional[str] = None
    notes: str = ""
    environment: str = ""
    metric_index: MetricIndex = field(default_factory=MetricIndex, init=False, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        d = {}
        for f in fields(self):
            if f.name == "metric_index":
                continue
            val = getattr(self, f.name)
            if hasattr(val, "to_dict"):
                d[f.name] = val.to_dict()
            elif isinstance(val, dict):
                d[f.name] = dict(val)
            elif isinstance(val, list):
                d[f.name] = list(val)
            else:
                d[f.name] = val
        d["status"] = self.status.value
        d["metrics"] = {
            key: [m.to_dict() for m in window.get_all()] for key, window in self.metrics.items()
        }
        return d

    @classmethod
    def _deserialize_metrics(cls, metrics_data: Dict[str, Any]) -> Dict[str, MetricRollingWindow]:
        """Deserialize metrics from dictionary format to MetricRollingWindow objects."""
        metrics_dict = {}
        for key, metrics_list in metrics_data.items():
            window = MetricRollingWindow()
            for m_dict in metrics_list:
                metric = Metric(**m_dict) if isinstance(m_dict, dict) else m_dict
                window.add(metric)
            metrics_dict[key] = window
        return metrics_dict

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Run":
        """Create from dictionary."""
        data = {k: v for k, v in data.items() if k != "metric_index"}
        data["status"] = RunStatus(data.get("status", "RUNNING"))
        if "metrics" in data:
            data["metrics"] = cls._deserialize_metrics(data["metrics"])
        run = cls(**data)

        for window in run.metrics.values():
            for metric in window.get_all():
                run.metric_index.index_metric(metric)
        return run


@dataclass
class Experiment:
    """Experiment container."""

    experiment_id: str
    name: str
    description: str
    created_at: str
    updated_at: str
    tags: Dict[str, str] = field(default_factory=dict)
    artifact_location: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Experiment":
        return cls(**data)


class ExperimentTracker:
    """
    Experiment Tracking system for logging metrics, parameters, and artifacts.
    """

    _instances: Set[weakref.ref] = set()
    _instances_lock = threading.Lock()
    _atexit_registered: bool = False

    def __init__(
        self,
        storage: StorageBackend,
        tracking_path: str = "experiment_tracking",
        metric_buffer_size: int = DEFAULT_METRIC_BUFFER_SIZE,
        auto_flush_metrics: bool = True,
        max_active_runs: int = DEFAULT_MAX_ACTIVE_RUNS,
        auto_cleanup_stale: bool = True,
        stale_run_age_seconds: float = DEFAULT_STALE_RUN_AGE_SECONDS,
        max_metrics_per_key: int = DEFAULT_MAX_METRICS_PER_KEY,
        max_metrics_per_run: int = DEFAULT_MAX_METRICS_PER_RUN,
    ):
        """
        Initialize Experiment Tracker.
        C3, C4: Metric buffering with persistence and limits.
        """
        self.storage = storage
        self.tracking_path = tracking_path
        self.metric_buffer_size = metric_buffer_size
        self.auto_flush_metrics = auto_flush_metrics
        self.max_active_runs = max_active_runs
        self.auto_cleanup_stale = auto_cleanup_stale
        self.stale_run_age_seconds = stale_run_age_seconds
        self.max_metrics_per_key = max_metrics_per_key
        self.max_metrics_per_run = max_metrics_per_run
        self._active_runs: OrderedDict[str, Run] = OrderedDict()
        self._metric_counts: Dict[str, int] = defaultdict(int)
        self._pending_metrics: Dict[str, deque] = {}
        self._runs_lock = threading.RLock()
        self._last_flushed_index: Dict[str, Dict[str, int]] = {}
        self._last_seen_evictions: Dict[str, Dict[str, int]] = {}
        self._total_runs_started = 0
        self._total_runs_completed = 0
        self._total_runs_failed = 0
        self._cleanup_count = 0
        self._total_metric_counts: Dict[str, int] = {}
        self._structure_ensured = False

        self._register_instance()

        logger.info(
            f"ExperimentTracker initialized at {tracking_path} (max_active_runs={max_active_runs})"
        )

    def _register_instance(self) -> None:
        """Register this instance for cleanup on exit."""
        with ExperimentTracker._instances_lock:
            ref = weakref.ref(self, ExperimentTracker._cleanup_ref)
            ExperimentTracker._instances.add(ref)
            if not ExperimentTracker._atexit_registered:
                atexit.register(ExperimentTracker._cleanup_all_instances)
                ExperimentTracker._atexit_registered = True

    @staticmethod
    def _cleanup_ref(ref: weakref.ref) -> None:
        """Callback when instance is garbage collected."""
        with ExperimentTracker._instances_lock:
            ExperimentTracker._instances.discard(ref)

    @staticmethod
    def _cleanup_all_instances() -> None:
        """Clean up all tracker instances on process exit."""
        with ExperimentTracker._instances_lock:
            for ref in ExperimentTracker._instances.copy():
                tracker = ref()
                if tracker is not None:
                    try:
                        tracker._cleanup_active_runs()
                    except Exception as e:
                        logger.warning(f"Error cleaning up tracker: {e}")

    def _cleanup_active_runs(self) -> None:
        """Clean up all active runs on shutdown."""
        with self._runs_lock:
            for run_id in tuple(self._active_runs.keys()):
                try:
                    self.end_run(run_id, RunStatus.FAILED)
                    logger.warning(f"Auto-closed orphaned run: {run_id}")
                except Exception as e:
                    logger.warning(f"Failed to close run {run_id}: {e}")

    def _ensure_tracking_structure(self) -> None:
        """
        Ensure tracking directory structure exists (lazy initialization).
        This is only called when actually creating an experiment or run.
        """
        if self._structure_ensured:
            return

        paths = [
            f"{self.tracking_path}/experiments",
            f"{self.tracking_path}/runs",
            f"{self.tracking_path}/artifacts",
            f"{self.tracking_path}/metrics",
        ]
        for path in paths:
            if not self.storage.exists(path):
                try:
                    self.storage.write_json(
                        {"created": datetime.now(timezone.utc).isoformat()},
                        f"{path}/.tracking_marker.json",
                        mode="overwrite",
                    )
                except Exception:
                    pass

        self._structure_ensured = True
        logger.debug(f"Tracking structure ensured at {self.tracking_path}")

    def create_experiment(
        self,
        name: str,
        description: str = "",
        tags: Optional[Dict[str, str]] = None,
    ) -> Experiment:
        """
        Create new experiment.
        """
        self._ensure_tracking_structure()

        name = validate_experiment_name(name)
        description = validate_description(description) or ""
        tags = validate_tags(tags)

        experiment_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()

        experiment = Experiment(
            experiment_id=experiment_id,
            name=name,
            description=description,
            created_at=now,
            updated_at=now,
            tags=tags or {},
            artifact_location=f"{self.tracking_path}/artifacts/{experiment_id}",
        )

        exp_path = f"{self.tracking_path}/experiments/{experiment_id}.json"
        self.storage.write_json(experiment.to_dict(), exp_path, mode="overwrite")

        self._update_experiments_index(experiment)

        logger.info(f"Created experiment {name} (ID: {experiment_id})")
        return experiment

    def start_run(
        self,
        experiment_id: str,
        name: str = "",
        parameters: Optional[Dict[str, Any]] = None,
        tags: Optional[Dict[str, str]] = None,
        parent_run_id: Optional[str] = None,
    ) -> Run:
        """
        Start new experiment run with memory protection.
        """
        # Ensure tracking structure exists before starting run
        self._ensure_tracking_structure()

        # Verify experiment exists
        self._get_experiment(experiment_id)

        # Validate inputs
        if name:
            name = validate_run_name(name)
        tags = validate_tags(tags)

        with self._runs_lock:
            # Check memory limits and cleanup if needed
            self._enforce_run_limits()

            run_id = str(uuid4())
            now = datetime.now(timezone.utc).isoformat()

            run = Run(
                run_id=run_id,
                experiment_id=experiment_id,
                name=name or f"run-{run_id[:8]}",
                status=RunStatus.RUNNING,
                created_at=now,
                updated_at=now,
                start_time=now,
                parameters=parameters or {},
                tags=tags or {},
                parent_run_id=parent_run_id,
                environment=tags.get("env_hash", "") if tags else "",
            )

            self._active_runs[run_id] = run
            self._total_runs_started += 1

        logger.info(f"Started run {run.name} (ID: {run_id})")
        return run

    def _enforce_run_limits(self) -> None:
        """Enforce maximum active runs limit with cleanup."""
        # First, try to clean up stale runs
        if self.auto_cleanup_stale and len(self._active_runs) >= self.max_active_runs:
            cleaned = self._cleanup_stale_runs_internal()
            if cleaned > 0:
                logger.info(f"Cleaned {cleaned} stale runs to make room")

        # If still at limit, fail with typed exception
        if len(self._active_runs) >= self.max_active_runs:
            raise RunLimitExceededError(
                current=len(self._active_runs),
                limit=self.max_active_runs,
            )

    def _cleanup_stale_runs_internal(self) -> int:
        """
        Internal stale run cleanup without lock (caller must hold lock).
        """
        now = datetime.now(timezone.utc)
        cleaned = 0

        stale_run_ids = [
            run_id
            for run_id, run in self._active_runs.items()
            if self._is_run_stale(run, now, self.stale_run_age_seconds)
        ]

        for run_id in stale_run_ids:
            try:
                # End run without lock (we already have it)
                self._end_run_internal(run_id, RunStatus.FAILED)
                cleaned += 1
                self._cleanup_count += 1
            except Exception as e:
                logger.warning(f"Failed to cleanup stale run {run_id}: {e}")

        return cleaned

    @staticmethod
    def _duration_seconds(start_time: str, end_time: str) -> float:
        """Compute duration in seconds from ISO timestamps."""
        start = datetime.fromisoformat(start_time)
        end = datetime.fromisoformat(end_time)
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        return (end - start).total_seconds()

    def _finalize_run_state(self, run: "Run", status: RunStatus) -> None:
        """Set status/timestamps/duration and flush metrics + final snapshot.

        Shared by ``end_run`` and ``_end_run_internal``, which differ only in
        what happens *after* this: ``end_run`` lets a persist failure raise
        (the run stays active so the caller can retry), while
        ``_end_run_internal`` logs and swallows it (used by cleanup loops that
        must not abort over one bad run). Neither `_flush_metrics` nor
        `_write_final_metrics_snapshot` raises — both are best-effort and
        handle their own errors internally — so this part is safe to share
        unconditionally.
        """
        now = datetime.now(timezone.utc).isoformat()
        run.status = status
        run.updated_at = now
        run.end_time = now

        if run.start_time:
            run.duration_seconds = self._duration_seconds(run.start_time, now)

        self._flush_metrics(run.run_id)
        self._write_final_metrics_snapshot(run)

    def _forget_run(self, run_id: str) -> None:
        """Drop a run's auxiliary per-run bookkeeping (metric flush cursors/
        counters). Called whenever a run leaves ``_active_runs``, whatever the
        reason (ended, cleaned up as stale, or explicitly deleted).
        """
        self._metric_counts.pop(run_id, None)
        self._total_metric_counts.pop(run_id, None)
        self._last_flushed_index.pop(run_id, None)
        self._last_seen_evictions.pop(run_id, None)

    def _record_run_outcome(self, status: RunStatus) -> None:
        if status == RunStatus.COMPLETED:
            self._total_runs_completed += 1
        else:
            self._total_runs_failed += 1

    def _end_run_internal(self, run_id: str, status: RunStatus) -> Optional[Run]:
        """End run without acquiring lock (for internal use)."""
        if run_id not in self._active_runs:
            return None

        run = self._active_runs[run_id]
        self._finalize_run_state(run, status)

        try:
            run_path = f"{self.tracking_path}/runs/{run.experiment_id}/{run_id}.json"
            self.storage.write_json(run.to_dict(), run_path, mode="overwrite")
            self._update_runs_index(run)
        except Exception as e:
            logger.error(f"Failed to persist run {run_id}: {e}")

        del self._active_runs[run_id]
        self._forget_run(run_id)
        self._record_run_outcome(status)

        return run

    def log_metric(
        self,
        run_id: str,
        key: str,
        value: float,
        step: int = 0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Log metric for run with memory protection and rolling window limits.
        """
        value = plain_number(value)
        # Validate metric value type
        if not isinstance(value, (int, float)):
            raise InvalidMetricError(
                key, value, f"Expected int or float, got {type(value).__name__}"
            )

        # Check for NaN or Inf
        if isinstance(value, float):
            if math.isnan(value):
                raise InvalidMetricError(key, value, "Value is NaN")
            if math.isinf(value):
                raise InvalidMetricError(key, value, "Value is infinite")

        with self._runs_lock:
            run = self._get_active_run(run_id)

            now = datetime.now(timezone.utc).isoformat()

            metric = Metric(
                key=key,
                value=value,
                timestamp=now,
                step=step,
                metadata=metadata or {},
            )

            # Both limit check and increment are inside self._runs_lock — do not split.
            current_count = self._total_metric_counts.get(run_id, 0)
            if current_count >= self.max_metrics_per_run:
                raise ResourceLimitError(
                    resource="metrics_per_run",
                    current=current_count,
                    limit=self.max_metrics_per_run,
                )

            # v2.1+: Use MetricRollingWindow for automatic eviction
            if key not in run.metrics:
                run.metrics[key] = MetricRollingWindow(max_size=self.max_metrics_per_key)
                # Sync MetricIndex capacity with this tracker's configuration on first key
                if run.metric_index.max_size != self.max_metrics_per_key:
                    run.metric_index.max_size = self.max_metrics_per_key

            # Add metric (auto-evicts oldest if window is full)
            run.metrics[key].add(metric)

            # v2.1+: Index metric for O(1) lookups
            run.metric_index.index_metric(metric)

            self._total_metric_counts[run_id] = current_count + 1
            total_metrics = self._total_metric_counts[run_id]

            # Warn if approaching total limit
            if total_metrics > self.max_metrics_per_run * 0.8:
                logger.warning(
                    f"Run {run_id}: High metric count ({total_metrics}/{self.max_metrics_per_run}). "
                    f"Consider logging less frequently or flushing metrics."
                )

            # Warn if key window is full (heavy logging)
            if run.metrics[key].get_stats()["is_full"]:
                logger.debug(
                    f"Run {run_id}: Metric key '{key}' rolling window full "
                    f"(evictions: {run.metrics[key]._evictions})"
                )

            logger.debug(f"Run {run_id}: Logged metric {key}={value} (step {step})")

            # Incremental persistence: flush if buffer is full
            self._metric_counts[run_id] += 1
            if self.auto_flush_metrics and self._metric_counts[run_id] >= self.metric_buffer_size:
                if self._flush_metrics(run_id):
                    self._metric_counts[run_id] = 0
                # else: leave the counter as-is so the next log_metric retries
                # the flush instead of silently believing it already happened.

    def log_parameter(
        self,
        run_id: str,
        key: str,
        value: Any,
    ) -> None:
        """
        Log hyperparameter for run.
        """
        with self._runs_lock:
            run = self._get_active_run(run_id)
            run.parameters[key] = value
        logger.debug(f"Run {run_id}: Logged parameter {key}={value}")

    def log_artifact(
        self,
        run_id: str,
        artifact_path: str,
        destination: str = "",
    ) -> str:
        """
        Log artifact for run.
        """
        # Verify artifact exists before logging
        from pathlib import Path

        artifact_file = Path(artifact_path)
        if not artifact_file.exists():
            raise ArtifactNotFoundError(artifact_path)

        with self._runs_lock:
            self._get_active_run(run_id)  # Verify run is active before writing
            if not destination:
                # one file per artifact: every artifact of a run used to share one path
                destination = f"artifacts/{run_id}/{artifact_file.name}"

        full_destination = f"{self.tracking_path}/{destination}"

        artifact_metadata = self.storage.write_artifact(
            artifact_path, full_destination, mode="overwrite"
        )

        with self._runs_lock:
            # Re-verify run is still active after storage write
            if run_id in self._active_runs:
                self._active_runs[run_id].artifacts.append(artifact_metadata.path)
            else:
                logger.warning(
                    f"Run {run_id} ended during artifact logging; artifact stored but not indexed"
                )
        logger.info(f"Run {run_id}: Logged artifact to {full_destination}")
        return artifact_metadata.path

    def set_tag(self, run_id: str, key: str, value: str) -> None:
        """Set tag on run."""
        with self._runs_lock:
            run = self._get_active_run(run_id)
            run.tags[key] = value
        logger.debug(f"Run {run_id}: Set tag {key}={value}")

    def end_run(self, run_id: str, status: RunStatus = RunStatus.COMPLETED) -> Run:
        """
        End run and persist to storage.
        """
        with self._runs_lock:
            run = self._get_active_run(run_id)
            self._finalize_run_state(run, status)

            # Persist run to storage. Unlike _end_run_internal, a failure here
            # is allowed to raise: the run stays in _active_runs so the caller
            # can retry end_run() instead of losing track of it silently.
            run_path = f"{self.tracking_path}/runs/{run.experiment_id}/{run_id}.json"
            self.storage.write_json(run.to_dict(), run_path, mode="overwrite")
            self._update_runs_index(run)

            del self._active_runs[run_id]
            self._forget_run(run_id)
            self._record_run_outcome(status)

            logger.info(f"Ended run {run.name} (ID: {run_id}) with status {status.value}")
            return run

    _TERMINAL_STATUSES = (RunStatus.COMPLETED, RunStatus.FAILED)

    def close_run(self, run_id: str, status: RunStatus, allow_override: bool = False) -> Run:
        """
        Force a run's status to a terminal value and persist it, without
        requiring the run to be active in this process's memory.
        """
        with self._runs_lock:
            if run_id in self._active_runs:
                return self.end_run(run_id, status=status)

            run = self.get_run(run_id)
            if run.status in self._TERMINAL_STATUSES and not allow_override:
                logger.warning(
                    f"close_run({run_id}) called on already-terminal run "
                    f"(status={run.status.value}); ignoring. Pass allow_override=True "
                    f"to force it."
                )
                return run

            now = datetime.now(timezone.utc).isoformat()
            run.status = status
            run.updated_at = now
            run.end_time = now
            if run.start_time:
                run.duration_seconds = self._duration_seconds(run.start_time, now)

            run_path = f"{self.tracking_path}/runs/{run.experiment_id}/{run_id}.json"
            self.storage.write_json(run.to_dict(), run_path, mode="overwrite")
            self._update_runs_index(run)

            logger.info(f"Closed stale run {run.name} (ID: {run_id}) with status {status.value}")
            return run

    def delete_run(self, run_id: str) -> None:
        """Delete a run's persisted record and remove it from the runs index."""
        run = self.get_run(run_id)

        run_path = f"{self.tracking_path}/runs/{run.experiment_id}/{run_id}.json"
        try:
            self.storage.delete(run_path)
        except Exception as e:
            logger.warning(f"Could not delete run file for {run_id}: {e}")

        lock_path = f"{self.tracking_path}/runs/.index.lock"
        base_path = getattr(self.storage, "base_path", None)
        with file_lock(lock_path, timeout=30.0, base_path=base_path):
            df = self._load_runs_index()
            if not df.empty:
                df = df[df["run_id"] != run_id]
                index_path = f"{self.tracking_path}/runs/index.parquet"
                self.storage.write_dataframe(df, index_path, mode="overwrite")
            self._drop_run_metrics(run)

        with self._runs_lock:
            self._active_runs.pop(run_id, None)
            self._forget_run(run_id)

        logger.info(f"Deleted run {run_id}")

    def _drop_run_metrics(self, run: Run) -> None:
        """Remove a deleted run from the metrics index and delete its metric files.

        ``search_runs`` with a metric filter reads the metrics index alone, so a row left
        there kept returning a run whose record was gone (``get_run`` then raised).
        """
        index_path = f"{self.tracking_path}/metrics/index.parquet"
        try:
            metrics_df = self.storage.read_dataframe(index_path)
            if "run_id" in metrics_df.columns:
                kept = metrics_df[metrics_df["run_id"] != run.run_id]
                if len(kept) != len(metrics_df):
                    self.storage.write_dataframe(kept, index_path, mode="overwrite")
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.warning(f"Could not drop run {run.run_id} from the metrics index: {e}")

        stem = f"{self.tracking_path}/metrics/{run.experiment_id}/{run.run_id}_metrics"
        for suffix in (".json", ".jsonl"):
            try:
                self.storage.delete(stem + suffix)
            except FileNotFoundError:
                pass
            except Exception as e:
                logger.warning(f"Could not delete {stem + suffix}: {e}")

    def get_run(self, run_id: str) -> Run:
        """
        Get run by ID.
        """
        with self._runs_lock:
            if run_id in self._active_runs:
                return Run.from_dict(self._active_runs[run_id].to_dict())

        # Search in storage
        runs_df = self._load_runs_index()
        run_rows = runs_df[runs_df["run_id"] == run_id]

        if run_rows.empty:
            raise RunNotFoundError(run_id)

        row = run_rows.iloc[0]
        run_path = f"{self.tracking_path}/runs/{row['experiment_id']}/{run_id}.json"
        data = self.storage.read_json(run_path)
        return Run.from_dict(data)

    def list_runs(
        self,
        experiment_id: str,
        status_filter: Optional[RunStatus] = None,
        tag_filter: Optional[Dict[str, str]] = None,
        with_metrics: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        List runs in experiment.

        ``with_metrics`` adds ``metrics``: each metric's latest point, as
        ``{key: [{"key", "value", "step", "timestamp"}]}``, so a caller can show
        final values without loading every run again.
        """
        runs_df = self._load_runs_index()
        runs = runs_df[runs_df["experiment_id"] == experiment_id]

        if runs.empty:
            return []

        if status_filter:
            runs = runs[runs["status"] == status_filter.value]

        result = []
        for _, row in runs.iterrows():
            try:
                run = self.get_run(row["run_id"])

                if tag_filter and not all(run.tags.get(k) == v for k, v in tag_filter.items()):
                    continue

                item: Dict[str, Any] = {
                    "run_id": run.run_id,
                    "name": run.name,
                    "status": run.status.value,
                    "created_at": run.created_at,
                    "duration_seconds": run.duration_seconds,
                    "parameters": run.parameters,
                    "metric_keys": list(run.metrics.keys()),
                    "tags": run.tags,
                }
                if with_metrics:
                    item["metrics"] = {}
                    for key in run.metrics:
                        latest = run.metric_index.get_latest(key)
                        if latest is not None:
                            item["metrics"][key] = [
                                {
                                    "key": key,
                                    "value": latest.value,
                                    "step": latest.step,
                                    "timestamp": latest.timestamp,
                                }
                            ]
                result.append(item)
            except Exception as e:
                logger.warning(f"Could not load run {row['run_id']}: {e}")
                continue

        return result

    def compare_runs(self, run_ids: List[str]) -> pd.DataFrame:
        """
        Compare multiple runs as DataFrame.
        """
        rows = []
        for run_id in run_ids:
            run = self.get_run(run_id)
            row = {
                "run_id": run.run_id,
                "name": run.name,
                "status": run.status.value,
                "duration_seconds": run.duration_seconds,
            }
            row.update({"param_" + k: v for k, v in run.parameters.items()})
            for k in run.metrics:
                if run.metrics[k]:
                    latest = run.metric_index.get_latest(k)
                    if latest is not None:
                        row[f"metric_{k}"] = latest.value
            rows.append(row)

        return pd.DataFrame(rows)

    def _compare(self, value: float, op: str, threshold: float) -> bool:
        try:
            return bool(_METRIC_OPS[op](value, threshold))
        except KeyError:
            raise ValueError(f"Unsupported operator: {op}")

    def _metric_ok(self, run: Run, metric_name: str, op: str, threshold: float) -> bool:
        latest = run.metric_index.get_latest(metric_name)
        if latest is None:
            return False
        return self._compare(latest.value, op, threshold)

    def search_runs(
        self,
        experiment_id: str,
        metric_filter: Optional[Dict[str, tuple]] = None,
    ) -> List[str]:
        """
        Search runs by metric thresholds using optimized metrics index.
        """
        if not metric_filter:
            runs = self.list_runs(experiment_id)
            return [r["run_id"] for r in runs]

        # Try to use metrics index for faster search
        try:
            return self._search_runs_optimized(experiment_id, metric_filter)
        except Exception as e:
            logger.debug(f"Falling back to full scan search: {e}")
            # Fallback to full scan
            return self._search_runs_full_scan(experiment_id, metric_filter)

    def _search_runs_optimized(
        self, experiment_id: str, metric_filter: Dict[str, tuple]
    ) -> List[str]:
        """Search using metrics index (fast path)."""
        metrics_index_path = f"{self.tracking_path}/metrics/index.parquet"
        metrics_df = self.storage.read_dataframe(metrics_index_path)

        # Filter by experiment
        metrics_df = metrics_df[metrics_df["experiment_id"] == experiment_id]

        # Apply metric filters
        for metric_name, (op, threshold) in metric_filter.items():
            col_name = f"metric_{metric_name}"
            if col_name not in metrics_df.columns:
                # Metric not in index, fallback to full scan
                raise ValueError(f"Metric {metric_name} not in index")

            if op not in _METRIC_OPS:
                raise ValueError(f"Unsupported operator: {op}")
            metrics_df = metrics_df[_METRIC_OPS[op](metrics_df[col_name], threshold)]

        return cast(List[str], metrics_df["run_id"].tolist())

    def _search_runs_full_scan(
        self, experiment_id: str, metric_filter: Dict[str, tuple]
    ) -> List[str]:
        """Search using full scan (fallback)."""
        runs = self.list_runs(experiment_id)
        matching_runs: List[str] = []

        for run_summary in runs:
            run_id = run_summary["run_id"]
            run = self.get_run(run_id)

            try:
                passed = True
                for metric_name, (op, threshold) in metric_filter.items():
                    if not self._metric_ok(run, metric_name, op, threshold):
                        passed = False
                        break
                if passed:
                    matching_runs.append(run_id)
            except ValueError:
                continue

        return matching_runs

    def download_artifact(
        self,
        run_id: str,
        artifact_path: str,
        local_destination: str,
    ) -> None:
        """
        Download artifact from run.
        Verifies that the artifact path belongs to this run before downloading.
        """
        expected_prefix = f"{self.tracking_path}/artifacts/{run_id}"
        if not artifact_path.startswith(expected_prefix):
            try:
                run = self.get_run(run_id)
                if artifact_path not in run.artifacts:
                    logger.warning(
                        f"Artifact '{artifact_path}' is not registered under run '{run_id}'. "
                        f"Proceeding with download but ownership could not be verified."
                    )
            except Exception:
                pass  # If run cannot be loaded, proceed with best-effort download

        self.storage.read_artifact(artifact_path, local_destination)
        logger.info(f"Downloaded artifact from run {run_id} to {local_destination}")

    def _flush_metrics(self, run_id: str) -> bool:
        """
        Flush metrics for a run to storage (incremental, append-only persistence).
        """
        if run_id not in self._active_runs:
            return False

        run = self._active_runs[run_id]

        try:
            last_flushed = self._last_flushed_index.setdefault(run_id, {})
            last_evictions = self._last_seen_evictions.setdefault(run_id, {})
            new_lines: List[str] = []

            for key, metrics in run.metrics.items():
                if isinstance(metrics, MetricRollingWindow):
                    all_metrics = metrics.get_all()
                    evictions_now = metrics.get_stats()["evictions"]
                else:
                    all_metrics = list(metrics)
                    evictions_now = 0

                start = last_flushed.get(key, 0)
                if evictions_now > last_evictions.get(key, 0):
                    logger.warning(
                        "Run {}: metric '{}' rolling window evicted entries "
                        "since the last flush; resending the full window for "
                        "this key to avoid missing points. Consider a larger "
                        "max_metrics_per_key or more frequent flushing "
                        "(smaller metric_buffer_size).",
                        run_id,
                        key,
                    )
                    start = 0

                for m in all_metrics[start:]:
                    new_lines.append(json.dumps({"key": key, **m.to_dict()}, default=str))
                last_flushed[key] = len(all_metrics)
                last_evictions[key] = evictions_now

            if not new_lines:
                return True

            deltas_path = f"{self.tracking_path}/metrics/{run.experiment_id}/{run_id}_metrics.jsonl"
            self.storage.append_lines(new_lines, deltas_path)
            logger.debug(f"Flushed {len(new_lines)} new metric point(s) for run {run_id}")
            return True
        except Exception as e:
            logger.warning(f"Could not flush metrics for run {run_id}: {e}")
            return False

    def _write_final_metrics_snapshot(self, run: "Run") -> None:
        """Write the complete, consolidated metrics snapshot once a run ends."""
        try:
            metrics_data = {
                key: [
                    m.to_dict()
                    for m in (
                        metrics.get_all() if isinstance(metrics, MetricRollingWindow) else metrics
                    )
                ]
                for key, metrics in run.metrics.items()
            }
            metrics_path = (
                f"{self.tracking_path}/metrics/{run.experiment_id}/{run.run_id}_metrics.json"
            )
            self.storage.write_json(metrics_data, metrics_path, mode="overwrite")
        except Exception as e:
            logger.warning(f"Could not write final metrics snapshot for run {run.run_id}: {e}")

    def _get_active_run(self, run_id: str) -> Run:
        """Get active run, raise if not found."""
        if run_id not in self._active_runs:
            raise RunNotActiveError(run_id)
        return self._active_runs[run_id]

    def get_experiment(self, experiment_id: str) -> Experiment:
        """The experiment *experiment_id*; ``ExperimentNotFoundError`` if there is none."""
        return self._get_experiment(experiment_id)

    def _get_experiment(self, experiment_id: str) -> Experiment:
        """Get experiment by ID."""
        try:
            exp_path = f"{self.tracking_path}/experiments/{experiment_id}.json"
            data = self.storage.read_json(exp_path)
            return Experiment.from_dict(data)
        except FileNotFoundError:
            raise ExperimentNotFoundError(experiment_id)

    def list_experiments(self) -> List[Dict[str, Any]]:
        """List all experiments from the index (most recent first)."""
        df = self._load_experiments_index()
        if df.empty:
            return []
        if "created_at" in df.columns:
            df = df.sort_values("created_at", ascending=False)
        return cast(List[Dict[str, Any]], df.to_dict(orient="records"))

    def _load_experiments_index(self) -> pd.DataFrame:
        """Load experiments index."""
        try:
            index_path = f"{self.tracking_path}/experiments/index.parquet"
            return self.storage.read_dataframe(index_path)
        except FileNotFoundError:
            return pd.DataFrame(columns=["experiment_id", "name", "created_at"])

    def _update_experiments_index(self, experiment: Experiment) -> None:
        """Update experiments index with file locking."""
        lock_path = f"{self.tracking_path}/experiments/.index.lock"
        base_path = getattr(self.storage, "base_path", None)

        with file_lock(lock_path, timeout=30.0, base_path=base_path):
            df = self._load_experiments_index()

            new_row = pd.DataFrame(
                [
                    {
                        "experiment_id": experiment.experiment_id,
                        "name": experiment.name,
                        "created_at": experiment.created_at,
                    }
                ]
            )

            df = pd.concat([df, new_row], ignore_index=True)
            df = df.drop_duplicates(subset=["experiment_id"], keep="last")

            index_path = f"{self.tracking_path}/experiments/index.parquet"
            self.storage.write_dataframe(df, index_path, mode="overwrite")

    def _load_runs_index(self) -> pd.DataFrame:
        """Load runs index."""
        try:
            index_path = f"{self.tracking_path}/runs/index.parquet"
            return self.storage.read_dataframe(index_path)
        except FileNotFoundError:
            return pd.DataFrame(columns=["run_id", "experiment_id", "status", "created_at"])

    def _update_runs_index(self, run: Run) -> None:
        """Update runs index with file locking and create metrics index."""
        lock_path = f"{self.tracking_path}/runs/.index.lock"
        base_path = getattr(self.storage, "base_path", None)

        with file_lock(lock_path, timeout=30.0, base_path=base_path):
            df = self._load_runs_index()

            new_row = pd.DataFrame(
                [
                    {
                        "run_id": run.run_id,
                        "experiment_id": run.experiment_id,
                        "status": run.status.value,
                        "created_at": run.created_at,
                    }
                ]
            )

            df = pd.concat([df, new_row], ignore_index=True)
            df = df.drop_duplicates(subset=["run_id"], keep="last")

            index_path = f"{self.tracking_path}/runs/index.parquet"
            self.storage.write_dataframe(df, index_path, mode="overwrite")

            # Create metrics index for faster search
            self._update_metrics_index(run)

    def _update_metrics_index(self, run: Run) -> None:
        """
        Update metrics index for faster search.
        """
        try:
            metrics_index_path = f"{self.tracking_path}/metrics/index.parquet"

            try:
                metrics_df = self.storage.read_dataframe(metrics_index_path)
            except FileNotFoundError:
                metrics_df = pd.DataFrame(columns=["run_id", "experiment_id"])

            metrics_df = metrics_df[metrics_df["run_id"] != run.run_id]

            row_data: Dict[str, Any] = {
                "run_id": run.run_id,
                "experiment_id": run.experiment_id,
            }

            for metric_name in run.metrics:
                latest = run.metric_index.get_latest(metric_name)
                if latest is not None:
                    row_data[f"metric_{metric_name}"] = latest.value

            new_row = pd.DataFrame([row_data])
            metrics_df = pd.concat([metrics_df, new_row], ignore_index=True)

            self.storage.write_dataframe(metrics_df, metrics_index_path, mode="overwrite")
            logger.debug(f"Updated metrics index for run {run.run_id}")

        except Exception as e:
            logger.warning(f"Could not update metrics index: {e}")

    def _is_run_stale(self, run, now: datetime, max_age_seconds: float) -> bool:
        """
        Determine if a run is stale; returns True when run should be cleaned up.
        """
        if not run.start_time:
            return False

        try:
            start_time = datetime.fromisoformat(run.start_time)
            if start_time.tzinfo is None:
                start_time = start_time.replace(tzinfo=timezone.utc)

            age_seconds = (now - start_time).total_seconds()
            if age_seconds > max_age_seconds:
                logger.warning(
                    f"Run {run.run_id if hasattr(run, 'run_id') else 'unknown'} "
                    f"({getattr(run, 'name', '')}) has been active for {age_seconds:.1f}s, marking as stale"
                )
                return True

            return False

        except (ValueError, TypeError) as e:
            logger.warning(
                f"Could not parse start_time for run {getattr(run, 'run_id', 'unknown')}: {e}. "
                f"Run will NOT be marked as stale to prevent accidental cleanup."
            )
            return False

    def cleanup_stale_runs(
        self,
        max_age_seconds: float = 3600.0,
        status: RunStatus = RunStatus.FAILED,
    ) -> int:
        """
        Clean up runs that have been active for too long without completion.
        """
        with self._runs_lock:
            now = datetime.now(timezone.utc)
            cleaned_count = 0

            stale_run_ids = [
                run_id
                for run_id, run in self._active_runs.items()
                if self._is_run_stale(run, now, max_age_seconds)
            ]

            for run_id in stale_run_ids:
                try:
                    self._end_run_internal(run_id, status)
                    cleaned_count += 1
                    self._cleanup_count += 1
                    logger.info(f"Cleaned up stale run {run_id}")
                except Exception as e:
                    logger.error(f"Failed to clean up stale run {run_id}: {e}")

            if cleaned_count > 0:
                logger.info(f"Cleaned up {cleaned_count} stale run(s)")

            return cleaned_count

    def get_latest_metric(
        self,
        run_id: str,
        key: str,
    ) -> Optional[Metric]:
        """
        Get latest metric for a key (O(1) lookup).
        """
        with self._runs_lock:
            run = self._get_active_run(run_id)
            return run.metric_index.get_latest(key)
