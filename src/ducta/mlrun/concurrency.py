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
import functools
import hashlib
import json
import os
import shutil
import socket
import tempfile
import threading
import time
import weakref
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Union
from uuid import uuid4

from loguru import logger

from ducta.mlrun.exceptions import ConcurrencyError, ErrorCode, LockTimeoutError, MLOpsException

if TYPE_CHECKING:
    import pandas as pd


DEFAULT_LOCK_TIMEOUT = 30.0
DEFAULT_CHECK_INTERVAL = 0.1
STALE_LOCK_THRESHOLD = 300.0  # 5 minutes


def _read_lock_file_metadata(lock_file: Path) -> Optional[dict]:
    """Best-effort read of a lock file's own JSON metadata (pid/host/token)."""
    try:
        raw = lock_file.read_text(encoding="utf-8")
        return json.loads(raw) if raw else None
    except Exception:
        return None


def _lock_owner_is_alive(metadata: Optional[dict]) -> Optional[bool]:
    """True/False if liveness could be determined (same host); None otherwise
    (different host, or metadata unreadable/incomplete) — callers fall back to
    the age-based heuristic alone in that case."""
    if not metadata:
        return None
    host = metadata.get("host")
    pid = metadata.get("pid")
    if host != socket.gethostname() or not isinstance(pid, int):
        return None
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but is owned by another user — treat as alive.
        return True
    except OSError:
        return None


@dataclass
class LockStats:
    """Statistics for lock operations."""

    acquisitions: int = 0
    releases: int = 0
    timeouts: int = 0
    stale_cleanups: int = 0
    total_wait_time: float = 0.0

    def record_acquisition(self, wait_time: float) -> None:
        """Record a successful acquisition."""
        self.acquisitions += 1
        self.total_wait_time += wait_time

    def record_timeout(self) -> None:
        """Record a timeout."""
        self.timeouts += 1

    def record_release(self) -> None:
        """Record a release."""
        self.releases += 1

    def record_stale_cleanup(self) -> None:
        """Record a stale lock cleanup."""
        self.stale_cleanups += 1

    @property
    def average_wait_time(self) -> float:
        """Average wait time for acquisitions."""
        if self.acquisitions == 0:
            return 0.0
        return self.total_wait_time / self.acquisitions


class LockManager:
    """
    Global lock manager for tracking and cleanup of all active locks.
    """

    _instance: Optional["LockManager"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "LockManager":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        with self.__class__._lock:
            if self._initialized:
                return

            self._active_locks: Dict[str, weakref.ref] = {}
            self._lock_files: Set[Path] = set()
            self._stats = LockStats()
            self._thread_lock = threading.RLock()
            self._initialized = True

            atexit.register(self._cleanup_all)
            logger.debug("LockManager initialized")

    def register(self, lock: "FileLock") -> None:
        """Register a lock for tracking."""
        with self._thread_lock:
            key = str(lock.lock_file)
            self._active_locks[key] = weakref.ref(lock)
            self._lock_files.add(lock.lock_file)

    def unregister(self, lock: "FileLock") -> None:
        """Unregister a lock."""
        with self._thread_lock:
            key = str(lock.lock_file)
            self._active_locks.pop(key, None)
            self._lock_files.discard(lock.lock_file)

    @property
    def stats(self) -> LockStats:
        """Get lock statistics."""
        return self._stats

    def cleanup_stale_locks(self, threshold: float = STALE_LOCK_THRESHOLD) -> int:
        """
        Clean up stale lock files.

        Returns:
            Number of stale locks cleaned up
        """
        cleaned = 0
        current_time = time.time()

        with self._thread_lock:
            stale_files = []

            for lock_file in self._lock_files:
                try:
                    if lock_file.exists():
                        mtime = lock_file.stat().st_mtime
                        if current_time - mtime > threshold:
                            metadata = _read_lock_file_metadata(lock_file)
                            if _lock_owner_is_alive(metadata) is True:
                                continue  # still held by a live process on this host
                            stale_files.append(lock_file)
                except OSError:
                    continue

            for lock_file in stale_files:
                try:
                    lock_file.unlink(missing_ok=True)
                    self._lock_files.discard(lock_file)
                    self._stats.record_stale_cleanup()
                    cleaned += 1
                    logger.warning(f"Cleaned up stale lock: {lock_file}")
                except OSError as e:
                    logger.warning(f"Failed to clean stale lock {lock_file}: {e}")

        return cleaned

    def _cleanup_all(self) -> None:
        """Clean up all active locks on process exit."""
        with self._thread_lock:
            # Snapshot both collections before iterating: lock.release() calls
            # unregister(), which pops/discards from _active_locks and
            # _lock_files. Iterating the live collections would raise
            # "dictionary changed size during iteration" (seen at interpreter
            # shutdown when a lock is still held).
            for key, lock_ref in list(self._active_locks.items()):
                lock = lock_ref()
                if lock is not None:
                    try:
                        lock.release()
                    except Exception as e:
                        logger.warning(f"Error releasing lock {key} on exit: {e}")

            for lock_file in list(self._lock_files):
                try:
                    lock_file.unlink(missing_ok=True)
                except OSError:
                    pass

            self._active_locks.clear()
            self._lock_files.clear()

    def get_active_lock_count(self) -> int:
        """Get count of active locks."""
        with self._thread_lock:
            self._active_locks = {k: v for k, v in self._active_locks.items() if v() is not None}
            return len(self._active_locks)


def get_lock_manager() -> LockManager:
    """Get the global lock manager instance."""
    return LockManager()


class FileLock:
    """
    Cross-platform file locking mechanism with automatic cleanup.
    """

    def __init__(
        self,
        lock_file: Union[str, Path],
        timeout: float = DEFAULT_LOCK_TIMEOUT,
        check_interval: float = DEFAULT_CHECK_INTERVAL,
        auto_cleanup_stale: bool = True,
        base_path: Optional[Union[str, Path]] = None,
    ):
        """
        Initialize file-based lock.

        Args:
            lock_file: Path to the lock file.
            timeout: Maximum time to wait for the lock.
            check_interval: Interval between lock acquisition attempts.
            auto_cleanup_stale: Whether to automatically remove stale locks.
            base_path: Optional base path to resolve relative lock_file paths.
        """
        self.lock_file = Path(lock_file)
        if base_path and not self.lock_file.is_absolute():
            self.lock_file = Path(base_path) / self.lock_file

        self.timeout = timeout
        self.check_interval = check_interval
        self.auto_cleanup_stale = auto_cleanup_stale
        self.lock_fd: Optional[int] = None
        self._acquired = False
        self._acquisition_time: Optional[float] = None
        self._token: Optional[str] = None
        self._thread_lock = threading.Lock()
        self._manager = get_lock_manager()

    def _read_lock_metadata(self) -> Optional[dict]:
        """Best-effort read of this lock file's own JSON metadata (pid/host/token)."""
        return _read_lock_file_metadata(self.lock_file)

    def _check_stale_lock(self) -> bool:
        """Check if existing lock file is stale and clean it up.

        Staleness is decided by age (``STALE_LOCK_THRESHOLD``); a lock recorded
        as held by a still-alive process on this same host is never stolen just
        because it has been held a long time — only age *and* a dead/undeterminable
        owner steal the lock. For a lock held by a process on a different host,
        liveness cannot be checked, so age alone is used (documented heuristic).
        """
        if not self.lock_file.exists():
            return False

        try:
            mtime = self.lock_file.stat().st_mtime
            age = time.time() - mtime

            if age <= STALE_LOCK_THRESHOLD:
                return False

            metadata = self._read_lock_metadata()
            if _lock_owner_is_alive(metadata) is True:
                logger.debug(
                    "Lock {} is old ({:.1f}s) but its owner (pid {}) is still alive "
                    "on this host; not stealing it",
                    self.lock_file,
                    age,
                    metadata.get("pid") if metadata else None,
                )
                return False

            logger.warning(f"Detected stale lock {self.lock_file} (age: {age:.1f}s)")
            self.lock_file.unlink(missing_ok=True)
            self._manager.stats.record_stale_cleanup()
            return True
        except OSError:
            pass

        return False

    def _create_lock_file(self):
        return os.open(str(self.lock_file), os.O_CREAT | os.O_EXCL | os.O_RDWR)

    def _should_timeout(self, start_time: float) -> bool:
        return (time.time() - start_time) >= self.timeout

    def _maybe_cleanup_stale(self, elapsed: float) -> bool:
        # Trigger every ~5 seconds; use a window of check_interval width to avoid
        # floating-point phase issues (int truncation could skip the exact multiple).
        if self.auto_cleanup_stale and elapsed > 5 and (elapsed % 5) < self.check_interval:
            return self._check_stale_lock()
        return False

    def _write_lock_metadata(self, fd: int) -> None:
        try:
            self._token = uuid4().hex
            metadata = json.dumps(
                {
                    "pid": os.getpid(),
                    "host": socket.gethostname(),
                    "acquired_at": time.time(),
                    "token": self._token,
                }
            )
            os.write(fd, metadata.encode("utf-8"))
            self.lock_fd = fd
        except Exception:
            try:
                os.close(fd)
            except Exception:
                pass
            raise

    def _handle_lock_exists(self, start_time: float) -> bool:
        elapsed = time.time() - start_time

        if self._should_timeout(start_time):
            self._manager.stats.record_timeout()
            logger.warning(f"Could not acquire lock {self.lock_file} after {self.timeout} seconds")
            return False

        if self._maybe_cleanup_stale(elapsed):
            return True

        time.sleep(self.check_interval)
        return True

    def _finalize_acquisition(self, start_time: float) -> None:
        self._acquired = True
        self._acquisition_time = time.time()
        wait_time = self._acquisition_time - start_time

        self._manager.register(self)
        self._manager.stats.record_acquisition(wait_time)

        logger.debug(f"Lock acquired: {self.lock_file} (wait: {wait_time:.3f}s)")

    def acquire(self) -> bool:
        """Acquire the lock with timeout."""
        with self._thread_lock:
            if self._acquired:
                logger.warning(f"Lock already acquired: {self.lock_file}")
                return True

            start_time = time.time()
            self.lock_file.parent.mkdir(parents=True, exist_ok=True)

            if self.auto_cleanup_stale:
                self._check_stale_lock()

            while True:
                try:
                    fd = self._create_lock_file()
                    self._write_lock_metadata(fd)
                    self._finalize_acquisition(start_time)
                    return True
                except FileExistsError:
                    if not self._handle_lock_exists(start_time):
                        return False
                except Exception as e:
                    logger.error(f"Error acquiring lock {self.lock_file}: {e}")
                    raise

    def release(self) -> None:
        """Release the lock.

        Only removes the lock file if it still carries the token this instance
        wrote on acquisition. If a stale-lock sweep reclaimed it while we still
        held it (a long-running critical section past ``STALE_LOCK_THRESHOLD``),
        the file on disk now belongs to a different holder — unlinking it
        unconditionally would delete *their* lock, letting a third acquirer in
        while the second believes it still holds exclusive access.
        """
        with self._thread_lock:
            if not self._acquired and self.lock_fd is None:
                return

            try:
                if self.lock_fd is not None:
                    os.close(self.lock_fd)

                current = self._read_lock_metadata()
                reclaimed = (
                    current is not None
                    and current.get("token") is not None
                    and current.get("token") != self._token
                )
                if reclaimed:
                    logger.warning(
                        "Lock {} was reclaimed as stale while held (token mismatch); "
                        "not deleting the new owner's lock file",
                        self.lock_file,
                    )
                else:
                    self.lock_file.unlink(missing_ok=True)

                self._manager.unregister(self)
                self._manager.stats.record_release()

                if self._acquisition_time is not None:
                    hold_time = time.time() - self._acquisition_time
                    logger.debug(f"Lock released: {self.lock_file} (held: {hold_time:.3f}s)")
                else:
                    logger.debug(f"Lock released: {self.lock_file}")
            except Exception as e:
                logger.warning(f"Error releasing lock {self.lock_file}: {e}")
            finally:
                self.lock_fd = None
                self._acquired = False
                self._acquisition_time = None
                self._token = None

    @property
    def is_acquired(self) -> bool:
        """Check if lock is currently acquired."""
        return self._acquired

    @property
    def hold_time(self) -> Optional[float]:
        """Get time lock has been held, or None if not acquired."""
        if self._acquisition_time is None:
            return None
        return time.time() - self._acquisition_time

    def __enter__(self):
        acquired = self.acquire()
        if not acquired:
            raise LockTimeoutError(str(self.lock_file), self.timeout)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()
        return False

    def __del__(self):
        try:
            self.release()
        except Exception:
            pass


@contextmanager
def file_lock(
    lock_file: Union[str, Path],
    timeout: float = DEFAULT_LOCK_TIMEOUT,
    auto_cleanup_stale: bool = True,
    base_path: Optional[Union[str, Path]] = None,
):
    """
    Context manager for file locking.

    Args:
        lock_file: Path to the lock file.
        timeout: Maximum time to wait for the lock.
        auto_cleanup_stale: Whether to automatically remove stale locks.
        base_path: Optional base path to resolve relative lock_file paths.
    """
    lock = FileLock(
        lock_file,
        timeout=timeout,
        auto_cleanup_stale=auto_cleanup_stale,
        base_path=base_path,
    )
    try:
        acquired = lock.acquire()
        if not acquired:
            raise LockTimeoutError(str(lock_file), timeout)
        yield lock
    finally:
        lock.release()


class OptimisticLock:
    """
    Optimistic locking using version counters or checksum verification.
    """

    def __init__(self, initial_version: int = 1):
        """Initialize optimistic lock with version counter."""
        self._version = initial_version
        self._lock = threading.Lock()

    @property
    def version(self) -> int:
        """Get current version."""
        with self._lock:
            return self._version

    @version.setter
    def version(self, value: int) -> None:
        """Set version."""
        with self._lock:
            self._version = value

    def check_version(self, expected_version: int) -> None:
        """
        Check if current version matches expected.
        """
        with self._lock:
            if self._version != expected_version:
                error = ConcurrencyError(resource="optimistic_lock", operation="check_version")
                error.with_context(expected_version=expected_version, actual_version=self._version)
                raise error

    def increment_version(self) -> int:
        """
        Atomically increment version and return new value.
        """
        with self._lock:
            self._version += 1
            return self._version

    def __str__(self) -> str:
        return f"OptimisticLock(version={self._version})"

    def __repr__(self) -> str:
        return self.__str__()

    # Static methods for checksum-based optimistic locking

    @staticmethod
    def compute_checksum(data: bytes) -> str:
        """Compute SHA-256 checksum for data."""
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def verify_no_changes(file_path: Path, original_checksum: str) -> bool:
        """Verify file hasn't changed since checksum was computed."""
        if not file_path.exists():
            return False

        try:
            current_data = file_path.read_bytes()
            current_checksum = OptimisticLock.compute_checksum(current_data)
            return current_checksum == original_checksum
        except OSError:
            return False

    @staticmethod
    def read_with_checksum(file_path: Path) -> tuple[bytes, str]:
        """
        Read file and compute checksum atomically.

        Returns:
            Tuple of (file_data, checksum)
        """
        data = file_path.read_bytes()
        checksum = OptimisticLock.compute_checksum(data)
        return data, checksum


class ReadWriteLock:
    """
    A readers-writer lock allowing concurrent reads but exclusive writes.
    """

    def __init__(self):
        self._read_count = 0
        self._write_waiting = 0
        self._lock = threading.Lock()
        self._read_lock = threading.Condition(self._lock)
        self._write_lock = threading.Condition(self._lock)
        self._writing = False

    @contextmanager
    def read_lock(self):
        """Acquire read lock."""
        with self._lock:
            while self._writing or self._write_waiting > 0:
                self._read_lock.wait()
            self._read_count += 1

        try:
            yield
        finally:
            with self._lock:
                self._read_count -= 1
                if self._read_count == 0:
                    self._write_lock.notify()

    @contextmanager
    def write_lock(self):
        """Acquire write lock."""
        with self._lock:
            self._write_waiting += 1
            try:
                while self._writing or self._read_count > 0:
                    self._write_lock.wait()
                self._writing = True
            finally:
                self._write_waiting -= 1

        try:
            yield
        finally:
            with self._lock:
                self._writing = False
                self._read_lock.notify_all()
                self._write_lock.notify()


class TransactionState(Enum):
    """Transaction execution state."""

    PENDING = "pending"
    ACTIVE = "active"
    COMMITTED = "committed"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"


class TransactionError(MLOpsException):
    """Transaction operation failed.

    Inherits MLOpsException (in addition to the plain Exception it always
    was) so code that catches MLOpsException to handle "any Ducta error"
    uniformly doesn't silently miss transaction failures.
    """

    error_code = ErrorCode.OPERATION_FAILED

    def __init__(self, message: str, **kwargs):
        super().__init__(message=message, **kwargs)


class RollbackError(TransactionError):
    """Rollback operation failed."""

    pass


@dataclass
class Operation:
    """Single transaction operation."""

    operation_type: str  # "write_json", "write_dataframe", "write_artifact", "delete"
    path: str
    data: Any = None
    mode: str = "overwrite"

    def __hash__(self):
        return hash(self.path)


class Transaction:
    """
    Atomic transaction for multiple storage operations.
    """

    def __init__(
        self,
        storage: Any,  # StorageBackend
        lock_path: str,
        timeout: float = 30.0,
        temp_dir: Optional[str] = None,
    ):
        self.storage = storage
        self.lock_path = lock_path
        self.timeout = timeout
        self.temp_dir = temp_dir or tempfile.gettempdir()

        self.operations: List[Operation] = []
        self.executed = False
        self.state = TransactionState.PENDING
        self._staging_dir: Optional[Path] = None

    def write_json(self, data: Dict[str, Any], path: str, mode: str = "overwrite") -> "Transaction":
        """Queue JSON write operation."""
        self.operations.append(
            Operation(operation_type="write_json", path=path, data=data, mode=mode)
        )
        return self

    def write_dataframe(
        self,
        df: "pd.DataFrame",
        path: str,
        mode: str = "overwrite",
    ) -> "Transaction":
        """Queue DataFrame write operation."""
        self.operations.append(
            Operation(operation_type="write_dataframe", path=path, data=df, mode=mode)
        )
        return self

    def write_artifact(
        self, artifact_path: str, destination: str, mode: str = "overwrite"
    ) -> "Transaction":
        """Queue artifact write operation."""
        self.operations.append(
            Operation(
                operation_type="write_artifact", path=destination, data=artifact_path, mode=mode
            )
        )
        return self

    def delete(self, path: str) -> "Transaction":
        """Queue delete operation."""
        self.operations.append(Operation(operation_type="delete", path=path))
        return self

    def execute(self) -> bool:
        """Execute all operations atomically under lock."""
        logger.debug(f"Executing transaction with {len(self.operations)} operations")

        try:
            with file_lock(
                self.lock_path,
                timeout=self.timeout,
                base_path=getattr(self.storage, "base_path", None),
            ):
                if self.executed:
                    raise TransactionError("Transaction already executed")

                if not self.operations:
                    logger.debug("Transaction has no operations, skipping")
                    return False

                self.state = TransactionState.ACTIVE

                for i, operation in enumerate(self.operations):
                    try:
                        self._execute_operation(operation)
                    except Exception as e:
                        raise TransactionError(
                            f"Operation {i} ({operation.operation_type} at '{operation.path}') failed: {e}"
                        )

                self.executed = True
                self.state = TransactionState.COMMITTED
                logger.info(f"Transaction committed with {len(self.operations)} operations")
                return True

        except Exception as e:
            # Operations before the failing one may already have been applied
            # (this is a partial failure, not a no-op) — FAILED, not PENDING,
            # so SafeTransaction.rollback() knows there may be state to undo.
            self.state = TransactionState.FAILED
            logger.error(f"Transaction failed: {e}")
            raise

    def _execute_operation(self, operation: Operation) -> None:
        """Execute a single operation."""
        if operation.operation_type == "write_json":
            self.storage.write_json(operation.data, operation.path, mode=operation.mode)
        elif operation.operation_type == "write_dataframe":
            self.storage.write_dataframe(operation.data, operation.path, mode=operation.mode)
        elif operation.operation_type == "write_artifact":
            self.storage.write_artifact(operation.data, operation.path, mode=operation.mode)
        elif operation.operation_type == "delete":
            self.storage.delete(operation.path)
        else:
            raise ValueError(f"Unknown operation type: {operation.operation_type}")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self.execute()
        else:
            logger.warning("Transaction context exited with exception, not executing")
        return False


# =============================================================================
# Safe Transaction with Rollback
# =============================================================================


class SafeTransaction(Transaction):
    """
    Enhanced transaction with automatic rollback capability.
    """

    # Sentinel recorded in `_original_values` for write_dataframe/write_json/
    # write_artifact operations whose path did not exist before the
    # transaction — distinct from "we don't know" (any other snapshot
    # failure), so rollback can delete the newly-created path instead of
    # silently doing nothing.
    _NOT_EXISTED = object()

    # Sentinel recorded when a pre-existing artifact could not be backed up
    # (e.g. read_artifact raised). This must NOT be conflated with
    # _NOT_EXISTED: the artifact did exist, we just don't have a copy of it,
    # so rollback must refuse to touch it rather than delete real data.
    _SNAPSHOT_FAILED = object()

    def __init__(
        self,
        storage: Any,
        lock_path: str,
        timeout: float = 30.0,
        enable_staging: bool = True,
    ):
        super().__init__(storage, lock_path, timeout)
        self.enable_staging = enable_staging
        self._original_values: Dict[str, Any] = {}

    def _snapshot_operations(self) -> None:
        """Snapshot pre-transaction state for each operation (used for rollback)."""
        if self.enable_staging and not self._staging_dir:
            self._staging_dir = Path(tempfile.mkdtemp(prefix="mlops_txn_staging_"))

        for operation in self.operations:
            try:
                if operation.operation_type == "write_dataframe":
                    try:
                        self._original_values[operation.path] = self.storage.read_dataframe(
                            operation.path
                        )
                    except FileNotFoundError:
                        self._original_values[operation.path] = self._NOT_EXISTED
                elif operation.operation_type == "write_json":
                    try:
                        self._original_values[operation.path] = self.storage.read_json(
                            operation.path
                        )
                    except FileNotFoundError:
                        self._original_values[operation.path] = self._NOT_EXISTED
                elif operation.operation_type == "write_artifact":
                    # Improved v2.2: Backup existing artifacts for full rollback support
                    if self.storage.exists(operation.path):
                        try:
                            # Use staging dir to backup original artifact
                            backup_name = hashlib.md5(operation.path.encode()).hexdigest()
                            backup_path = self._staging_dir / backup_name
                            self.storage.read_artifact(operation.path, str(backup_path))
                            self._original_values[operation.path] = {
                                "_existed": True,
                                "_backup_path": str(backup_path),
                            }
                        except Exception as e:
                            # It existed but we couldn't back it up — record
                            # this explicitly so rollback refuses to delete
                            # it (see _rollback_single_operation).
                            self._original_values[operation.path] = self._SNAPSHOT_FAILED
                            logger.error(
                                f"Could not back up existing artifact at {operation.path}, "
                                f"rollback will not be able to restore it: {e}"
                            )
                    else:
                        self._original_values[operation.path] = self._NOT_EXISTED
            except Exception as e:
                logger.debug(f"Could not snapshot {operation.path}: {e}")

    def execute(self) -> bool:
        """Execute with enhanced safety and staging."""
        if self.executed:
            raise TransactionError("Transaction already executed")

        if not self.operations:
            logger.debug("Safe transaction has no operations, skipping")
            return False

        if self.enable_staging:
            logger.debug("Safe transaction enabled with staging")
            self._snapshot_operations()

        try:
            result = super().execute()

            # Clean up staging on success
            if result and self._staging_dir and self._staging_dir.exists():
                shutil.rmtree(self._staging_dir)
                self._staging_dir = None

            return result
        except Exception:
            # Staging dir remains for potential rollback
            raise

    def _rollback_single_operation(self, operation) -> bool:
        """
        Attempt to rollback a single operation.
        Returns True if state was restored, False otherwise.
        """
        try:
            if operation.operation_type == "write_dataframe":
                if operation.path in self._original_values:
                    orig = self._original_values[operation.path]
                    if orig is self._NOT_EXISTED:
                        if self.storage.exists(operation.path):
                            self.storage.delete(operation.path)
                        return True
                    self.storage.write_dataframe(orig, operation.path, mode="overwrite")
                    return True
            elif operation.operation_type == "write_json":
                if operation.path in self._original_values:
                    orig = self._original_values[operation.path]
                    if orig is self._NOT_EXISTED:
                        if self.storage.exists(operation.path):
                            self.storage.delete(operation.path)
                        return True
                    self.storage.write_json(orig, operation.path, mode="overwrite")
                    return True
            elif operation.operation_type == "write_artifact":
                orig = self._original_values.get(operation.path)
                if orig is self._SNAPSHOT_FAILED:
                    # We know an artifact existed here but never captured a
                    # usable backup — restoring or deleting would be a guess.
                    logger.error(
                        f"Refusing to rollback {operation.path}: the pre-transaction "
                        "artifact could not be backed up during snapshot, so its "
                        "original state is unknown."
                    )
                    return False
                if orig is None or orig is self._NOT_EXISTED:
                    # Created during transaction, delete it
                    if self.storage.exists(operation.path):
                        self.storage.delete(operation.path)
                        return True
                elif "_backup_path" in orig:
                    # Restore from backup
                    self.storage.write_artifact(
                        orig["_backup_path"], operation.path, mode="overwrite"
                    )
                    return True
        except Exception as e:
            logger.error(f"Failed to rollback at {operation.path}: {e}")
        return False

    def rollback(self) -> bool:
        """
        Attempt to rollback to original state.

        Restores DataFrame, JSON and Artifact writes to their pre-transaction values.

        Can be called both after a successful commit (state COMMITTED) and
        after an execution that failed partway through (state FAILED) —
        `_snapshot_operations` runs before `super().execute()`, so the
        pre-transaction state is already captured in either case.
        """
        if self.state not in (TransactionState.COMMITTED, TransactionState.FAILED):
            logger.warning(f"Cannot rollback transaction in state '{self.state.value}'")
            return False

        logger.warning("Attempting to rollback transaction")
        rollback_count = sum(1 for op in self.operations if self._rollback_single_operation(op))

        # Cleanup staging after rollback attempt
        if self._staging_dir and self._staging_dir.exists():
            try:
                shutil.rmtree(self._staging_dir)
                self._staging_dir = None
            except Exception as e:
                logger.warning(f"Failed to cleanup staging dir after rollback: {e}")

        self.state = TransactionState.ROLLED_BACK

        if rollback_count > 0:
            logger.info(f"Rolled back {rollback_count} operations")
            return True

        logger.warning("Rollback did not restore any files")
        return False


def transactional_operation(storage: Any, lock_path: str, timeout: float = 30.0):
    """
    Decorator for transactional operations.
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            txn = Transaction(storage, lock_path, timeout)
            result = func(*args, txn=txn, **kwargs)
            if not txn.executed:
                txn.execute()
            return result

        return wrapper

    return decorator
