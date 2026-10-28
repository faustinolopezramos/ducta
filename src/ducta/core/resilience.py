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

import time
from typing import Callable, Iterable, Optional, Tuple, Type, TypeVar

from loguru import logger  # type: ignore

T = TypeVar("T")


class RetryPolicy:
    """
    Generic retry policy with exponential backoff.
    """

    SKIP_RETRY_ATTR = "skip_retry"

    def __init__(
        self,
        max_retries: int = 3,
        delay: int = 5,
        backoff_factor: float = 2.0,
        non_retryable: Iterable[Type[BaseException]] = (),
        max_delay: float = 60.0,
        cancel_check: Optional[Callable[[], bool]] = None,
    ):
        """Configure retry policy. Default backoff_factor=2.0 gives exponential delay.

        ``max_delay`` caps one wait (``delay * backoff_factor**n`` grows without bound).
        ``cancel_check`` is polled while waiting: once it is true the waiting ends and the
        last error is raised, so a cancelled run does not sit out a long backoff.
        """
        self.max_retries = max(0, max_retries)
        self.delay = delay
        self.backoff_factor = backoff_factor
        self.max_delay = max_delay
        self.cancel_check = cancel_check
        self.non_retryable: Tuple[Type[BaseException], ...] = tuple(non_retryable)

    def is_retryable(self, error: BaseException) -> bool:
        """Whether *error* is worth another attempt."""
        if getattr(error, self.SKIP_RETRY_ATTR, False):
            return False
        if self.non_retryable and isinstance(error, self.non_retryable):
            return False
        return True

    def execute(self, func: Callable[..., T], *args, **kwargs) -> T:
        """
        Execute a function with retries.
        """
        last_exception: Optional[BaseException] = None

        for attempt in range(self.max_retries + 1):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_exception = e

                if not self.is_retryable(e):
                    logger.error(
                        "Action failed with a non-retryable error ({}): {}. "
                        "Not retrying — the outcome would be identical.",
                        type(e).__name__,
                        e,
                    )
                    raise

                if attempt < self.max_retries:
                    sleep_time = self._calculate_backoff(attempt)
                    logger.warning(
                        f"Action failed: {str(e)}. "
                        f"Retrying (attempt {attempt + 1}/{self.max_retries}) in {sleep_time:.2f}s..."
                    )
                    if self._wait(sleep_time):
                        logger.warning("Retry abandoned: the action was cancelled while waiting.")
                        raise
                else:
                    logger.error(f"Action failed after {self.max_retries + 1} attempts.")

        if last_exception is None:  # pragma: no cover - defensive
            raise RuntimeError("RetryPolicy.execute exhausted attempts without an exception")
        raise last_exception

    def _wait(self, seconds: float) -> bool:
        """Sleep ``seconds``; True if ``cancel_check`` turned true meanwhile."""
        if self.cancel_check is None:
            time.sleep(seconds)
            return False
        deadline = time.monotonic() + seconds
        while True:
            if self.cancel_check():
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(0.2, remaining))

    def _calculate_backoff(self, attempt: int) -> float:
        """Calculate exponential backoff delay for retry attempt, capped at ``max_delay``."""
        return min(self.max_delay, self.delay * (self.backoff_factor**attempt))
