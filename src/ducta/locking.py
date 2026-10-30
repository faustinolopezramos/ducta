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

Cross-platform advisory locks on an open file: Ducta's one implementation.

The non-blocking pair (:func:`try_lock_fd` / :func:`unlock_fd`) serves the API's
config lock (``ducta.api.core.locks``), the run lock (``ducta.core.run_lock``) and
Sentinel; :func:`exclusive_lock` waits, for the quality history
(``ducta.check.storage``). The OS releases these locks when the holding
process dies, which is what makes them the right primitive for a single host:
a crashed run never leaves a lock behind that someone has to clear by hand.
"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from typing import IO, Any, Iterator

if sys.platform == "win32":
    import msvcrt

    def _msvcrt_at_start(fd: int, mode: int) -> None:
        """``msvcrt.locking`` on byte 0 of ``fd``, leaving its position where it was.

        msvcrt locks a byte range starting at the *current* position, and the lock and
        its unlock must name the same range: pinning both to byte 0 makes them agree
        whatever the caller read or wrote in between.
        """
        position = os.lseek(fd, 0, os.SEEK_CUR)
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            msvcrt.locking(fd, mode, 1)
        finally:
            os.lseek(fd, position, os.SEEK_SET)

else:
    import fcntl


def try_lock_fd(fd: int) -> bool:
    """Take an exclusive lock on ``fd`` without waiting. True if acquired."""
    try:
        if sys.platform == "win32":
            _msvcrt_at_start(fd, msvcrt.LK_NBLCK)
        else:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def unlock_fd(fd: int) -> None:
    """Release a lock taken with :func:`try_lock_fd`. Never raises."""
    try:
        if sys.platform == "win32":
            _msvcrt_at_start(fd, msvcrt.LK_UNLCK)
        else:
            fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass


@contextmanager
def exclusive_lock(f: "IO[Any]") -> Iterator[None]:
    """Hold an exclusive lock on the open file ``f``, waiting until it is free."""
    fd = f.fileno()
    if sys.platform == "win32":
        f.flush()
        _msvcrt_at_start(fd, msvcrt.LK_LOCK)
    else:
        fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        yield
    finally:
        if sys.platform == "win32":
            f.flush()
            _msvcrt_at_start(fd, msvcrt.LK_UNLCK)
        else:
            fcntl.flock(fd, fcntl.LOCK_UN)
