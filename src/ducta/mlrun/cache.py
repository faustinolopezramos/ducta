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

import hashlib
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Generic, List, Optional, TypeVar, Union

from loguru import logger

K = TypeVar("K")  # Key type
V = TypeVar("V")  # Value type


@dataclass
class CacheEntry(Generic[V]):
    """A single cache entry with metadata."""

    value: V
    created_at: float
    last_accessed: float
    access_count: int = 0
    ttl_seconds: Optional[float] = None

    @property
    def age(self) -> float:
        """Get age of entry in seconds."""
        return time.time() - self.created_at

    @property
    def is_expired(self) -> bool:
        """Check if entry has expired based on TTL."""
        if self.ttl_seconds is None:
            return False
        return self.age > self.ttl_seconds

    def touch(self) -> None:
        """Update last access time and increment counter."""
        self.last_accessed = time.time()
        self.access_count += 1


@dataclass
class CacheStats:
    """Cache statistics for monitoring."""

    hits: int = 0
    misses: int = 0
    evictions: int = 0
    expirations: int = 0
    size: int = 0
    max_size: int = 0

    @property
    def hit_rate(self) -> float:
        """Calculate cache hit rate."""
        total = self.hits + self.misses
        if total == 0:
            return 0.0
        return self.hits / total

    @property
    def miss_rate(self) -> float:
        """Calculate cache miss rate."""
        return 1.0 - self.hit_rate

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "expirations": self.expirations,
            "size": self.size,
            "max_size": self.max_size,
            "hit_rate": f"{self.hit_rate:.2%}",
            "miss_rate": f"{self.miss_rate:.2%}",
        }


class LRUCache(Generic[K, V]):
    """
    Thread-safe LRU (Least Recently Used) cache with TTL support.
    """

    def __init__(
        self,
        max_size: int = 1000,
        default_ttl: Optional[float] = None,
        cleanup_interval: float = 60.0,
    ):
        """
        Initialize LRU cache.
        """
        self._max_size = max_size
        self._default_ttl = default_ttl
        self._cleanup_interval = cleanup_interval

        self._cache: OrderedDict[K, CacheEntry[V]] = OrderedDict()
        self._lock = threading.RLock()
        self._stats = CacheStats(max_size=max_size)
        self._last_cleanup = time.time()

    def get(self, key: K, default: Optional[V] = None) -> Optional[V]:
        """
        Get value from cache.
        """
        with self._lock:
            self._maybe_cleanup()

            if key not in self._cache:
                self._stats.misses += 1
                return default

            entry = self._cache[key]

            # Check expiration
            if entry.is_expired:
                del self._cache[key]
                self._stats.expirations += 1
                self._stats.misses += 1
                self._stats.size = len(self._cache)
                return default

            # Move to end (most recently used)
            self._cache.move_to_end(key)
            entry.touch()

            self._stats.hits += 1
            return entry.value

    def set(
        self,
        key: K,
        value: V,
        ttl: Optional[float] = None,
    ) -> None:
        """
        Set value in cache.
        """
        with self._lock:
            self._maybe_cleanup()

            now = time.time()
            entry = CacheEntry(
                value=value,
                created_at=now,
                last_accessed=now,
                ttl_seconds=ttl if ttl is not None else self._default_ttl,
            )

            # If key exists, update it
            if key in self._cache:
                self._cache[key] = entry
                self._cache.move_to_end(key)
            else:
                # Evict if at capacity
                while len(self._cache) >= self._max_size:
                    self._evict_oldest()

                self._cache[key] = entry

            self._stats.size = len(self._cache)

    def delete(self, key: K) -> bool:
        """
        Delete key from cache.
        """
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                self._stats.size = len(self._cache)
                return True
            return False

    def clear(self) -> None:
        """Clear all entries from cache."""
        with self._lock:
            self._cache.clear()
            self._stats.size = 0

    def has(self, key: K) -> bool:
        """Check if key exists in cache (without updating access time)."""
        with self._lock:
            if key not in self._cache:
                return False
            entry = self._cache[key]
            return not entry.is_expired

    def get_stats(self) -> CacheStats:
        """Get cache statistics."""
        with self._lock:
            self._stats.size = len(self._cache)
            return CacheStats(
                hits=self._stats.hits,
                misses=self._stats.misses,
                evictions=self._stats.evictions,
                expirations=self._stats.expirations,
                size=self._stats.size,
                max_size=self._stats.max_size,
            )

    def _evict_oldest(self) -> None:
        """Evict the oldest (least recently used) entry."""
        if self._cache:
            self._cache.popitem(last=False)
            self._stats.evictions += 1

    def _maybe_cleanup(self) -> None:
        """Perform cleanup if interval has passed."""
        now = time.time()
        if now - self._last_cleanup >= self._cleanup_interval:
            self._cleanup_expired()
            self._last_cleanup = now

    def _cleanup_expired(self) -> None:
        """Remove all expired entries."""
        expired_keys = [key for key, entry in self._cache.items() if entry.is_expired]

        for key in expired_keys:
            del self._cache[key]
            self._stats.expirations += 1

        self._stats.size = len(self._cache)

    def get_many(self, keys: List[K]) -> Dict[K, V]:
        """
        Get multiple values from cache.
        """
        results = {}
        for key in keys:
            value = self.get(key)
            if value is not None:
                results[key] = value
        return results

    def set_many(
        self,
        items: Dict[K, V],
        ttl: Optional[float] = None,
    ) -> None:
        """
        Set multiple values in cache.
        """
        for key, value in items.items():
            self.set(key, value, ttl)


class TwoLevelCache(Generic[K, V]):
    """
    Two-level cache with fast L1 (memory) and slower L2 (storage).
    """

    # How long a thread waiting on someone else's in-flight L2 load polls
    # before re-checking, and the overall ceiling before giving up.
    _IN_FLIGHT_POLL_INTERVAL: float = 5.0
    _IN_FLIGHT_MAX_WAIT: float = 60.0

    def __init__(
        self,
        l1_size: int = 100,
        l1_ttl: Optional[float] = 60.0,
        l2_loader: Optional[Callable[[K], V]] = None,
        l2_writer: Optional[Callable[[K, V], None]] = None,
        l2_deleter: Optional[Callable[[K], None]] = None,
        write_through: bool = True,
    ):
        """
        Initialize two-level cache.
        """
        self._l1 = LRUCache[K, V](max_size=l1_size, default_ttl=l1_ttl)
        self._l2_loader = l2_loader
        self._l2_writer = l2_writer
        self._l2_deleter = l2_deleter
        self._write_through = write_through
        self._lock = threading.RLock()
        # Per-key in-flight tracking: only one goroutine loads from L2 per key at a time
        # (A-04: thundering herd prevention)
        self._in_flight: Dict[Any, threading.Event] = {}
        self._inflight_lock = threading.Lock()

    def get(self, key: K, default: Optional[V] = None) -> Optional[V]:
        """
        Get value, checking L1 first then L2.
        Uses a per-key in-flight gate to prevent thundering herd when multiple
        threads simultaneously request the same missing key from L2.
        """
        # Try L1 first
        value = self._l1.get(key)
        if value is not None:
            return value

        # Try L2 if loader provided
        if self._l2_loader is None:
            return default

        # Check if another thread is already loading this key from L2
        with self._inflight_lock:
            if key in self._in_flight:
                in_flight_event = self._in_flight[key]
            else:
                # This thread will do the load; register a gate for other threads
                in_flight_event = threading.Event()
                self._in_flight[key] = in_flight_event
                in_flight_event = None  # sentinel: this thread is the loader

        if in_flight_event is not None:
            # Another thread is loading. Poll in bounded increments rather
            # than giving up after a single wait() timeout: wait() returning
            # False only means the loader hasn't finished *yet* — checking
            # L1 immediately after a timeout could hand back a stale `default`
            # for a load that was seconds away from succeeding.
            waited = 0.0
            while waited < self._IN_FLIGHT_MAX_WAIT:
                signaled = in_flight_event.wait(timeout=self._IN_FLIGHT_POLL_INTERVAL)
                waited += self._IN_FLIGHT_POLL_INTERVAL
                if signaled:
                    break
            else:
                logger.warning(
                    "Timed out after {}s waiting for in-flight L2 load of key {!r}",
                    self._IN_FLIGHT_MAX_WAIT,
                    key,
                )
            # After the loader thread completes (or we gave up waiting), the
            # value is in L1 if and only if the load actually succeeded.
            return self._l1.get(key, default)

        # This thread is the loader
        try:
            value = self._l2_loader(key)
            if value is not None:
                self._l1.set(key, value)
            return value if value is not None else default
        except Exception as e:
            # A real L2 failure (permissions, corruption, network) must be
            # distinguishable from a normal cache miss — silently returning
            # `default` here hid the difference entirely.
            logger.warning("L2 cache loader failed for key {!r}: {}", key, e)
            return default
        finally:
            # Signal all waiting threads and remove the gate
            with self._inflight_lock:
                gate = self._in_flight.pop(key, None)
            if gate is not None:
                gate.set()

    def set(
        self,
        key: K,
        value: V,
        ttl: Optional[float] = None,
    ) -> None:
        """
        Set value in cache.
        """
        # Always set in L1
        self._l1.set(key, value, ttl)

        # Write-through to L2 if configured
        if self._write_through and self._l2_writer is not None:
            with self._lock:
                try:
                    self._l2_writer(key, value)
                except Exception as e:
                    logger.warning(f"L2 cache write failed for {key}: {e}")

    def delete(self, key: K) -> bool:
        """Delete from L1 and optionally L2 backend to prevent stale data reappearing."""
        l1_deleted = self._l1.delete(key)
        if self._l2_deleter is not None:
            try:
                self._l2_deleter(key)
            except Exception as e:
                logger.warning(f"L2 cache delete failed for {key}: {e}")
        return l1_deleted

    def clear(self) -> None:
        """Clear L1 cache."""
        self._l1.clear()

    def get_stats(self) -> CacheStats:
        """Get L1 cache statistics."""
        return self._l1.get_stats()


@dataclass
class BatchOperation:
    """A single operation in a batch."""

    operation: str  # "read", "write", "delete"
    key: str
    value: Optional[Any] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BatchResult:
    """Result of a batch operation."""

    successful: int
    failed: int
    errors: List[str]
    duration_seconds: float

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "successful": self.successful,
            "failed": self.failed,
            "errors": self.errors,
            "duration_seconds": self.duration_seconds,
        }


class BatchProcessor(Generic[K, V]):
    """
    Batch processor for efficient bulk operations.
    """

    def __init__(
        self,
        reader: Optional[Callable[[K], V]] = None,
        writer: Optional[Callable[[K, V], None]] = None,
        deleter: Optional[Callable[[K], None]] = None,
        batch_size: int = 100,
        auto_execute_threshold: Optional[int] = None,
    ):
        """
        Initialize batch processor.
        """
        self._reader = reader
        self._writer = writer
        self._deleter = deleter
        self._batch_size = batch_size
        self._auto_threshold = auto_execute_threshold

        self._queue: List[BatchOperation] = []
        self._results: Dict[str, Any] = {}
        self._lock = threading.RLock()

    def queue_read(self, key: K, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Queue a read operation."""
        with self._lock:
            self._queue.append(
                BatchOperation(
                    operation="read",
                    key=str(key),
                    metadata=metadata or {},
                )
            )
            self._maybe_auto_execute()

    def queue_write(
        self,
        key: K,
        value: V,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Queue a write operation."""
        with self._lock:
            self._queue.append(
                BatchOperation(
                    operation="write",
                    key=str(key),
                    value=value,
                    metadata=metadata or {},
                )
            )
            self._maybe_auto_execute()

    def queue_delete(self, key: K, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Queue a delete operation."""
        with self._lock:
            self._queue.append(
                BatchOperation(
                    operation="delete",
                    key=str(key),
                    metadata=metadata or {},
                )
            )
            self._maybe_auto_execute()

    def execute(self) -> BatchResult:
        """
        Execute all queued operations.
        """
        with self._lock:
            operations = self._queue.copy()
            self._queue.clear()

        start_time = time.time()
        successful = 0
        failed = 0
        errors: List[str] = []

        for op in operations:
            try:
                if op.operation == "read" and self._reader:
                    result = self._reader(op.key)
                    self._results[op.key] = result
                    successful += 1
                elif op.operation == "write" and self._writer:
                    self._writer(op.key, op.value)
                    successful += 1
                elif op.operation == "delete" and self._deleter:
                    self._deleter(op.key)
                    successful += 1
                else:
                    failed += 1
                    errors.append(f"No handler for {op.operation}")
            except Exception as e:
                failed += 1
                errors.append(f"{op.operation} {op.key}: {e}")

        duration = time.time() - start_time

        return BatchResult(
            successful=successful,
            failed=failed,
            errors=errors,
            duration_seconds=duration,
        )

    def get_results(self) -> Dict[str, Any]:
        """Get results from read operations."""
        with self._lock:
            return self._results.copy()

    def clear_results(self) -> None:
        """Clear stored results."""
        with self._lock:
            self._results.clear()

    def pending_count(self) -> int:
        """Get count of pending operations."""
        with self._lock:
            return len(self._queue)

    def _maybe_auto_execute(self) -> None:
        """Auto-execute if threshold reached."""
        if self._auto_threshold is not None and len(self._queue) >= self._auto_threshold:
            self.execute()

    def close(self, execute_pending: bool = True) -> Optional[BatchResult]:
        """
        Close the batch processor and optionally execute pending operations.
        """
        with self._lock:
            result = None
            if execute_pending and self._queue:
                result = self.execute()
            self._queue.clear()
            self._results.clear()
            return result

    def __enter__(self) -> "BatchProcessor[K, V]":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Context manager exit - executes pending operations."""
        self.close(execute_pending=(exc_type is None))
        return False


class CacheKeyBuilder:
    """
    Utility for building consistent cache keys.
    """

    def __init__(self, prefix: str = "mlops", separator: str = ":"):
        self.prefix = prefix
        self.separator = separator

    def _escape_part(self, part: str) -> str:
        """Escape backslash and the separator within a part.

        Without this, `custom_key("json", "a:b")` and
        `custom_key("json", "a", "b")` join to the identical string
        ("mlops:json:a:b") despite being built from different part tuples —
        a real key collision for any caller whose part happens to contain
        the separator.
        """
        escaped = part.replace("\\", "\\\\")
        return escaped.replace(self.separator, "\\" + self.separator)

    def _build(self, *parts: str) -> str:
        """Build key from parts."""
        escaped_parts = [self._escape_part(str(p)) for p in parts]
        return self.separator.join([self.prefix] + escaped_parts)

    def model_key(
        self,
        model_name: str,
        version: Optional[int] = None,
    ) -> str:
        """Build model cache key."""
        if version is not None:
            return self._build("model", model_name, f"v{version}")
        return self._build("model", model_name, "latest")

    def experiment_key(self, experiment_id: str) -> str:
        """Build experiment cache key."""
        return self._build("experiment", experiment_id)

    def run_key(self, experiment_id: str, run_id: str) -> str:
        """Build run cache key."""
        return self._build("run", experiment_id, run_id)

    def metrics_key(self, run_id: str, metric_name: Optional[str] = None) -> str:
        """Build metrics cache key."""
        if metric_name:
            return self._build("metrics", run_id, metric_name)
        return self._build("metrics", run_id)

    def index_key(self, index_type: str) -> str:
        """Build index cache key."""
        return self._build("index", index_type)

    def custom_key(self, *parts: str) -> str:
        """Build custom cache key."""
        return self._build(*parts)

    @staticmethod
    def hash_key(data: Union[str, bytes]) -> str:
        """Create a hash-based key from data."""
        if isinstance(data, str):
            data = data.encode("utf-8")
        return hashlib.sha256(data).hexdigest()[:16]


class CachedStorage:
    """
    Wrapper that adds caching to a storage backend.
    """

    def __init__(
        self,
        storage: Any,
        cache_size: int = 500,
        cache_ttl: Optional[float] = 300.0,
    ):
        """
        Initialize cached storage wrapper.
        """
        self._storage = storage
        self._json_cache: LRUCache[str, Dict[str, Any]] = LRUCache(
            max_size=cache_size,
            default_ttl=cache_ttl,
        )
        self._df_cache: LRUCache[str, Any] = LRUCache(
            max_size=cache_size // 5,  # DataFrames are larger
            default_ttl=cache_ttl,
        )
        self._key_builder = CacheKeyBuilder()

    def read_json(self, path: str) -> Dict[str, Any]:
        """Read JSON with caching."""
        cache_key = self._key_builder.custom_key("json", path)

        # Check cache
        cached = self._json_cache.get(cache_key)
        if cached is not None:
            return cached

        # Read from storage
        data = self._storage.read_json(path)

        # Cache result
        self._json_cache.set(cache_key, data)

        return data

    def write_json(
        self,
        data: Dict[str, Any],
        path: str,
        mode: str = "overwrite",
    ) -> Any:
        """Write JSON and invalidate cache."""
        # Write to storage
        result = self._storage.write_json(data, path, mode)

        # Invalidate cache
        cache_key = self._key_builder.custom_key("json", path)
        self._json_cache.delete(cache_key)

        return result

    def read_dataframe(self, path: str) -> Any:
        """Read DataFrame with caching."""
        cache_key = self._key_builder.custom_key("df", path)

        # Check cache
        cached = self._df_cache.get(cache_key)
        if cached is not None:
            return cached

        # Read from storage
        df = self._storage.read_dataframe(path)

        # Cache result
        self._df_cache.set(cache_key, df)

        return df

    def write_dataframe(
        self,
        df: Any,
        path: str,
        mode: str = "overwrite",
    ) -> Any:
        """Write DataFrame and invalidate cache."""
        # Write to storage
        result = self._storage.write_dataframe(df, path, mode)

        # Invalidate cache
        cache_key = self._key_builder.custom_key("df", path)
        self._df_cache.delete(cache_key)

        return result

    def invalidate(self, path: str) -> None:
        """Invalidate cache for a path."""
        self._json_cache.delete(self._key_builder.custom_key("json", path))
        self._df_cache.delete(self._key_builder.custom_key("df", path))

    def invalidate_all(self) -> None:
        """Clear all caches."""
        self._json_cache.clear()
        self._df_cache.clear()

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get combined cache statistics."""
        return {
            "json_cache": self._json_cache.get_stats().to_dict(),
            "dataframe_cache": self._df_cache.get_stats().to_dict(),
        }

    def __getattr__(self, name: str) -> Any:
        """Delegate unknown attributes to underlying storage."""
        return getattr(self._storage, name)
