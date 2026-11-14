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
import time
from typing import Callable, Dict, List, Tuple

from ducta_server.config import get_settings


class LoginThrottle:
    """Failed-login counter per key, with a lockout once *max_attempts* is reached."""

    def __init__(
        self,
        max_attempts: int = 5,
        window_seconds: int = 900,
        lockout_seconds: int = 300,
        max_keys: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self.lockout_seconds = lockout_seconds
        self.max_keys = max_keys
        self._clock = clock
        self._failures: Dict[Tuple[str, str], List[float]] = {}
        self._locked_until: Dict[Tuple[str, str], float] = {}
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self.max_attempts > 0 and self.lockout_seconds > 0

    def retry_after(self, client: str, username: str) -> int:
        """Seconds until this client may try this user again; 0 when it may now."""
        if not self.enabled:
            return 0
        key = (client, username.lower())
        with self._lock:
            until = self._locked_until.get(key)
            if until is None:
                return 0
            left = until - self._clock()
            if left <= 0:
                del self._locked_until[key]
                self._failures.pop(key, None)
                return 0
            return int(left) + 1

    def record_failure(self, client: str, username: str) -> None:
        if not self.enabled:
            return
        key = (client, username.lower())
        now = self._clock()
        with self._lock:
            self._evict_locked(now)
            recent = [t for t in self._failures.get(key, []) if now - t < self.window_seconds]
            recent.append(now)
            self._failures[key] = recent
            if len(recent) >= self.max_attempts:
                self._locked_until[key] = now + self.lockout_seconds

    def record_success(self, client: str, username: str) -> None:
        key = (client, username.lower())
        with self._lock:
            self._failures.pop(key, None)
            self._locked_until.pop(key, None)

    def _evict_locked(self, now: float) -> None:
        """Forget what has expired; if still over capacity, the oldest keys."""
        if len(self._failures) < self.max_keys:
            return
        for key in [
            k
            for k, times in self._failures.items()
            if all(now - t >= self.window_seconds for t in times)
            and self._locked_until.get(k, 0) <= now
        ]:
            self._failures.pop(key, None)
            self._locked_until.pop(key, None)
        while len(self._failures) >= self.max_keys:
            oldest = min(self._failures, key=lambda k: self._failures[k][-1])
            self._failures.pop(oldest, None)
            self._locked_until.pop(oldest, None)


_throttle: "LoginThrottle | None" = None
_throttle_lock = threading.Lock()


def get_login_throttle() -> LoginThrottle:
    """The process's throttle, built from the settings the first time it is asked for."""
    global _throttle
    if _throttle is None:
        with _throttle_lock:
            if _throttle is None:
                s = get_settings()
                _throttle = LoginThrottle(
                    max_attempts=s.login_max_attempts,
                    window_seconds=s.login_window_seconds,
                    lockout_seconds=s.login_lockout_seconds,
                )
    return _throttle


def reset_login_throttle() -> None:
    """Forget the throttle (tests, and settings that changed)."""
    global _throttle
    with _throttle_lock:
        _throttle = None
