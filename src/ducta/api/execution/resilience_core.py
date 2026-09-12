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

Resilience & Fault-Tolerance for Pipeline Executions.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ducta.api.execution._registry import KeyedRegistry


@dataclass
class ExecutionFailure:
    timestamp: datetime
    exception: Exception
    node_id: Optional[str] = None
    context: Optional[str] = None


class ResilienceMetrics:
    def __init__(self, execution_id: str):
        self.execution_id = execution_id
        self.start_time = datetime.now(tz=timezone.utc)
        self.retries_attempted = 0
        self.retries_successful = 0
        self.failures: List[ExecutionFailure] = []
        self._lock = threading.Lock()

    def record_retry_attempt(self) -> None:
        with self._lock:
            self.retries_attempted += 1

    def record_retry_success(self) -> None:
        with self._lock:
            self.retries_successful += 1

    def record_failure(
        self, exception: Exception, node_id: Optional[str] = None, context: Optional[str] = None
    ) -> None:
        with self._lock:
            self.failures.append(
                ExecutionFailure(
                    timestamp=datetime.now(tz=timezone.utc),
                    exception=exception,
                    node_id=node_id,
                    context=context,
                )
            )

    def elapsed_seconds(self) -> float:
        return (datetime.now(tz=timezone.utc) - self.start_time).total_seconds()

    def to_dict(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "execution_id": self.execution_id,
                "elapsed_seconds": self.elapsed_seconds(),
                "retries_attempted": self.retries_attempted,
                "retries_successful": self.retries_successful,
                "failure_count": len(self.failures),
            }


class ResilienceContext:
    def __init__(self, execution_id: str):
        self.execution_id = execution_id
        self.metrics = ResilienceMetrics(execution_id)

    def record_node_failure(
        self, node_id: str, exception: Exception, context: Optional[str] = None
    ) -> None:
        self.metrics.record_failure(exception, node_id=node_id, context=context)


_resilience_contexts: KeyedRegistry[str, ResilienceContext] = KeyedRegistry(ResilienceContext)


def get_resilience_context(execution_id: str) -> ResilienceContext:
    return _resilience_contexts.get_or_create(execution_id)


def delete_resilience_context(execution_id: str) -> bool:
    return _resilience_contexts.delete(execution_id)
