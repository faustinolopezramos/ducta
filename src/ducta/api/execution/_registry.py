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
from typing import Callable, Dict, Generic, Optional, TypeVar

K = TypeVar("K")
V = TypeVar("V")


class KeyedRegistry(Generic[K, V]):
    """Thread-safe lazy registry keyed by e.g. execution id.

    Replaces the module-level ``dict`` + ``threading.Lock`` "lazy singleton"
    pattern that was hand-rolled independently (and inconsistently — some
    without a lock at all) across several execution/ modules.
    """

    def __init__(self, factory: Callable[[K], V]) -> None:
        self._items: Dict[K, V] = {}
        self._lock = threading.Lock()
        self._factory = factory

    def get_or_create(self, key: K) -> V:
        with self._lock:
            if key not in self._items:
                self._items[key] = self._factory(key)
            return self._items[key]

    def delete(self, key: K) -> bool:
        with self._lock:
            return self._items.pop(key, None) is not None

    def pop(self, key: K) -> Optional[V]:
        """Remove and return the entry for *key*, or None if absent."""
        with self._lock:
            return self._items.pop(key, None)

    def peek(self, key: K) -> Optional[V]:
        """Return the entry for *key* without creating one if absent."""
        with self._lock:
            return self._items.get(key)

    # ── Dict-like conveniences (kept small; mainly for tests/introspection) ──

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def __contains__(self, key: K) -> bool:
        with self._lock:
            return key in self._items

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    def __getitem__(self, key: K) -> V:
        with self._lock:
            return self._items[key]

    def __setitem__(self, key: K, value: V) -> None:
        with self._lock:
            self._items[key] = value
