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

import threading
import time
from enum import Enum
from typing import Any, Callable, Dict, Optional


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Minimal per-source circuit breaker: opens after N consecutive failures,
    stays open for a cooldown, then allows one trial call (half-open) before
    fully closing again on success or re-opening on failure."""

    def __init__(
        self,
        failure_threshold: int = 5,
        cooldown_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._threshold = failure_threshold
        self._cooldown = cooldown_seconds
        self._clock = clock
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._opened_at: Optional[float] = None

        self._lock = threading.Lock()

    def is_open(self) -> bool:
        """True if calls should be blocked. Transitions OPEN -> HALF_OPEN once the
        cooldown elapses (returns False exactly once, to allow a trial call).
        """
        with self._lock:
            if self._state is CircuitState.OPEN:
                if (
                    self._opened_at is not None
                    and (self._clock() - self._opened_at) >= self._cooldown
                ):
                    self._state = CircuitState.HALF_OPEN
                    return False
                return True
            if self._state is CircuitState.HALF_OPEN:
                return True
            return False

    def record_success(self) -> None:
        with self._lock:
            self._state = CircuitState.CLOSED
            self._consecutive_failures = 0
            self._opened_at = None

    def record_failure(self) -> None:
        with self._lock:
            self._consecutive_failures += 1
            if (
                self._state is CircuitState.HALF_OPEN
                or self._consecutive_failures >= self._threshold
            ):
                self._state = CircuitState.OPEN
                self._opened_at = self._clock()

    def state_dict(self) -> Dict[str, Any]:
        with self._lock:
            return {"state": self._state.value, "consecutive_failures": self._consecutive_failures}
