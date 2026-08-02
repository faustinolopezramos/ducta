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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger  # type: ignore


class CachedConfigService:
    """LRU-cached configuration loader with TTL invalidation."""

    def __init__(self, ttl_seconds: int = 300, max_size: int = 100) -> None:
        """Initialize cache."""
        self.ttl_seconds = ttl_seconds
        self.max_size = max_size

        # Thread-safe cache dict: path → (timestamp, data)
        self._cache: Dict[str, tuple[datetime, Any]] = {}
        self._cache_lock = threading.RLock()

    def load(self, path: Path, loader_fn) -> Any:
        """Load config file with caching."""
        path = Path(path)
        now = datetime.now(tz=timezone.utc)
        path_key = str(path)

        # Fast path: check cache under lock
        with self._cache_lock:
            if path_key in self._cache:
                cached_time, cached_data = self._cache[path_key]
                age = (now - cached_time).total_seconds()

                if age < self.ttl_seconds:
                    logger.debug(
                        "CachedConfigService: cache hit for {path} (age={age:.1f}s)",
                        path=path.name,
                        age=age,
                    )
                    return cached_data

        # Slow path: load outside the lock to avoid blocking other threads
        logger.debug(
            "CachedConfigService: cache miss for {path}",
            path=path.name,
        )
        data = loader_fn(path)

        # Store result under lock
        with self._cache_lock:
            self._cache[path_key] = (now, data)

            # Simple LRU: evict oldest if over limit
            if len(self._cache) > self.max_size:
                oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k][0])
                del self._cache[oldest_key]
                logger.debug(
                    "CachedConfigService: evicted {key}",
                    key=Path(oldest_key).name,
                )

            return data

    def invalidate(self, path: Optional[Path] = None) -> None:
        """Invalidate cache entry(ies)."""
        with self._cache_lock:
            if path is None:
                count = len(self._cache)
                self._cache.clear()
                logger.debug(
                    "CachedConfigService: cleared all {count} cache entries",
                    count=count,
                )
            else:
                path_str = str(Path(path))
                if path_str in self._cache:
                    del self._cache[path_str]
                    logger.debug(
                        "CachedConfigService: invalidated {path}",
                        path=Path(path).name,
                    )

    def stats(self) -> Dict[str, Any]:
        """Return cache statistics."""
        with self._cache_lock:
            return {
                "size": len(self._cache),
                "max_size": self.max_size,
                "ttl_seconds": self.ttl_seconds,
            }


_cached_config_service: Optional[CachedConfigService] = None
_service_lock = threading.RLock()


def get_cached_config_service(ttl_seconds: int = 300) -> CachedConfigService:
    """Get or create global cached config service."""
    global _cached_config_service

    with _service_lock:
        if _cached_config_service is None:
            _cached_config_service = CachedConfigService(ttl_seconds=ttl_seconds)
        return _cached_config_service
