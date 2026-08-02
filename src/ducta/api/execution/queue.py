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

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from queue import Empty, PriorityQueue
from typing import Optional

from loguru import logger


class ExecutionPriority(str, Enum):
    """Priority levels for pipeline execution."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"

    @classmethod
    def from_env(cls, env_name: str) -> "ExecutionPriority":
        """Determine priority based on environment name.

        Args:
            env_name: Environment name (e.g., 'prod', 'staging', 'dev')

        Returns:
            ExecutionPriority level for the given environment
        """
        env_lower = env_name.lower().strip()

        # Production environments → HIGH priority
        if env_lower in ("production", "prod"):
            return cls.HIGH

        # Staging environments → NORMAL priority
        if env_lower in ("staging", "stage"):
            return cls.NORMAL

        # Development environments → LOW priority
        if env_lower in ("development", "dev", "local", "localhost"):
            return cls.LOW

        # Default → NORMAL priority for unknown environments
        return cls.NORMAL


@dataclass(order=True)
class QueuedExecution:
    """Queued execution with priority-based ordering."""

    # Primary sort: priority (higher first)
    priority: int = field(compare=True)
    # Secondary sort: creation time (older first, FIFO within same priority)
    created_at: float = field(compare=True)

    execution_id: str = field(compare=False)
    pipeline_name: str = field(compare=False)
    created_at_dt: datetime = field(
        compare=False, default_factory=lambda: datetime.now(tz=timezone.utc)
    )

    def __post_init__(self) -> None:
        """Auto-populate created_at if not set."""
        if self.created_at == 0:
            self.created_at = datetime.now(tz=timezone.utc).timestamp()

    @staticmethod
    def from_execution(
        execution_id: str,
        pipeline_name: str,
        priority: ExecutionPriority = ExecutionPriority.NORMAL,
    ) -> QueuedExecution:
        """Create a queued execution with proper priority ordering."""
        priority_values = {
            ExecutionPriority.LOW: 1,
            ExecutionPriority.NORMAL: 2,
            ExecutionPriority.HIGH: 3,
        }
        now = datetime.now(tz=timezone.utc)
        return QueuedExecution(
            # Negate so higher-priority jobs (HIGH=3) sort first in the min-heap
            priority=-priority_values.get(priority, 2),
            created_at=now.timestamp(),
            execution_id=execution_id,
            pipeline_name=pipeline_name,
            created_at_dt=now,
        )


class ExecutionQueue:
    """
    Priority queue for pipeline executions.

    Limits concurrency to prevent resource exhaustion. Uses a heap for
    efficient priority-based scheduling with FIFO ordering within same priority.
    """

    def __init__(self, max_concurrent: int = 5):
        """Initialize queue with concurrency limit.

        Args:
            max_concurrent: Maximum number of concurrent executions. Default: 5
        """
        self.max_concurrent = max_concurrent
        self._queue: PriorityQueue[QueuedExecution] = PriorityQueue()
        self._active: set[str] = set()
        self._waiting: dict[str, QueuedExecution] = {}
        # IDs cancelled while still in the heap; drained lazily in dequeue()
        self._cancelled_ids: set[str] = set()
        self._stats = {
            "total_queued": 0,
            "total_completed": 0,
            "total_cancelled": 0,
        }
        self._has_work: asyncio.Event = asyncio.Event()

    def enqueue(
        self,
        execution_id: str,
        pipeline_name: str,
        priority: ExecutionPriority = ExecutionPriority.NORMAL,
    ) -> None:
        """Add execution to queue. Returns immediately (does NOT await)."""
        queued = QueuedExecution.from_execution(execution_id, pipeline_name, priority)
        self._waiting[execution_id] = queued
        self._queue.put(queued)
        self._stats["total_queued"] += 1

        logger.info(
            "Queued execution {id} ({name}, priority={pri}, position={pos})",
            id=execution_id,
            name=pipeline_name,
            pri=priority.value,
            pos=self._queue.qsize(),
        )
        self._has_work.set()

    async def dequeue(self) -> Optional[QueuedExecution]:
        """
        Wait for an execution slot to become available and return the next queued item.

        Blocks until:
        1. There is capacity (len(active) < max_concurrent), AND
        2. There is an item in the queue

        Returns None if queue is empty after timeout.
        """
        while True:
            # Check if we have capacity
            if len(self._active) < self.max_concurrent and not self._queue.empty():
                try:
                    queued = self._queue.get_nowait()
                    # Skip items that were cancelled while waiting in the heap
                    if queued.execution_id in self._cancelled_ids:
                        self._cancelled_ids.discard(queued.execution_id)
                        self._waiting.pop(queued.execution_id, None)
                        logger.debug(
                            "Skipped cancelled execution {id} from queue",
                            id=queued.execution_id,
                        )
                        continue  # check queue again immediately, no sleep
                    self._active.add(queued.execution_id)
                    self._waiting.pop(queued.execution_id, None)

                    logger.info(
                        "Dequeued execution {id} ({name}), active: {active}/{max}",
                        id=queued.execution_id,
                        name=queued.pipeline_name,
                        active=len(self._active),
                        max=self.max_concurrent,
                    )
                    return queued
                except Exception:
                    pass

            # No capacity or items — wait for notification without polling.
            # Clear BEFORE re-checking so notifications arriving between the
            # check above and this clear() are not lost.
            self._has_work.clear()
            if len(self._active) < self.max_concurrent and not self._queue.empty():
                continue  # notificación llegó en la ventana, reintentar
            await self._has_work.wait()

    def mark_complete(self, execution_id: str) -> bool:
        """Mark execution as complete. Return True if found and removed."""
        if execution_id in self._active:
            self._active.remove(execution_id)
            self._stats["total_completed"] += 1

            logger.info(
                "Completed execution {id}, active: {active}/{max}",
                id=execution_id,
                active=len(self._active),
                max=self.max_concurrent,
            )
            self._has_work.set()
            return True
        return False

    def cancel_execution(self, execution_id: str) -> bool:
        """Cancel queued execution (not yet started). Return True if found."""
        if execution_id in self._waiting:
            del self._waiting[execution_id]
            # Mark ID so dequeue() skips it when it naturally surfaces from the heap
            self._cancelled_ids.add(execution_id)
            self._stats["total_cancelled"] += 1

            logger.info(
                "Cancelled queued execution {id}",
                id=execution_id,
            )
            self._has_work.set()
            return True
        return False

    @property
    def is_over_capacity(self) -> bool:
        """Return True if we're at or over max concurrency."""
        return len(self._active) >= self.max_concurrent

    @property
    def queue_depth(self) -> int:
        """Return number of items waiting in queue."""
        return self._queue.qsize()

    @property
    def active_count(self) -> int:
        """Return number of active executions."""
        return len(self._active)

    def get_stats(self) -> dict:
        """Return queue statistics."""
        return {
            **self._stats,
            "active": self.active_count,
            "queued": self.queue_depth,
            "capacity": self.max_concurrent,
        }

    def shutdown(self) -> None:
        """Drain queue (on shutdown)."""
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except Empty:
                break
        self._active.clear()
        self._waiting.clear()
        self._cancelled_ids.clear()
        self._has_work.set()  # desbloquea cualquier dequeue() suspendido
