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

import functools
import random
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Optional, TypeVar

from loguru import logger

from ducta.mlrun.exceptions import ResilienceError, ResourceLimitError  # noqa: F401


@dataclass
class RetryConfig:
    """Configuration for retry behavior."""

    max_attempts: int = 3
    initial_delay: float = 0.1
    max_delay: float = 10.0
    exponential_base: float = 2.0
    jitter: bool = True
    retryable_exceptions: tuple = (IOError, OSError, TimeoutError)
    non_retryable_exceptions: tuple = ()

    def __post_init__(self):
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.initial_delay < 0:
            raise ValueError("initial_delay must be non-negative")
        if self.max_delay < self.initial_delay:
            raise ValueError("max_delay must be >= initial_delay")


# Default retry configurations for different operation types
DEFAULT_RETRY_CONFIG = RetryConfig(
    max_attempts=3,
    initial_delay=0.1,
    max_delay=5.0,
)


STORAGE_RETRY_CONFIG = RetryConfig(
    max_attempts=3,
    initial_delay=0.5,
    max_delay=15.0,
    retryable_exceptions=(IOError, OSError, TimeoutError),
    non_retryable_exceptions=(PermissionError, ValueError, FileNotFoundError, FileExistsError),
)


class RetryExhaustedError(ResilienceError):
    """Raised when all retry attempts have been exhausted."""

    def __init__(self, operation: str, attempts: int, last_error: Exception):
        self.operation = operation
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(
            f"Operation '{operation}' failed after {attempts} attempts. Last error: {last_error}"
        )


class CircuitBreakerOpenError(ResilienceError):
    """Raised when circuit breaker is open and preventing operations."""

    def __init__(self, name: str, reset_time: float):
        self.name = name
        self.reset_time = reset_time
        super().__init__(
            f"Circuit breaker '{name}' is open. Will reset in {reset_time:.1f} seconds."
        )


def calculate_delay(
    attempt: int,
    config: RetryConfig,
) -> float:
    """
    Calculate delay for next retry attempt using exponential backoff with optional jitter.
    """
    delay = config.initial_delay * (config.exponential_base**attempt)
    delay = min(delay, config.max_delay)
    return delay if not config.jitter else _apply_jitter(delay)


def _apply_jitter(delay: float) -> float:
    """Apply random jitter to delay (+/- 25%)."""
    jitter_range = delay * 0.25
    return max(0, delay + random.uniform(-jitter_range, jitter_range))


def should_retry(
    exception: Exception,
    config: RetryConfig,
) -> bool:
    """
    Determine if an exception should trigger a retry based on configured exception types.
    """

    def _classify(exc: Exception) -> Optional[bool]:
        if config.non_retryable_exceptions and isinstance(exc, config.non_retryable_exceptions):
            return False
        if isinstance(exc, config.retryable_exceptions):
            return True
        return None

    decision = _classify(exception)
    if decision is not None:
        return decision

    cause = getattr(exception, "cause", None) or exception.__cause__
    if isinstance(cause, Exception) and cause is not exception:
        return bool(_classify(cause))

    return False


F = TypeVar("F", bound=Callable[..., Any])


def _handle_retry_exception(
    exc: Exception,
    attempt: int,
    name: str,
    config: RetryConfig,
    on_retry: Optional[Callable[[Exception, int], None]],
) -> None:
    """
    Handle a retry exception by logging and sleeping.
    """
    if not should_retry(exc, config):
        # Raised as it is, for the caller to handle: a missing registry index on
        # a first run is "empty", not a problem. Warning here put it on the
        # terminal of every first run.
        logger.debug("Non-retryable exception in '{}': {}", name, exc)
        raise exc  # NOSONAR

    if attempt + 1 >= config.max_attempts:
        logger.error(f"'{name}' failed after {attempt + 1} attempts: {exc}")
        raise RetryExhaustedError(name, attempt + 1, exc) from exc

    delay = calculate_delay(attempt, config)
    logger.warning(
        f"'{name}' attempt {attempt + 1}/{config.max_attempts} "
        f"failed: {exc}. Retrying in {delay:.2f}s..."
    )

    if on_retry:
        try:
            on_retry(exc, attempt + 1)
        except Exception:
            pass

    time.sleep(delay)


def retry_call(
    config: Optional[RetryConfig],
    operation_name: str,
    func: Callable[..., Any],
    *args: Any,
    on_retry: Optional[Callable[[Exception, int], None]] = None,
    **kwargs: Any,
) -> Any:
    """
    Execute ``func(*args, **kwargs)`` with retry, resolving ``config`` at call
    time.
    """
    if config is None:
        config = DEFAULT_RETRY_CONFIG

    last_exception: Exception

    for attempt in range(config.max_attempts):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last_exception = e
            _handle_retry_exception(e, attempt, operation_name, config, on_retry)

    raise RetryExhaustedError(operation_name, config.max_attempts, last_exception)


def with_instance_retry(operation_name: str) -> Callable[[F], F]:
    """
    Decorator for a bound method whose retry behavior must come from the
    instance, not from a config baked in at class-definition time.
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            config = getattr(self, "_retry_config", None) or DEFAULT_RETRY_CONFIG
            return retry_call(config, operation_name, func, self, *args, **kwargs)

        return wrapper  # type: ignore

    return decorator


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Blocking requests
    HALF_OPEN = "half_open"  # Testing if service recovered


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker."""

    failure_threshold: int = 5
    success_threshold: int = 2
    timeout: float = 30.0
    half_open_max_calls: int = 3


class CircuitBreaker:
    """
    Circuit breaker implementation for fault tolerance.
    """

    def __init__(
        self,
        name: str,
        config: Optional[CircuitBreakerConfig] = None,
    ):
        self.name = name
        self.config = config or CircuitBreakerConfig()

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: Optional[float] = None
        self._half_open_calls = 0
        self._lock = threading.RLock()

    @property
    def state(self) -> CircuitState:
        """Current circuit state."""
        with self._lock:
            self._maybe_transition_from_open()
            return self._state

    @property
    def is_available(self) -> bool:
        """Check if circuit allows operations."""
        return self.state != CircuitState.OPEN

    def _maybe_transition_from_open(self) -> None:
        """Check if timeout has passed and transition to half-open."""
        if self._state != CircuitState.OPEN:
            return

        if self._last_failure_time is None:
            return

        elapsed = time.time() - self._last_failure_time
        if elapsed >= self.config.timeout:
            logger.info(f"Circuit breaker '{self.name}' transitioning from OPEN to HALF_OPEN")
            self._state = CircuitState.HALF_OPEN
            self._half_open_calls = 0
            self._success_count = 0

    def record_success(self) -> None:
        """Record a successful operation."""
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.config.success_threshold:
                    logger.info(f"Circuit breaker '{self.name}' transitioning to CLOSED")
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    self._success_count = 0
            elif self._state == CircuitState.CLOSED:
                # Reset failure count on success
                self._failure_count = 0

    def record_failure(self, error: Optional[Exception] = None) -> None:
        """Record a failed operation."""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()

            if self._state == CircuitState.HALF_OPEN:
                logger.warning(
                    f"Circuit breaker '{self.name}' failure in HALF_OPEN, "
                    f"transitioning to OPEN" + (f": {error}" if error else "")
                )
                self._state = CircuitState.OPEN
                self._half_open_calls = 0
            elif self._state == CircuitState.CLOSED:
                if self._failure_count >= self.config.failure_threshold:
                    logger.warning(
                        f"Circuit breaker '{self.name}' threshold reached "
                        f"({self._failure_count}), transitioning to OPEN"
                        + (f": {error}" if error else "")
                    )
                    self._state = CircuitState.OPEN

    def check(self) -> None:
        """
        Check if operation is allowed.
        """
        with self._lock:
            self._maybe_transition_from_open()

            if self._state == CircuitState.OPEN:
                remaining = 0.0
                if self._last_failure_time:
                    remaining = max(
                        0, self.config.timeout - (time.time() - self._last_failure_time)
                    )
                raise CircuitBreakerOpenError(self.name, remaining)

            if self._state == CircuitState.HALF_OPEN:
                self._half_open_calls += 1
                if self._half_open_calls > self.config.half_open_max_calls:
                    self._state = CircuitState.OPEN
                    self._last_failure_time = time.time()
                    raise CircuitBreakerOpenError(self.name, self.config.timeout)

    def reset(self) -> None:
        """Manually reset the circuit breaker to closed state."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._half_open_calls = 0
            self._last_failure_time = None
            logger.info(f"Circuit breaker '{self.name}' manually reset to CLOSED")

    def __call__(self, func: F) -> F:
        """Use circuit breaker as a decorator."""

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            self.check()
            try:
                result = func(*args, **kwargs)
                self.record_success()
                return result
            except Exception:
                self.record_failure()
                raise

        return wrapper  # type: ignore
