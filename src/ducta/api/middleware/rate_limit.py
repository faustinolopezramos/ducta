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
import uuid
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Deque, Dict, Optional

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware


class SlidingWindowLimiter:
    """Sliding window rate limiter using in-memory request timestamps."""

    def __init__(
        self,
        max_requests: int = 100,
        window_seconds: int = 60,
        max_keys: int = 10_000,
    ) -> None:
        """Initialize limiter."""
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.max_keys = max_keys

        # key -> deque of request timestamps (ascending order)
        self._requests: Dict[str, Deque[datetime]] = {}
        self._last_seen: Dict[str, datetime] = {}
        self._lock = threading.RLock()

    def is_allowed(self, key: str) -> bool:
        """Check if request is allowed for this key."""
        now = datetime.now(tz=timezone.utc)
        cutoff = now - timedelta(seconds=self.window_seconds)

        with self._lock:
            self._ensure_capacity_for_key_locked(key=key)

            bucket = self._requests.get(key)
            if bucket is None:
                bucket = deque()
                self._requests[key] = bucket

            while bucket and bucket[0] <= cutoff:
                bucket.popleft()

            self._last_seen[key] = now

            # Check if under limit
            if len(bucket) < self.max_requests:
                bucket.append(now)
                return True

            return False

    def _ensure_capacity_for_key_locked(self, key: str) -> None:
        """Keep key cardinality bounded before adding a new key."""
        if key in self._requests:
            return

        if len(self._requests) < self.max_keys:
            return

        self.cleanup_old_keys()
        if len(self._requests) < self.max_keys:
            return

        self._evict_oldest_key_locked()

    def _evict_oldest_key_locked(self) -> bool:
        """Evict the least recently seen key when cardinality limit is reached."""
        if not self._last_seen:
            return False

        oldest_key = min(self._last_seen, key=lambda k: self._last_seen[k])
        self._last_seen.pop(oldest_key, None)
        self._requests.pop(oldest_key, None)
        logger.debug(
            "SlidingWindowLimiter: evicted oldest key to enforce max_keys ({key})",
            key=oldest_key,
        )
        return True

    def cleanup_old_keys(self, now: datetime | None = None) -> int:
        """Remove keys with no recent requests."""
        if now is None:
            now = datetime.now(tz=timezone.utc)
        cutoff = now - timedelta(seconds=self.window_seconds * 2)

        with self._lock:
            return self._cleanup_old_keys_locked(cutoff=cutoff)

    def _cleanup_old_keys_locked(self, cutoff: datetime) -> int:
        keys_to_remove: list[str] = []
        for key, bucket in self._requests.items():
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()

            last_seen = self._last_seen.get(key)
            if not bucket and (last_seen is None or last_seen <= cutoff):
                keys_to_remove.append(key)

        for key in keys_to_remove:
            self._requests.pop(key, None)
            self._last_seen.pop(key, None)

        return len(keys_to_remove)

    @property
    def key_count(self) -> int:
        """Return the number of tracked limiter keys."""
        with self._lock:
            return len(self._requests)


class RedisSlidingWindowLimiter:
    """Sliding window rate limiter backed by Redis.

    Unlike ``SlidingWindowLimiter``, this enforces the limit consistently
    across multiple worker processes (or hosts) sharing the same Redis
    instance. The check-and-increment is done atomically via a Lua script
    to avoid races between concurrent workers.
    """

    _LUA_SCRIPT = """
    local key = KEYS[1]
    local now = tonumber(ARGV[1])
    local window = tonumber(ARGV[2])
    local max_requests = tonumber(ARGV[3])
    local member = ARGV[4]
    local cutoff = now - window
    redis.call('ZREMRANGEBYSCORE', key, '-inf', cutoff)
    local count = redis.call('ZCARD', key)
    if count < max_requests then
        redis.call('ZADD', key, now, member)
        redis.call('EXPIRE', key, window)
        return 1
    end
    return 0
    """

    def __init__(
        self,
        redis_client: Any,
        max_requests: int,
        window_seconds: int,
        key_prefix: str = "ducta:ratelimit:",
    ) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        # Not enforced for Redis: expiry keeps key cardinality bounded server-side.
        self.max_keys = -1
        self._client = redis_client
        self._key_prefix = key_prefix
        self._script = redis_client.register_script(self._LUA_SCRIPT)

    def is_allowed(self, key: str) -> bool:
        """Check if request is allowed for this key."""
        now = time.time()
        member = f"{now}:{uuid.uuid4().hex}"
        result = self._script(
            keys=[f"{self._key_prefix}{key}"],
            args=[now, self.window_seconds, self.max_requests, member],
        )
        return bool(result)

    def cleanup_old_keys(self, now: datetime | None = None) -> int:
        """No-op: Redis EXPIRE reclaims stale keys automatically."""
        return 0

    @property
    def key_count(self) -> int:
        """Unknown/unbounded — cardinality is managed by Redis key expiry."""
        return -1


def _build_limiter(
    max_requests: int,
    window_seconds: int,
    max_keys: int,
    redis_url: Optional[str],
) -> "SlidingWindowLimiter | RedisSlidingWindowLimiter":
    """Build the rate-limit counter backend.

    Uses Redis when *redis_url* is configured and the optional ``redis``
    package is installed, so the limit is correct across multiple worker
    processes. Falls back to a per-process in-memory limiter otherwise
    (the historical behavior, unaffected when Redis is not configured).
    """
    if redis_url:
        try:
            import redis as redis_lib

            client = redis_lib.Redis.from_url(redis_url)
            client.ping()
            logger.info("RateLimitMiddleware: using shared Redis backend at {url}", url=redis_url)
            return RedisSlidingWindowLimiter(
                redis_client=client,
                max_requests=max_requests,
                window_seconds=window_seconds,
            )
        except ImportError:
            logger.warning(
                "RATE_LIMIT_REDIS_URL is set but the 'redis' package is not installed "
                "(pip install ducta[redis]); falling back to a per-process in-memory "
                "rate limiter. The effective limit will scale with the worker count."
            )
        except Exception as exc:  # noqa: BLE001 - connection/auth errors, etc.
            logger.warning(
                "Could not connect to Redis at {url} for rate limiting ({exc}); "
                "falling back to a per-process in-memory rate limiter.",
                url=redis_url,
                exc=exc,
            )

    return SlidingWindowLimiter(
        max_requests=max_requests,
        window_seconds=window_seconds,
        max_keys=max_keys,
    )


_ws_limiter_cache: Dict[int, "SlidingWindowLimiter | RedisSlidingWindowLimiter"] = {}
_ws_limiter_cache_lock = threading.Lock()


def get_websocket_connection_limiter(
    settings: Any,
) -> "SlidingWindowLimiter | RedisSlidingWindowLimiter":
    """Return the rate limiter guarding WebSocket handshakes, building it once per *settings*.

    `RateLimitMiddleware` extends `BaseHTTPMiddleware`, which only intercepts
    the ASGI ``http`` scope — WebSocket connections (``/ws/logs/{execution_id}``,
    ``/ws/terminal``) bypass it entirely, so their handshakes had zero rate
    limiting even with ``rate_limit_enabled=True``. Callers should check this
    once per connection attempt, before ``websocket.accept()``. Reuses the
    same in-memory/Redis backend selection as the HTTP middleware.
    """
    key = id(settings)
    with _ws_limiter_cache_lock:
        limiter = _ws_limiter_cache.get(key)
        if limiter is None:
            limiter = _build_limiter(
                max_requests=settings.rate_limit_requests or 100,
                window_seconds=settings.rate_limit_window_seconds,
                max_keys=settings.rate_limit_max_keys,
                redis_url=settings.rate_limit_redis_url,
            )
            _ws_limiter_cache[key] = limiter
        return limiter


def get_websocket_client_key(websocket: Any) -> str:
    """Return the per-IP rate-limit key for a WebSocket connection.

    Mirrors ``RateLimitMiddleware._get_client_key``'s trusted-proxy handling
    of ``X-Forwarded-For``.
    """
    import ipaddress

    client_host = websocket.client.host if websocket.client else "unknown"
    forwarded = websocket.headers.get("x-forwarded-for")
    if forwarded and client_host != "unknown":
        try:
            client_addr = ipaddress.ip_address(client_host)
            if client_addr.is_private or client_addr.is_loopback:
                client_host = forwarded.split(",")[0].strip()
        except ValueError:
            pass

    return f"ip:{client_host}"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware for rate limiting by IP or auth user."""

    def __init__(
        self,
        app,
        max_requests_per_minute: int = 100,
        window_seconds: int = 60,
        max_keys: int = 10_000,
        cleanup_interval_seconds: int = 300,
        enabled: bool = True,
        redis_url: Optional[str] = None,
    ) -> None:
        """Initialize rate limit middleware."""
        super().__init__(app)
        self.enabled = enabled
        self.limiter = _build_limiter(
            max_requests=max_requests_per_minute,
            window_seconds=window_seconds,
            max_keys=max_keys,
            redis_url=redis_url,
        )
        self.window_seconds = window_seconds
        self.cleanup_interval = cleanup_interval_seconds
        self.last_cleanup = datetime.now(tz=timezone.utc)

    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        """Check rate limit and process request."""

        if not self.enabled:
            return await call_next(request)

        # Identify the client by IP (per-process, in-memory limiter).
        key = self._get_client_key(request)

        # Lazy cleanup of old entries
        now = datetime.now(tz=timezone.utc)
        if (now - self.last_cleanup).total_seconds() > self.cleanup_interval:
            removed = self.limiter.cleanup_old_keys(now=now)
            tracked = self.limiter.key_count
            if removed > 0 or (tracked >= 0 and tracked >= self.limiter.max_keys):
                logger.debug(
                    "RateLimitMiddleware: cleaned {count} keys, tracked={tracked}, max={max_keys}",
                    count=removed,
                    tracked=tracked,
                    max_keys=self.limiter.max_keys,
                )
            self.last_cleanup = now

        # Check rate limit
        if not self.limiter.is_allowed(key):
            logger.warning(
                "RateLimitMiddleware: rate limit exceeded for {key}",
                key=key,
            )
            # Return the response directly. Raising HTTPException here would NOT be
            # caught by the app's exception handlers (those live in the inner
            # ExceptionMiddleware), so it would surface as a 500 instead of a 429.
            return JSONResponse(
                status_code=429,
                content={
                    "error": "RATE_LIMIT_EXCEEDED",
                    "message": (
                        f"Rate limit exceeded ({self.limiter.max_requests} requests per "
                        f"{self.window_seconds}s). Please retry after {self.window_seconds} seconds."
                    ),
                },
                headers={"Retry-After": str(self.window_seconds)},
            )

        return await call_next(request)

    @staticmethod
    def _get_client_key(request: Request) -> str:
        """Return the per-IP rate-limit key for *request*.

        Honors ``X-Forwarded-For`` only when the immediate peer is a private or
        loopback address (i.e. a trusted reverse proxy); otherwise the direct
        client IP is used so the header cannot be spoofed to evade limits.
        """
        import ipaddress

        # Direct client IP
        client_host = request.client.host if request.client else "unknown"
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded and client_host != "unknown":
            try:
                client_addr = ipaddress.ip_address(client_host)
                if client_addr.is_private or client_addr.is_loopback:
                    # The immediate sender is a trusted proxy — use forwarded IP
                    client_host = forwarded.split(",")[0].strip()
            except ValueError:
                # Malformed IP — ignore forwarded header
                pass

        return f"ip:{client_host}"
