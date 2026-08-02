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

from collections import deque
from threading import Lock
from typing import Any, Deque, Dict, Optional

from loguru import logger  # type: ignore

try:
    from pyspark.sql.streaming import StreamingQueryListener  # type: ignore

    _LISTENER_AVAILABLE = True
except ImportError:  # PySpark not installed or too old to expose the listener API
    StreamingQueryListener = object  # type: ignore
    _LISTENER_AVAILABLE = False


def listener_available() -> bool:
    """Return True when the PySpark StreamingQueryListener API is importable."""
    return _LISTENER_AVAILABLE


class StreamingProgressSink:
    """Thread-safe store for per-query streaming progress (push model).

    Fed by :class:`DuctaProgressListener` from Spark's own
    ``onQueryProgress`` callbacks, so reading status costs no py4j RPC and no
    extra micro-batch work. Keyed by query *name* (Ducta sets a deterministic
    ``queryName`` per node) with the query id tracked for cross-reference.
    """

    def __init__(self, max_history: int = 50) -> None:
        self._lock = Lock()
        self._max_history = max(1, int(max_history))
        # query_name -> latest progress summary dict
        self._latest: Dict[str, Dict[str, Any]] = {}
        # query_name -> rolling window of triggerExecution durations (ms)
        self._trigger_ms: Dict[str, Deque[float]] = {}
        # query_id -> query_name
        self._id_to_name: Dict[str, str] = {}

    @staticmethod
    def _duration(progress: Any, key: str) -> Optional[float]:
        """Pull a numeric duration (ms) from a progress object's durationMs map."""
        try:
            duration_map = getattr(progress, "durationMs", None)
            if duration_map is None and isinstance(progress, dict):
                duration_map = progress.get("durationMs")
            if not duration_map:
                return None
            # durationMs may be a Java map proxy; .get works on both dict and proxy.
            value = duration_map.get(key)
            return float(value) if value is not None else None
        except Exception:
            return None

    @staticmethod
    def _attr(progress: Any, name: str) -> Any:
        if isinstance(progress, dict):
            return progress.get(name)
        return getattr(progress, name, None)

    def record(self, progress: Any) -> None:
        """Record a single StreamingQueryProgress event."""
        try:
            query_name = self._attr(progress, "name")
            if not query_name:
                # Unnamed queries can't be correlated to a node; skip quietly.
                return
            query_id = self._attr(progress, "id")
            trigger_ms = self._duration(progress, "triggerExecution")

            summary = {
                "batchId": self._attr(progress, "batchId"),
                "numInputRows": self._attr(progress, "numInputRows"),
                "inputRowsPerSecond": self._attr(progress, "inputRowsPerSecond"),
                "processedRowsPerSecond": self._attr(progress, "processedRowsPerSecond"),
                "triggerExecutionMs": trigger_ms,
                "addBatchMs": self._duration(progress, "addBatch"),
                "getBatchMs": self._duration(progress, "getBatch"),
                "queryPlanningMs": self._duration(progress, "queryPlanning"),
                "walCommitMs": self._duration(progress, "walCommit"),
            }

            with self._lock:
                self._latest[query_name] = summary
                if query_id is not None:
                    self._id_to_name[str(query_id)] = query_name
                if trigger_ms is not None:
                    window = self._trigger_ms.setdefault(
                        query_name, deque(maxlen=self._max_history)
                    )
                    window.append(trigger_ms)
        except Exception as e:  # never let a metrics callback break the stream
            logger.debug(f"StreamingProgressSink.record ignored an event: {e}")

    def get_latest(self, query_name: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            value = self._latest.get(query_name)
            return dict(value) if value is not None else None

    def avg_trigger_ms(self, query_name: str) -> Optional[float]:
        """Mean triggerExecution (ms) over the rolling window, or None if no data."""
        with self._lock:
            window = self._trigger_ms.get(query_name)
            if not window:
                return None
            return sum(window) / len(window)

    def snapshot_for_prefix(self, name_prefix: str) -> Dict[str, Dict[str, Any]]:
        """Return latest progress for every query whose name starts with *name_prefix*."""
        with self._lock:
            return {
                name: dict(value)
                for name, value in self._latest.items()
                if name.startswith(name_prefix)
            }

    def forget(self, query_name: str) -> None:
        with self._lock:
            self._latest.pop(query_name, None)
            self._trigger_ms.pop(query_name, None)
            stale_ids = [qid for qid, name in self._id_to_name.items() if name == query_name]
            for qid in stale_ids:
                self._id_to_name.pop(qid, None)


class DuctaProgressListener(StreamingQueryListener):  # type: ignore[misc]
    """Forwards Spark's streaming progress events into a :class:`StreamingProgressSink`.

    Registered once per SparkSession. All callbacks are wrapped so an error in
    the metrics path can never propagate back into the streaming engine.
    """

    def __init__(self, sink: StreamingProgressSink) -> None:
        self._sink = sink

    def onQueryStarted(self, event: Any) -> None:  # noqa: N802 (Spark API name)
        try:
            logger.debug(f"Streaming query started: {getattr(event, 'name', None)}")
        except Exception:
            pass

    def onQueryProgress(self, event: Any) -> None:  # noqa: N802 (Spark API name)
        progress = getattr(event, "progress", None)
        if progress is not None:
            self._sink.record(progress)

    def onQueryIdle(self, event: Any) -> None:  # noqa: N802 (Spark API name, 3.5+)
        # No-op: an idle query is not consuming CPU; nothing to record.
        pass

    def onQueryTerminated(self, event: Any) -> None:  # noqa: N802 (Spark API name)
        try:
            logger.debug(f"Streaming query terminated: {getattr(event, 'id', None)}")
        except Exception:
            pass
