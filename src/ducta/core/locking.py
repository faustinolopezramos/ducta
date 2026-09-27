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

Cross-platform, non-blocking advisory locks on an open file descriptor.

Shared by the API's config lock (``ducta.api.core.locks``) and the run lock
(``ducta.core.run_lock``). The OS releases these locks when the holding
process dies, which is what makes them the right primitive for a single host:
a crashed run never leaves a lock behind that someone has to clear by hand.
"""

from __future__ import annotations

import sys

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl


def try_lock_fd(fd: int) -> bool:
    """Take an exclusive lock on ``fd`` without waiting. True if acquired."""
    try:
        if sys.platform == "win32":
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def unlock_fd(fd: int) -> None:
    """Release a lock taken with :func:`try_lock_fd`. Never raises."""
    try:
        if sys.platform == "win32":
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass
