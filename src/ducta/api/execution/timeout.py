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
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

from loguru import logger


class TimeoutHandler:
    """Manages timeout for a single execution."""

    def __init__(self, execution_id: str, timeout_seconds: int, thread_id: int):
        self.execution_id = execution_id
        self.timeout_seconds = timeout_seconds
        self.thread_id = thread_id
        self.start_time = datetime.now(tz=timezone.utc)
        self.deadline = self.start_time + timedelta(seconds=timeout_seconds)
        self._timer: Optional[threading.Timer] = None
        self._timed_out = False

    @property
    def elapsed_seconds(self) -> float:
        """Return seconds elapsed since start."""
        return (datetime.now(tz=timezone.utc) - self.start_time).total_seconds()

    @property
    def remaining_seconds(self) -> float:
        """Return seconds until timeout."""
        return max(0, self.timeout_seconds - self.elapsed_seconds)

    @property
    def has_timed_out(self) -> bool:
        """Return True if timeout has been exceeded."""
        return self._timed_out

    def start(self) -> None:
        """Start the timeout timer."""
        if self._timer is not None:
            return

        def _on_timeout() -> None:
            self._timed_out = True
            logger.warning(
                "Execution {id}: timeout after {s}s",
                id=self.execution_id,
                s=self.timeout_seconds,
            )
            # Best-effort: asynchronously inject TimeoutError into the worker thread.
            # This is a CPython-only mechanism and only fires when the target thread
            # is executing Python bytecode (it cannot interrupt blocking C calls such
            # as the Spark JVM bridge); periodic verify() calls remain the reliable
            # path. The previous `hasattr(os, "tgkill")` guard was always False
            # (os.tgkill does not exist), so this injection never ran at all.
            try:
                import ctypes

                affected = ctypes.pythonapi.PyThreadState_SetAsyncExc(
                    ctypes.c_long(self.thread_id), ctypes.py_object(TimeoutError)
                )
                if affected > 1:
                    # Undo if more than the target thread was affected (shouldn't happen).
                    ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_long(self.thread_id), None)
            except Exception as e:
                logger.debug("Could not inject timeout exception: {e}", e=e)

        # Schedule timer for remaining timeout
        self._timer = threading.Timer(
            self.timeout_seconds,
            _on_timeout,
        )
        self._timer.daemon = True
        self._timer.start()
        logger.debug(
            "Timeout handler started: {id}, deadline in {s}s",
            id=self.execution_id,
            s=self.timeout_seconds,
        )

    def cancel(self) -> None:
        """Cancel the timeout timer."""
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
            logger.debug(
                "Timeout handler cancelled: {id}",
                id=self.execution_id,
            )

    def verify(self) -> None:
        """Raise TimeoutError if deadline exceeded. Call periodically from sync code."""
        if self.has_timed_out:
            raise TimeoutError(
                f"Pipeline execution {self.execution_id} exceeded timeout of "
                f"{self.timeout_seconds}s"
            )


class TimeoutManager:
    """Central manager for all execution timeouts."""

    # Default timeout: 1 hour (3600 seconds)
    DEFAULT_TIMEOUT_SECONDS = 3600

    def __init__(self, default_timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS):
        self._default_timeout_seconds = default_timeout_seconds
        self._handlers: Dict[str, TimeoutHandler] = {}
        self._lock = threading.RLock()

    def create_handler(
        self, execution_id: str, timeout_seconds: Optional[int] = None
    ) -> TimeoutHandler:
        """Create and register a timeout handler for an execution."""
        timeout = timeout_seconds or self._default_timeout_seconds
        thread_id = threading.get_ident()

        handler = TimeoutHandler(
            execution_id=execution_id,
            timeout_seconds=timeout,
            thread_id=thread_id,
        )

        with self._lock:
            self._handlers[execution_id] = handler

        handler.start()
        return handler

    def get_handler(self, execution_id: str) -> Optional[TimeoutHandler]:
        """Retrieve a timeout handler by execution ID."""
        with self._lock:
            return self._handlers.get(execution_id)

    def cancel_handler(self, execution_id: str) -> bool:
        """Cancel timeout for an execution. Return True if found."""
        handler = self.get_handler(execution_id)
        if handler:
            handler.cancel()
            with self._lock:
                del self._handlers[execution_id]
            return True
        return False

    def cleanup_timed_out(self) -> list[str]:
        """Return list of execution IDs that have timed out."""
        timed_out = []
        with self._lock:
            for exec_id, handler in self._handlers.items():
                if handler.has_timed_out:
                    timed_out.append(exec_id)
        return timed_out

    def cleanup_all(self) -> None:
        """Cancel all active timeout handlers (on shutdown)."""
        with self._lock:
            for handler in self._handlers.values():
                handler.cancel()
            self._handlers.clear()


# Singleton instance
_timeout_manager: Optional[TimeoutManager] = None


def get_timeout_manager(
    default_timeout_seconds: int = TimeoutManager.DEFAULT_TIMEOUT_SECONDS,
) -> TimeoutManager:
    """Get or create the singleton TimeoutManager."""
    global _timeout_manager
    if _timeout_manager is None:
        _timeout_manager = TimeoutManager(default_timeout_seconds)
    return _timeout_manager
