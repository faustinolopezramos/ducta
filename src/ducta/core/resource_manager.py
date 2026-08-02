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

import atexit
import os
import shutil
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from loguru import logger  # type: ignore


class ResourceType:
    """Resource type constants."""

    CONNECTION = "connection"
    FILE_HANDLE = "file_handle"
    TEMP_FILE = "temp_file"
    TEMP_DIR = "temp_dir"
    SPARK_DF = "spark_dataframe"
    PANDAS_DF = "pandas_dataframe"
    GPU_RESOURCE = "gpu"
    THREAD_POOL = "thread_pool"
    PROCESS_POOL = "process_pool"
    GENERIC = "generic"


class ManagedResource:
    """
    Wrapper for a managed resource with cleanup callback.
    """

    def __init__(
        self,
        resource: Any,
        resource_type: str,
        cleanup_callback: Optional[Callable] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialize managed resource.
        """
        self.resource = resource
        self.resource_type = resource_type
        self.cleanup_callback = cleanup_callback
        self.metadata = metadata or {}
        self.cleaned_up = False
        self._lock = threading.Lock()

    def cleanup(self) -> bool:
        """
        Clean up the resource.
        """
        with self._lock:
            if self.cleaned_up:
                logger.debug(f"Resource already cleaned up: {self.resource_type}")
                return True

            try:
                if self.cleanup_callback:
                    self.cleanup_callback(self.resource)
                else:
                    self._default_cleanup()

                self.cleaned_up = True
                logger.debug(f"Successfully cleaned up {self.resource_type} resource")
                return True

            except Exception as e:
                logger.error(f"Error cleaning up {self.resource_type} resource: {e}")
                return False

    def _default_cleanup(self) -> None:
        """Default cleanup based on resource type."""
        if self.resource_type == ResourceType.CONNECTION:
            self._cleanup_connection()
        elif self.resource_type == ResourceType.FILE_HANDLE:
            self._cleanup_file_handle()
        elif self.resource_type == ResourceType.TEMP_FILE:
            self._cleanup_temp_file()
        elif self.resource_type == ResourceType.TEMP_DIR:
            self._cleanup_temp_dir()
        elif self.resource_type == ResourceType.SPARK_DF:
            self._cleanup_spark_df()
        elif self.resource_type == ResourceType.GPU_RESOURCE:
            self._cleanup_gpu()
        elif self.resource_type in (ResourceType.THREAD_POOL, ResourceType.PROCESS_POOL):
            self._cleanup_executor()

    def _cleanup_connection(self) -> None:
        """Cleanup database connection."""
        if hasattr(self.resource, "close"):
            self.resource.close()
        elif hasattr(self.resource, "disconnect"):
            self.resource.disconnect()

    def _cleanup_file_handle(self) -> None:
        """Cleanup file handle."""
        if hasattr(self.resource, "close"):
            self.resource.close()

    def _cleanup_temp_file(self) -> None:
        """Cleanup temporary file."""
        path = (
            self.resource if isinstance(self.resource, (str, Path)) else self.metadata.get("path")
        )
        if not path:
            return
        try:
            Path(path).unlink(missing_ok=True)
            logger.debug("Deleted temporary file: {}", path)
        except OSError as e:
            logger.warning("Failed to delete temporary file {}: {}", path, e)

    def _cleanup_temp_dir(self) -> None:
        """Cleanup temporary directory."""
        path = (
            self.resource if isinstance(self.resource, (str, Path)) else self.metadata.get("path")
        )
        if not path:
            return
        try:
            shutil.rmtree(path, ignore_errors=True)
            logger.debug("Deleted temporary directory: {}", path)
        except OSError as e:
            logger.warning("Failed to delete temporary directory {}: {}", path, e)

    def _cleanup_spark_df(self) -> None:
        """Cleanup Spark DataFrame."""
        if hasattr(self.resource, "unpersist"):
            try:
                self.resource.unpersist()
            except Exception:
                pass

    def _cleanup_gpu(self) -> None:
        """Cleanup GPU resources."""
        if hasattr(self.resource, "reset"):
            self.resource.reset()
        elif hasattr(self.resource, "clear"):
            self.resource.clear()

    def _cleanup_executor(self) -> None:
        """Cleanup thread/process pool executor."""
        if hasattr(self.resource, "shutdown"):
            self.resource.shutdown(wait=True)


class ResourceManager:
    """
    Central resource manager for tracking and cleanup of all resources.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._resources: Dict[str, List[ManagedResource]] = {}
        self._global_resources: List[ManagedResource] = []
        self._lock = threading.RLock()
        self._temp_dirs: Set[Path] = set()
        self._cleanup_registered = False
        self._initialized = True

        self._register_exit_cleanup()

    def _register_exit_cleanup(self) -> None:
        """Register cleanup to run on program exit."""
        if not self._cleanup_registered:
            atexit.register(self.cleanup_all)
            self._cleanup_registered = True
            logger.debug("Registered resource cleanup on exit")

    @contextmanager
    def resource_context(self, context_id: str):
        """
        Context manager for resource scoping.
        """
        try:
            yield self
        finally:
            self.cleanup_context(context_id)

    def node_context(self, node_id: str):
        """Context manager scoped to a single node lifecycle. Alias for resource_context."""
        return self.resource_context(node_id)

    def register_resource(
        self,
        node_id: str,
        resource: Any,
        resource_type: str,
        cleanup_fn: Optional[Callable] = None,
    ) -> str:
        """Register a node-scoped resource and return an opaque resource identifier.

        Appends and computes the index in one critical section (unlike calling
        ``register()`` and then separately re-locking to read the list length),
        so a concurrent registration for the same ``node_id`` in between can't
        make the returned identifier point at the wrong slot.
        """
        managed = ManagedResource(resource, resource_type, cleanup_fn)
        with self._lock:
            bucket = self._resources.setdefault(node_id, [])
            bucket.append(managed)
            idx = len(bucket) - 1
        logger.debug(f"Registered {resource_type} resource for context '{node_id}'")
        return f"{node_id}_{idx}"

    def register(
        self,
        resource: Any,
        resource_type: str,
        context_id: Optional[str] = None,
        cleanup_callback: Optional[Callable] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ManagedResource:
        """
        Register a resource for managed cleanup.
        """
        managed = ManagedResource(resource, resource_type, cleanup_callback, metadata)

        with self._lock:
            if context_id:
                if context_id not in self._resources:
                    self._resources[context_id] = []
                self._resources[context_id].append(managed)
                logger.debug(f"Registered {resource_type} resource for context '{context_id}'")
            else:
                self._global_resources.append(managed)
                logger.debug(f"Registered global {resource_type} resource")

        return managed

    def cleanup_context(self, context_id: str) -> None:
        """
        Clean up all resources for a specific context.

        The resource list is popped under the lock, then each (potentially
        slow — DB connection close, Spark unpersist, arbitrary user
        callback) cleanup runs *outside* it. Executor.py runs nodes
        concurrently in a thread pool, all sharing this one process-wide
        manager; holding the lock across every callback would serialize
        registration and cleanup for every other concurrently-running node
        behind whichever one's cleanup happens to be slow.
        """
        with self._lock:
            resources = self._resources.pop(context_id, None)

        if not resources:
            return

        logger.info(f"Cleaning up {len(resources)} resources for context '{context_id}'")

        for managed in reversed(resources):
            try:
                if not managed.cleanup():
                    logger.error(
                        f"Cleanup failed for {managed.resource_type} resource in "
                        f"context '{context_id}'; it may be leaked (no retry)."
                    )
            except Exception as e:
                logger.error(f"Error during cleanup of {managed.resource_type}: {e}")

        logger.debug(f"Context '{context_id}' cleaned up")

    def cleanup_all(self) -> None:
        """Clean up all managed resources."""
        with self._lock:
            total_resources = sum(len(r) for r in self._resources.values()) + len(
                self._global_resources
            )

            if total_resources == 0:
                return

            logger.info(f"Cleaning up {total_resources} total resources")

            for context_id in tuple(self._resources.keys()):
                self.cleanup_context(context_id)

            for managed in reversed(self._global_resources):
                try:
                    managed.cleanup()
                except Exception as e:
                    logger.error(f"Error during cleanup of global {managed.resource_type}: {e}")

            self._global_resources.clear()
            logger.info("All resources cleaned up")

    def create_temp_file(
        self,
        context_id: Optional[str] = None,
        suffix: str = "",
        prefix: str = "Ducta_",
        dir: Optional[str] = None,
    ) -> Path:
        """
        Create a managed temporary file.
        """
        fd, path = tempfile.mkstemp(suffix=suffix, prefix=prefix, dir=dir)
        os.close(fd)

        temp_path = Path(path)
        self.register(
            temp_path,
            ResourceType.TEMP_FILE,
            context_id,
            metadata={"path": str(temp_path)},
        )

        logger.debug(f"Created managed temporary file: {temp_path}")
        return temp_path

    def create_temp_dir(
        self,
        context_id: Optional[str] = None,
        suffix: str = "",
        prefix: str = "Ducta_",
        dir: Optional[str] = None,
    ) -> Path:
        """
        Create a managed temporary directory.
        """
        path = tempfile.mkdtemp(suffix=suffix, prefix=prefix, dir=dir)
        temp_path = Path(path)

        self.register(
            temp_path,
            ResourceType.TEMP_DIR,
            context_id,
            metadata={"path": str(temp_path)},
        )

        with self._lock:
            self._temp_dirs.add(temp_path)

        logger.debug(f"Created managed temporary directory: {temp_path}")
        return temp_path

    def detect_resource_type(self, resource: Any) -> str:
        """Detect the type of resource for proper cleanup."""
        if hasattr(resource, "unpersist") and hasattr(resource, "rdd"):
            return ResourceType.SPARK_DF

        if hasattr(resource, "columns") and hasattr(resource, "empty"):
            return ResourceType.PANDAS_DF

        if hasattr(resource, "device") and hasattr(resource, "reset"):
            return ResourceType.GPU_RESOURCE

        if hasattr(resource, "cursor") or hasattr(resource, "execute"):
            return ResourceType.CONNECTION

        if hasattr(resource, "read") and hasattr(resource, "close"):
            return ResourceType.FILE_HANDLE

        if isinstance(resource, (str, Path)):
            import os

            if os.path.exists(str(resource)):
                return ResourceType.TEMP_FILE

        return ResourceType.GENERIC

    def get_resource_count(self, context_id: Optional[str] = None) -> int:
        """
        Get count of managed resources.
        """
        with self._lock:
            if context_id:
                return len(self._resources.get(context_id, []))
            else:
                return sum(len(r) for r in self._resources.values()) + len(self._global_resources)

    def get_stats(self) -> Dict[str, Any]:
        """
        Get resource management statistics.
        """
        with self._lock:
            context_counts = {ctx: len(res) for ctx, res in self._resources.items()}
            type_counts: Dict[str, int] = {}

            for resources in self._resources.values():
                for managed in resources:
                    rtype = managed.resource_type
                    type_counts[rtype] = type_counts.get(rtype, 0) + 1

            for managed in self._global_resources:
                rtype = managed.resource_type
                type_counts[rtype] = type_counts.get(rtype, 0) + 1

            return {
                "total_resources": self.get_resource_count(),
                "global_resources": len(self._global_resources),
                "contexts": len(self._resources),
                "context_counts": context_counts,
                "by_type": type_counts,
                "temp_directories": len(self._temp_dirs),
            }


def get_resource_manager() -> ResourceManager:
    """Get the global ResourceManager instance."""
    return ResourceManager()
