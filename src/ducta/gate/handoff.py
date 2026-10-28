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
from typing import Any, Optional

from loguru import logger  # type: ignore

from ducta.gate.context_manager import ContextManager

_STORE_KEY = "_ducta_df_handoff"  # a key on a dict context, an attribute on an object one
_LOCK = threading.Lock()


def is_enabled(context: Any) -> bool:
    """True when in-memory handoff is turned on in global_config."""
    if context is None:
        return False
    return bool(ContextManager(context).get_nested("global_config.in_memory_handoff", False))


def normalize_key(path: Any) -> str:
    """Canonical cache key for a storage path (strip trailing separators)."""
    return str(path).rstrip("/\\")


class _HandoffStore:
    """Thread-safe path→DataFrame store with a persisted-block registry for cleanup."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._frames: dict = {}

    def put(self, key: str, dataframe: Any) -> None:
        with self._lock:
            previous = self._frames.get(key)
            self._frames[key] = dataframe

        if previous is not None and previous is not dataframe:
            try:
                if hasattr(previous, "unpersist"):
                    previous.unpersist()
            except Exception as error:
                logger.warning("Failed to unpersist replaced handoff frame: {}", error)

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            return self._frames.get(key)

    def holds(self, dataframe: Any) -> bool:
        """Whether ``dataframe`` is one of the cached frames themselves (not a copy)."""
        with self._lock:
            return any(frame is dataframe for frame in self._frames.values())

    def drop(self, key: str) -> None:
        """Forget the frame held for ``key`` (it no longer is what is on disk)."""
        with self._lock:
            dropped = self._frames.pop(key, None)
        if dropped is not None and hasattr(dropped, "unpersist"):
            try:
                dropped.unpersist()
            except Exception as error:
                logger.warning("Failed to unpersist dropped handoff frame: {}", error)

    def clear(self) -> None:
        """Unpersist every cached frame and drop them. Safe to call repeatedly."""
        with self._lock:
            frames = list(self._frames.values())
            self._frames.clear()
        for dataframe in frames:
            try:
                if hasattr(dataframe, "unpersist"):
                    dataframe.unpersist()
            except Exception as error:
                logger.warning("Failed to unpersist cached handoff frame: {}", error)


def get_store(context: Any) -> Optional[_HandoffStore]:
    """Get-or-create the per-context handoff store; None if it can't attach."""
    if context is None:
        return None
    manager = ContextManager(context)
    store = manager.get(_STORE_KEY)
    if isinstance(store, _HandoffStore):
        return store
    with _LOCK:
        store = manager.get(_STORE_KEY)
        if not isinstance(store, _HandoffStore):
            store = _HandoffStore()
            if not manager.set(_STORE_KEY, store):
                return None
    return store


def _is_spark_dataframe(dataframe: Any) -> bool:
    return hasattr(dataframe, "persist") and hasattr(dataframe, "rdd")


def _is_pandas_dataframe(dataframe: Any) -> bool:
    """True for a pandas DataFrame, without importing pandas when absent."""
    if dataframe is None or _is_spark_dataframe(dataframe):
        return False
    try:
        import pandas as pd  # type: ignore

        return isinstance(dataframe, pd.DataFrame)
    except ImportError:
        return False


def offer(context: Any, path: Any, dataframe: Any, write_mode: Optional[str]) -> None:
    """Persist and register ``dataframe`` for handoff under ``path`` when eligible."""
    if not is_enabled(context):
        return
    mode = (write_mode or "overwrite").lower()
    store = get_store(context)
    if store is None:
        return
    if mode != "overwrite":
        # An append or merge changed what is at `path`: a frame kept from an earlier
        # overwrite would hand the next reader the data as it was before.
        store.drop(normalize_key(path))
        return

    if _is_spark_dataframe(dataframe):
        try:
            from pyspark import StorageLevel  # type: ignore

            dataframe.persist(StorageLevel.MEMORY_AND_DISK)
        except Exception:
            try:
                dataframe.persist()
            except Exception as error:
                logger.warning("Could not persist DataFrame for handoff at '{}': {}", path, error)
                return
        store.put(normalize_key(path), dataframe)
        logger.debug("Registered in-memory handoff for path '{}'", path)
        return

    if _is_pandas_dataframe(dataframe):
        try:
            snapshot = dataframe.copy(deep=True)
        except Exception as error:
            logger.warning("Could not snapshot pandas frame for handoff at '{}': {}", path, error)
            return
        store.put(normalize_key(path), snapshot)
        logger.debug("Registered in-memory pandas handoff for path '{}'", path)


def take(context: Any, path: Any) -> Optional[Any]:
    """Return a cached DataFrame for ``path`` if handoff is enabled and present."""
    if not is_enabled(context):
        return None
    store = get_store(context)
    if store is None:
        return None
    dataframe = store.get(normalize_key(path))
    if dataframe is None:
        return None

    logger.info("Serving input from in-memory handoff (skipped disk read): {}", path)
    if _is_pandas_dataframe(dataframe):
        try:
            return dataframe.copy(deep=True)
        except Exception as error:
            logger.warning(
                "Could not copy cached pandas frame for '{}': {}; falling back to a disk "
                "read so no node can mutate another's input",
                path,
                error,
            )
            return None
    return dataframe


def is_shared(context: Any, dataframe: Any) -> bool:
    """True if ``dataframe`` is a cached handoff frame that other nodes will be served too.

    Whoever holds it must not unpersist it: ``clear`` does that at the end of the run.
    """
    store = ContextManager(context).get(_STORE_KEY) if context is not None else None
    return isinstance(store, _HandoffStore) and store.holds(dataframe)


def clear(context: Any) -> None:
    """Unpersist and drop all handoff frames for a context (call at run teardown)."""
    if context is None:
        return
    store = ContextManager(context).get(_STORE_KEY)
    if isinstance(store, _HandoffStore):
        store.clear()
