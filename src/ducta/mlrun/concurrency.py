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
import json
import os
import socket
import threading
import time
import weakref
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Optional, Set, Union, cast
from uuid import uuid4

from loguru import logger

from ducta.mlrun.exceptions import LockTimeoutError

if TYPE_CHECKING:
    pass


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
        return cast(LockStats, self._stats)

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

        A lock recorded as held by a process on this host that no longer exists is stale at
        once: waiting out ``STALE_LOCK_THRESHOLD`` after a ``SIGKILL`` made every
        ``end_run``/``register_model`` time out for five minutes. A live owner on this host
        is never robbed, however long it holds the lock. For a lock whose owner's liveness
        cannot be checked (another host, unreadable metadata) age alone decides
        (documented heuristic).
        """
        if not self.lock_file.exists():
            return False

        try:
            age = time.time() - self.lock_file.stat().st_mtime
            metadata = self._read_lock_metadata()
            alive = _lock_owner_is_alive(metadata)

            if alive is True:
                if age > STALE_LOCK_THRESHOLD:
                    logger.debug(
                        "Lock {} is old ({:.1f}s) but its owner (pid {}) is still alive "
                        "on this host; not stealing it",
                        self.lock_file,
                        age,
                        metadata.get("pid") if metadata else None,
                    )
                return False
            if alive is None and age <= STALE_LOCK_THRESHOLD:
                return False

            # Another waiter may have stolen it and a new owner taken it meanwhile.
            now = self._read_lock_metadata()
            if (now or {}).get("token") != (metadata or {}).get("token"):
                return False

            logger.warning(
                f"Detected stale lock {self.lock_file} (age: {age:.1f}s"
                f"{', owner process is gone' if alive is False else ''})"
            )
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
