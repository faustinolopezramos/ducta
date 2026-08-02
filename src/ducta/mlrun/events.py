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

import json
import threading
import time
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Union

from loguru import logger


class EventType(str, Enum):
    """MLOps event types."""

    # Experiment events
    EXPERIMENT_CREATED = "experiment.created"
    EXPERIMENT_DELETED = "experiment.deleted"

    # Run events
    RUN_STARTED = "run.started"
    RUN_ENDED = "run.ended"
    RUN_FAILED = "run.failed"
    RUN_CLEANED = "run.cleaned"

    # Metric events
    METRIC_LOGGED = "metric.logged"
    METRICS_FLUSHED = "metrics.flushed"
    METRIC_THRESHOLD_EXCEEDED = "metric.threshold_exceeded"

    # Parameter events
    PARAMETER_LOGGED = "parameter.logged"

    # Artifact events
    ARTIFACT_LOGGED = "artifact.logged"
    ARTIFACT_DOWNLOADED = "artifact.downloaded"

    # Model events
    MODEL_REGISTERED = "model.registered"
    MODEL_PROMOTED = "model.promoted"
    MODEL_DELETED = "model.deleted"
    MODEL_DOWNLOADED = "model.downloaded"

    # Storage events
    STORAGE_WRITE_STARTED = "storage.write.started"
    STORAGE_WRITE_COMPLETED = "storage.write.completed"
    STORAGE_READ_STARTED = "storage.read.started"
    STORAGE_READ_COMPLETED = "storage.read.completed"
    STORAGE_ERROR = "storage.error"

    # System events
    CONTEXT_INITIALIZED = "context.initialized"
    CONTEXT_CLEANUP = "context.cleanup"
    CLEANUP_STARTED = "cleanup.started"
    CLEANUP_COMPLETED = "cleanup.completed"

    # Circuit breaker events
    CIRCUIT_OPENED = "circuit.opened"
    CIRCUIT_CLOSED = "circuit.closed"
    CIRCUIT_HALF_OPEN = "circuit.half_open"

    # Lock events
    LOCK_ACQUIRED = "lock.acquired"
    LOCK_RELEASED = "lock.released"
    LOCK_TIMEOUT = "lock.timeout"
    LOCK_STALE_CLEANED = "lock.stale_cleaned"


@dataclass
class Event:
    """Represents an MLOps event."""

    event_type: EventType
    timestamp: str
    data: Dict[str, Any]
    source: str = "mlops"
    correlation_id: Optional[str] = None

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        """Convert event to dictionary."""
        return {
            "event_type": self.event_type.value,
            "timestamp": self.timestamp,
            "data": self.data,
            "source": self.source,
            "correlation_id": self.correlation_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Event":
        """Create event from dictionary."""
        return cls(
            event_type=EventType(data["event_type"]),
            timestamp=data.get("timestamp") or datetime.now(timezone.utc).isoformat(),
            data=data.get("data", {}),
            source=data.get("source", "mlops"),
            correlation_id=data.get("correlation_id"),
        )


class PersistentEventLog:
    """
    Prevents loss of events that would be discarded from in-memory deque.
    """

    def __init__(self, log_dir: str = "./mlops_logs", max_log_files: int = 10):
        """
        Initialize persistent event log.

        Args:
            log_dir: Directory to write log files.
            max_log_files: Maximum number of .jsonl files to retain after
                rotation. Set to 0 to disable pruning.
        """
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._max_log_files = max_log_files

        self._lock = threading.RLock()
        self._current_file: Optional[Path] = None
        self._file_handle: Optional[Any] = None
        self._events_written = 0
        self._max_file_size = 100 * 1024 * 1024  # 100MB per file

        logger.debug(f"PersistentEventLog initialized at {self.log_dir}")

    def write_event(self, event: Event) -> None:
        """
        Write event to persistent log file.
        """
        with self._lock:
            try:
                # Rotate file if too large
                self._maybe_rotate()

                # Ensure file is open
                if self._file_handle is None:
                    self._open_file()

                # Write event as JSONL (one JSON per line)
                event_dict = event.to_dict()
                line = json.dumps(event_dict) + "\n"
                self._file_handle.write(line)
                self._file_handle.flush()
                self._events_written += 1

            except Exception as e:
                logger.error(f"Failed to write event to persistent log: {e}")

    def _open_file(self) -> None:
        """Open a new log file, closing any existing handle first."""
        if self._file_handle is not None:
            try:
                self._file_handle.close()
            except Exception:
                pass
            self._file_handle = None
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self._current_file = self.log_dir / f"events_{timestamp}.jsonl"
        self._file_handle = open(self._current_file, "a", encoding="utf-8")
        logger.debug(f"Opened event log file: {self._current_file}")

    def _maybe_rotate(self) -> None:
        """Rotate to new file if current is too large, then prune old files."""
        if self._current_file and self._current_file.exists():
            size = self._current_file.stat().st_size
            if size >= self._max_file_size:
                if self._file_handle:
                    self._file_handle.close()
                self._file_handle = None
                logger.info(f"Rotating event log (size: {size / 1e6:.1f}MB)")
                self._prune_old_log_files()

    def _prune_old_log_files(self) -> None:
        """Delete oldest event log files when count exceeds _max_log_files.

        Must be called with self._lock held.
        """
        if self._max_log_files <= 0:
            return
        log_files = sorted(self.log_dir.glob("events_*.jsonl"))
        excess = len(log_files) - self._max_log_files
        if excess <= 0:
            return
        for old_file in log_files[:excess]:
            try:
                old_file.unlink()
                logger.info(f"Pruned old event log: {old_file}")
            except OSError as e:
                logger.warning(f"Failed to prune old event log {old_file}: {e}")

    def _parse_and_filter_line(
        self,
        line: str,
        event_type: Optional[EventType],
        start_time: Optional[str],
        end_time: Optional[str],
        log_file: Path,
    ) -> Optional[Event]:
        """Parse a single JSONL line and apply filters; return Event or None."""
        try:
            event_dict = json.loads(line)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse event from {log_file}: {e}")
            return None

        if not self._matches_filters(event_dict, event_type, start_time, end_time):
            return None

        try:
            return Event.from_dict(event_dict)
        except Exception as e:
            logger.warning(f"Failed to create Event from dict: {e}")
            return None

    def _matches_filters(
        self,
        event_dict: Dict[str, Any],
        event_type: Optional[EventType],
        start_time: Optional[str],
        end_time: Optional[str],
    ) -> bool:
        """Check if event matches all provided filters."""
        if event_type and event_dict.get("event_type") != event_type.value:
            return False
        if start_time and event_dict.get("timestamp", "") < start_time:
            return False
        if end_time and event_dict.get("timestamp", "") > end_time:
            return False
        return True

    def get_events(
        self,
        event_type: Optional[EventType] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: int = 1000,
    ) -> List[Event]:
        """
        Query events from log files.
        """
        events: List[Event] = []

        # Get all log files, sorted by name (timestamp)
        log_files = sorted(self.log_dir.glob("events_*.jsonl"), reverse=True)

        for log_file in log_files:
            try:
                with open(log_file, encoding="utf-8") as f:
                    for line in f:
                        if len(events) >= limit:
                            return events

                        event = self._parse_and_filter_line(
                            line, event_type, start_time, end_time, log_file
                        )
                        if event is not None:
                            events.append(event)

            except Exception as e:
                logger.error(f"Error reading event log {log_file}: {e}")
                continue

        return events

    def cleanup_old_files(self, days: int = 30) -> None:
        """
        Remove event log files older than specified days.

        Args:
            days: Age threshold in days
        """
        import time

        threshold = time.time() - (days * 24 * 3600)

        removed_count = 0
        for log_file in self.log_dir.glob("events_*.jsonl"):
            if log_file.stat().st_mtime < threshold:
                try:
                    log_file.unlink()
                    removed_count += 1
                except Exception as e:
                    logger.warning(f"Failed to remove old event log {log_file}: {e}")

        if removed_count > 0:
            logger.info(f"Cleaned up {removed_count} old event log files")

    def close(self) -> None:
        """Close the current log file."""
        with self._lock:
            if self._file_handle:
                self._file_handle.close()
                self._file_handle = None
            logger.debug(f"Closed event log (wrote {self._events_written} events)")


EventCallback = Callable[[Event], None]


class EventEmitter:
    """
    Thread-safe event emitter for MLOps components.
    """

    def __init__(
        self,
        name: str = "default",
        max_history: int = 1000,
        max_workers: int = 4,
        log_dir: Optional[str] = None,
    ):
        self.name = name
        self._listeners: Dict[EventType, Set[EventCallback]] = defaultdict(set)
        self._async_listeners: Dict[EventType, Set[EventCallback]] = defaultdict(set)
        self._wildcard_listeners: Set[EventCallback] = set()
        self._async_wildcard_listeners: Set[EventCallback] = set()
        self._lock = threading.RLock()
        # Use deque with maxlen to auto-remove old events (prevents memory leak)
        self._event_history: deque = deque(maxlen=max_history)
        self._enabled = True
        # Thread pool for async callbacks
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="event-")
        # Optional persistent event log for audit trail
        self._persistent_log: Optional[PersistentEventLog] = None
        if log_dir:
            self._persistent_log = PersistentEventLog(log_dir=log_dir)
        logger.debug(
            f"EventEmitter '{name}' initialized with max_history={max_history}, persistent_log={bool(self._persistent_log)}"
        )

    @staticmethod
    def _normalize_event_type(event_type: Union[EventType, str]) -> Union[EventType, str]:
        """Convert string to EventType, leaving '*' unchanged."""
        if event_type != "*" and isinstance(event_type, str):
            return EventType(event_type)
        return event_type

    def on(
        self,
        event_type: Union[EventType, str],
        callback: EventCallback,
    ) -> None:
        """
        Register an event listener.
        """
        with self._lock:
            event_type = self._normalize_event_type(event_type)
            if event_type == "*":
                self._wildcard_listeners.add(callback)
            else:
                self._listeners[event_type].add(callback)

    def off(
        self,
        event_type: Union[EventType, str],
        callback: EventCallback,
    ) -> None:
        """
        Remove an event listener.
        """
        with self._lock:
            event_type = self._normalize_event_type(event_type)
            if event_type == "*":
                self._wildcard_listeners.discard(callback)
            else:
                self._listeners[event_type].discard(callback)

    def emit(
        self,
        event_type: EventType,
        data: Dict[str, Any],
        source: str = "mlops",
        correlation_id: Optional[str] = None,
    ) -> Event:
        """
        Emit an event to all registered listeners.
        Sync callbacks run inline, async callbacks run in thread pool.
        """
        if not self._enabled:
            return Event(event_type=event_type, timestamp="", data=data)

        event = Event(
            event_type=event_type,
            timestamp=datetime.now(timezone.utc).isoformat(),
            data=data,
            source=source,
            correlation_id=correlation_id,
        )

        with self._lock:
            # Store in history (deque auto-removes old entries)
            self._event_history.append(event)

            # Get listeners (copy to avoid modification during iteration)
            sync_listeners = list(self._listeners.get(event_type, set()))
            async_listeners = list(self._async_listeners.get(event_type, set()))
            sync_wildcard = list(self._wildcard_listeners)
            async_wildcard = list(self._async_wildcard_listeners)

        # Persist to disk OUTSIDE lock to avoid blocking concurrent emitters on I/O
        if self._persistent_log:
            try:
                self._persistent_log.write_event(event)
            except Exception as e:
                logger.warning(f"Failed to write persistent event log: {e}")

        # Call sync listeners outside lock (blocking)
        for callback in sync_listeners + sync_wildcard:
            try:
                callback(event)
            except Exception as e:
                logger.warning(f"Sync event listener error for {event_type.value}: {e}")

        # Submit async listeners to thread pool (non-blocking)
        for callback in async_listeners + async_wildcard:
            self._executor.submit(self._run_async_callback, callback, event)

        return event

    def enable(self) -> None:
        """Enable event emission."""
        self._enabled = True

    def disable(self) -> None:
        """Disable event emission (for performance)."""
        self._enabled = False

    def _run_async_callback(self, callback: EventCallback, event: Event) -> None:
        """
        Run callback in thread pool. Errors are logged but don't propagate.
        """
        try:
            callback(event)
        except Exception as e:
            logger.warning(f"Async event listener error for {event.event_type.value}: {e}")

    def subscribe_async(
        self,
        event_type: Union[EventType, str],
        callback: EventCallback,
    ) -> None:
        """
        Register an async event listener (runs in thread pool).
        """
        with self._lock:
            event_type = self._normalize_event_type(event_type)
            if event_type == "*":
                self._async_wildcard_listeners.add(callback)
            else:
                self._async_listeners[event_type].add(callback)

    def unsubscribe_async(
        self,
        event_type: Union[EventType, str],
        callback: EventCallback,
    ) -> None:
        """
        Remove an async event listener.
        """
        with self._lock:
            event_type = self._normalize_event_type(event_type)
            if event_type == "*":
                self._async_wildcard_listeners.discard(callback)
            else:
                self._async_listeners[event_type].discard(callback)

    def get_history(
        self,
        event_type: Optional[EventType] = None,
        limit: int = 100,
    ) -> List[Event]:
        """
        Get recent event history (deque-backed, auto-limited).
        """
        with self._lock:
            if event_type is None:
                return list(self._event_history)[-limit:]
            return [e for e in self._event_history if e.event_type == event_type][-limit:]

    def clear_history(self) -> None:
        """Clear event history."""
        with self._lock:
            self._event_history.clear()

    def close(self) -> None:
        """Close event emitter and cleanup resources (persistent log, thread pool)."""
        with self._lock:
            if self._persistent_log:
                self._persistent_log.close()
                self._persistent_log = None
            self._executor.shutdown(wait=True)
            logger.debug(f"EventEmitter '{self.name}' closed")

    def __del__(self) -> None:
        """Ensure cleanup on garbage collection."""
        try:
            if hasattr(self, "_persistent_log") and self._persistent_log:
                self._persistent_log.close()
            if hasattr(self, "_executor"):
                self._executor.shutdown(wait=False)
        except Exception:  # noqa: BLE001  (broad catch intentional in __del__: RuntimeError/TypeError/AttributeError can be raised during interpreter shutdown)
            pass

    def listener_count(self, event_type: Optional[EventType] = None) -> int:
        """Get count of registered listeners."""
        with self._lock:
            if event_type is None:
                total = sum(len(ls) for ls in self._listeners.values())
                return total + len(self._wildcard_listeners)
            return len(self._listeners.get(event_type, set()))


@dataclass
class MetricAggregation:
    """Aggregated metric statistics."""

    name: str
    count: int
    total: float
    min_value: float
    max_value: float
    last_value: float
    last_timestamp: str

    @property
    def mean(self) -> float:
        """Calculate mean value."""
        return self.total / self.count if self.count > 0 else 0.0


class MetricsCollector:
    """
    Collects and aggregates operational metrics for MLOps.
    """

    def __init__(self):
        self._counters: Dict[str, int] = defaultdict(int)
        self._gauges: Dict[str, float] = {}
        self._timers: Dict[str, List[float]] = defaultdict(list)
        self._aggregations: Dict[str, MetricAggregation] = {}
        self._lock = threading.RLock()
        self._max_timer_samples = 1000

    def increment(
        self,
        name: str,
        value: int = 1,
        tags: Optional[Dict[str, str]] = None,
    ) -> int:
        """
        Increment a counter metric.
        """
        key = self._make_key(name, tags)
        with self._lock:
            self._counters[key] += value
            return self._counters[key]

    def decrement(
        self,
        name: str,
        value: int = 1,
        tags: Optional[Dict[str, str]] = None,
    ) -> int:
        """
        Decrement a counter metric.
        """
        key = self._make_key(name, tags)
        with self._lock:
            self._counters[key] = max(0, self._counters[key] - value)
            return self._counters[key]

    def gauge(
        self,
        name: str,
        value: float,
        tags: Optional[Dict[str, str]] = None,
    ) -> None:
        """
        Set a gauge metric (point-in-time value).
        """
        key = self._make_key(name, tags)
        with self._lock:
            self._gauges[key] = value
            self._update_aggregation(key, value)

    def timer(self, name: str, tags: Optional[Dict[str, str]] = None):
        """
        Context manager for timing operations.
        """
        return _TimerContext(self, name, tags)

    def record_time(
        self,
        name: str,
        duration: float,
        tags: Optional[Dict[str, str]] = None,
    ) -> None:
        """
        Record a duration measurement.
        """
        key = self._make_key(name, tags)
        with self._lock:
            self._timers[key].append(duration)
            if len(self._timers[key]) > self._max_timer_samples:
                self._timers[key] = self._timers[key][-self._max_timer_samples :]
            self._update_aggregation(key, duration)

    def _make_key(self, name: str, tags: Optional[Dict[str, str]]) -> str:
        """Create a metric key from name and tags."""
        if not tags:
            return name
        tag_str = ",".join(f"{k}={v}" for k, v in sorted(tags.items()))
        return f"{name}[{tag_str}]"

    def _update_aggregation(self, key: str, value: float) -> None:
        """Update running aggregation for a metric."""
        now = datetime.now(timezone.utc).isoformat()

        if key not in self._aggregations:
            self._aggregations[key] = MetricAggregation(
                name=key,
                count=1,
                total=value,
                min_value=value,
                max_value=value,
                last_value=value,
                last_timestamp=now,
            )
        else:
            agg = self._aggregations[key]
            agg.count += 1
            agg.total += value
            agg.min_value = min(agg.min_value, value)
            agg.max_value = max(agg.max_value, value)
            agg.last_value = value
            agg.last_timestamp = now

    def get_counter(self, name: str, tags: Optional[Dict[str, str]] = None) -> int:
        """Get current counter value."""
        key = self._make_key(name, tags)
        with self._lock:
            return self._counters.get(key, 0)

    def get_gauge(self, name: str, tags: Optional[Dict[str, str]] = None) -> Optional[float]:
        """Get current gauge value."""
        key = self._make_key(name, tags)
        with self._lock:
            return self._gauges.get(key)

    def get_timer_stats(
        self,
        name: str,
        tags: Optional[Dict[str, str]] = None,
    ) -> Dict[str, float]:
        """
        Get statistics for a timer.
        """
        key = self._make_key(name, tags)
        with self._lock:
            samples = self._timers.get(key, [])
            if not samples:
                return {}

            sorted_samples = sorted(samples)
            count = len(sorted_samples)

            return {
                "count": count,
                "min": min(sorted_samples),
                "max": max(sorted_samples),
                "mean": sum(sorted_samples) / count,
                "p50": sorted_samples[int(count * 0.5)],
                "p95": sorted_samples[int(count * 0.95)] if count >= 20 else sorted_samples[-1],
                "p99": sorted_samples[int(count * 0.99)] if count >= 100 else sorted_samples[-1],
            }

    def get_summary(self) -> Dict[str, Any]:
        """
        Get a summary of all collected metrics.
        """
        with self._lock:
            summary = {
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "timers": {},
                "aggregations": {},
            }

            for key in self._timers:
                samples = self._timers[key]
                if samples:
                    summary["timers"][key] = {
                        "count": len(samples),
                        "mean": sum(samples) / len(samples),
                        "min": min(samples),
                        "max": max(samples),
                    }

            for key, agg in self._aggregations.items():
                summary["aggregations"][key] = {
                    "count": agg.count,
                    "mean": agg.mean,
                    "min": agg.min_value,
                    "max": agg.max_value,
                    "last": agg.last_value,
                }

            return summary

    def reset(self) -> None:
        """Reset all metrics."""
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._timers.clear()
            self._aggregations.clear()


class _TimerContext:
    """Context manager for timing operations."""

    def __init__(
        self,
        collector: MetricsCollector,
        name: str,
        tags: Optional[Dict[str, str]],
    ):
        self._collector = collector
        self._name = name
        self._tags = tags
        self._start_time: Optional[float] = None

    def __enter__(self):
        self._start_time = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._start_time is not None:
            duration = time.perf_counter() - self._start_time
            self._collector.record_time(self._name, duration, self._tags)
        return False


# Global event emitter
_global_emitter: Optional[EventEmitter] = None
_emitter_lock = threading.Lock()


def get_event_emitter() -> EventEmitter:
    """Get the global event emitter instance."""
    global _global_emitter
    with _emitter_lock:
        if _global_emitter is None:
            _global_emitter = EventEmitter("global")
        return _global_emitter


def emit_event(
    event_type: EventType,
    data: Dict[str, Any],
    source: str = "mlops",
) -> Event:
    """
    Emit an event using the global emitter.
    """
    return get_event_emitter().emit(event_type, data, source)


# Global metrics collector
_global_metrics: Optional[MetricsCollector] = None
_metrics_lock = threading.Lock()


def get_metrics_collector() -> MetricsCollector:
    """Get the global metrics collector instance."""
    global _global_metrics
    with _metrics_lock:
        if _global_metrics is None:
            _global_metrics = MetricsCollector()
        return _global_metrics


class HookType(str, Enum):
    """Types of hooks for MLOps operations."""

    # Pre-operation hooks
    PRE_RUN_START = "pre.run.start"
    PRE_RUN_END = "pre.run.end"
    PRE_METRIC_LOG = "pre.metric.log"
    PRE_MODEL_REGISTER = "pre.model.register"
    PRE_MODEL_PROMOTE = "pre.model.promote"
    PRE_STORAGE_WRITE = "pre.storage.write"
    PRE_STORAGE_READ = "pre.storage.read"

    # Post-operation hooks
    POST_RUN_START = "post.run.start"
    POST_RUN_END = "post.run.end"
    POST_METRIC_LOG = "post.metric.log"
    POST_MODEL_REGISTER = "post.model.register"
    POST_MODEL_PROMOTE = "post.model.promote"
    POST_STORAGE_WRITE = "post.storage.write"
    POST_STORAGE_READ = "post.storage.read"

    # Error hooks
    ON_ERROR = "on.error"
    ON_RETRY = "on.retry"


HookCallback = Callable[[HookType, Dict[str, Any]], Optional[Dict[str, Any]]]


class HooksManager:
    """
    Manages hooks for extending MLOps operations.
    """

    def __init__(self):
        self._hooks: Dict[HookType, List[tuple[HookCallback, int]]] = defaultdict(list)
        self._lock = threading.RLock()

    def register(
        self,
        hook_type: HookType,
        callback: Optional[HookCallback] = None,
        priority: int = 0,
    ):
        """
        Register a hook callback.
        """

        def decorator(func: HookCallback) -> HookCallback:
            with self._lock:
                # Insert at position based on priority
                hooks = self._hooks[hook_type]
                # Find insertion point (higher priority first)
                insert_idx = len(hooks)
                for i, (_, p) in enumerate(hooks):
                    if priority > p:
                        insert_idx = i
                        break
                hooks.insert(insert_idx, (func, priority))
            return func

        if callback is not None:
            return decorator(callback)
        return decorator

    def unregister(
        self,
        hook_type: HookType,
        callback: HookCallback,
    ) -> bool:
        """
        Unregister a hook callback.
        """
        with self._lock:
            hooks = self._hooks[hook_type]
            for i, (cb, _) in enumerate(hooks):
                if cb == callback:
                    hooks.pop(i)
                    return True
            return False

    def execute(
        self,
        hook_type: HookType,
        data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Execute all hooks for a given type.
        """
        with self._lock:
            hooks = list(self._hooks.get(hook_type, []))

        result = data
        for callback, _ in hooks:
            try:
                hook_result = callback(hook_type, result)
                if hook_result is not None:
                    result = hook_result
            except Exception as e:
                logger.error(f"Hook {hook_type.value} failed: {e}")
                # For ON_ERROR hooks, don't re-raise
                if hook_type != HookType.ON_ERROR:
                    raise

        return result

    def clear(self, hook_type: Optional[HookType] = None) -> None:
        """
        Clear registered hooks.
        """
        with self._lock:
            if hook_type is None:
                self._hooks.clear()
            else:
                self._hooks[hook_type].clear()


# Global hooks manager
_global_hooks: Optional[HooksManager] = None
_hooks_lock = threading.Lock()


def get_hooks_manager() -> HooksManager:
    """Get the global hooks manager instance."""
    global _global_hooks
    with _hooks_lock:
        if _global_hooks is None:
            _global_hooks = HooksManager()
        return _global_hooks


@dataclass
class AuditEntry:
    """An audit log entry."""

    timestamp: str
    operation: str
    user: Optional[str]
    resource_type: str
    resource_id: str
    action: str
    status: str
    details: Dict[str, Any]
    duration_ms: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "timestamp": self.timestamp,
            "operation": self.operation,
            "user": self.user,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "action": self.action,
            "status": self.status,
            "details": self.details,
            "duration_ms": self.duration_ms,
        }


class AuditLogger:
    """
    Audit logger for tracking MLOps operations.
    """

    def __init__(
        self,
        max_entries: int = 10000,
        persist_callback: Optional[Callable[[AuditEntry], None]] = None,
    ):
        self._entries: List[AuditEntry] = []
        self._max_entries = max_entries
        self._persist_callback = persist_callback
        self._lock = threading.RLock()

    def log(
        self,
        operation: str,
        resource_type: str,
        resource_id: str,
        action: str,
        status: str,
        details: Optional[Dict[str, Any]] = None,
        user: Optional[str] = None,
        duration_ms: Optional[float] = None,
    ) -> AuditEntry:
        """
        Log an audit entry.
        """
        entry = AuditEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            operation=operation,
            user=user,
            resource_type=resource_type,
            resource_id=resource_id,
            action=action,
            status=status,
            details=details or {},
            duration_ms=duration_ms,
        )

        with self._lock:
            self._entries.append(entry)
            if len(self._entries) > self._max_entries:
                self._entries = self._entries[-self._max_entries :]

        # Persist if callback provided
        if self._persist_callback:
            try:
                self._persist_callback(entry)
            except Exception as e:
                logger.warning(f"Failed to persist audit entry: {e}")

        return entry

    def _matches_query(
        self,
        entry: AuditEntry,
        operation: Optional[str],
        resource_type: Optional[str],
        resource_id: Optional[str],
        status: Optional[str],
        since: Optional[str],
    ) -> bool:
        """Check if an entry matches the query criteria."""
        if operation and entry.operation != operation:
            return False
        if resource_type and entry.resource_type != resource_type:
            return False
        if resource_id and entry.resource_id != resource_id:
            return False
        if status and entry.status != status:
            return False
        if since and entry.timestamp < since:
            return False
        return True

    def query(
        self,
        operation: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        status: Optional[str] = None,
        since: Optional[str] = None,
        limit: int = 100,
    ) -> List[AuditEntry]:
        """
        Query audit entries.
        """
        with self._lock:
            results = []

            for entry in reversed(self._entries):
                if len(results) >= limit:
                    break

                if self._matches_query(entry, operation, resource_type, resource_id, status, since):
                    results.append(entry)

            return results

    def get_summary(self) -> Dict[str, Any]:
        """Get audit log summary statistics."""
        with self._lock:
            operations: Dict[str, int] = defaultdict(int)
            statuses: Dict[str, int] = defaultdict(int)
            resource_types: Dict[str, int] = defaultdict(int)

            for entry in self._entries:
                operations[entry.operation] += 1
                statuses[entry.status] += 1
                resource_types[entry.resource_type] += 1

            return {
                "total_entries": len(self._entries),
                "operations": dict(operations),
                "statuses": dict(statuses),
                "resource_types": dict(resource_types),
            }

    def clear(self) -> int:
        """Clear all audit entries. Returns count of cleared entries."""
        with self._lock:
            count = len(self._entries)
            self._entries.clear()
            return count


# Global audit logger
_global_audit: Optional[AuditLogger] = None
_audit_lock = threading.Lock()


def get_audit_logger() -> AuditLogger:
    """Get the global audit logger instance."""
    global _global_audit
    with _audit_lock:
        if _global_audit is None:
            _global_audit = AuditLogger()
        return _global_audit
