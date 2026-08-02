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

import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from loguru import logger  # type: ignore

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl


class ConfigLockError(Exception):
    pass


class ConfigLockManager:
    """Process-level locking for coordinating CLI ↔ API writes to config."""

    def __init__(self, workspace_root: Path, lock_file: str = ".ducta/config.lock"):
        self.workspace_root = Path(workspace_root)
        self.lock_file = self.workspace_root / lock_file
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        self._lock_fd: Optional[int] = None
        self._is_locked = False

    @contextmanager
    def write_lock(self, timeout: float = 5.0):
        self._acquire_lock(timeout=timeout)
        try:
            logger.debug("Lock acquired: {path}", path=self.lock_file)
            yield
        finally:
            try:
                self._release_lock()
                logger.debug("Lock released: {path}", path=self.lock_file)
            except Exception as e:
                logger.error("Error releasing lock: {err}", err=e)

    def _acquire_lock(self, timeout: float = 5.0) -> None:
        if self._is_locked:
            raise ConfigLockError("Lock already acquired")

        try:
            self._lock_fd = os.open(str(self.lock_file), os.O_CREAT | os.O_WRONLY, 0o600)
            if sys.platform == "win32":
                self._acquire_lock_windows(timeout)
            else:
                self._acquire_lock_unix(timeout)
            self._is_locked = True
        except Exception as e:
            if self._lock_fd is not None:
                os.close(self._lock_fd)
                self._lock_fd = None
            raise ConfigLockError(f"Failed to acquire lock: {e}")

    def _acquire_lock_unix(self, timeout: float = 5.0) -> None:
        deadline = time.monotonic() + timeout if timeout > 0 else None
        while True:
            try:
                fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return
            except (IOError, OSError):
                if deadline is not None and time.monotonic() >= deadline:
                    raise TimeoutError(f"Lock acquisition timeout ({timeout}s)")
                time.sleep(0.05)

    def _acquire_lock_windows(self, timeout: float = 5.0) -> None:
        start = time.time()
        while True:
            try:
                msvcrt.locking(self._lock_fd, msvcrt.LK_LOCK, 1)
                break
            except OSError:
                if timeout > 0 and time.time() - start > timeout:
                    raise TimeoutError(f"Lock acquisition timeout ({timeout}s)")
                time.sleep(0.1)

    def _release_lock(self) -> None:
        if not self._is_locked:
            return

        try:
            if sys.platform == "win32" and self._lock_fd is not None:
                try:
                    msvcrt.locking(self._lock_fd, msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            elif self._lock_fd is not None:
                fcntl.flock(self._lock_fd, fcntl.LOCK_UN)

            if self._lock_fd is not None:
                os.close(self._lock_fd)
                self._lock_fd = None
        finally:
            self._is_locked = False

    def is_locked(self) -> bool:
        return self._is_locked

    def acquire_non_blocking(self) -> bool:
        if self._is_locked:
            return False
        try:
            self._lock_fd = os.open(str(self.lock_file), os.O_CREAT | os.O_WRONLY, 0o600)
            if sys.platform == "win32":
                try:
                    msvcrt.locking(self._lock_fd, msvcrt.LK_LOCK, 1)
                except OSError:
                    os.close(self._lock_fd)
                    self._lock_fd = None
                    return False
            else:
                try:
                    fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except (IOError, OSError):
                    os.close(self._lock_fd)
                    self._lock_fd = None
                    return False
            self._is_locked = True
            return True
        except Exception as e:
            logger.error("Failed to acquire non-blocking lock: {err}", err=e)
            if self._lock_fd is not None:
                os.close(self._lock_fd)
                self._lock_fd = None
            return False

    def release_non_blocking(self) -> None:
        if self._is_locked:
            self._release_lock()
