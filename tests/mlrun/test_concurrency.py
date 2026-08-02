"""Unit tests for ducta.mlrun.concurrency.FileLock (cross-platform advisory lock)."""

from __future__ import annotations

import json
import os
import socket
import time

from ducta.mlrun.concurrency import FileLock, file_lock, get_lock_manager


def _find_unused_pid() -> int:
    """A pid guaranteed not to correspond to a live process, for stale-lock tests."""
    candidate = 2**30
    while True:
        try:
            os.kill(candidate, 0)
        except ProcessLookupError:
            return candidate
        except PermissionError:
            candidate += 1
        else:
            candidate += 1


class TestFileLock:
    def test_acquire_and_release(self, tmp_path):
        lock = FileLock(tmp_path / "x.lock")
        assert lock.acquire() is True
        assert lock.is_acquired is True
        lock.release()
        assert lock.is_acquired is False

    def test_mutual_exclusion(self, tmp_path):
        p = tmp_path / "x.lock"
        first = FileLock(p)
        assert first.acquire() is True
        # A second lock on the same fresh (non-stale) file cannot acquire.
        second = FileLock(p, timeout=0.2, auto_cleanup_stale=False)
        assert second.acquire() is False
        first.release()
        # Now it is free.
        assert second.acquire() is True
        second.release()

    def test_lock_file_removed_after_release(self, tmp_path):
        p = tmp_path / "x.lock"
        lock = FileLock(p)
        lock.acquire()
        lock.release()
        assert not p.exists()


class TestFileLockContextManager:
    def test_context_manager_acquires_and_releases(self, tmp_path):
        p = tmp_path / "cm.lock"
        with file_lock(p) as lock:
            assert lock.is_acquired is True
        assert not p.exists()


class TestStaleLockLivenessCheck:
    def test_stale_by_age_but_alive_owner_is_not_stolen(self, tmp_path):
        p = tmp_path / "x.lock"
        holder = FileLock(p)
        assert holder.acquire() is True
        # Force the lock file to look old enough to be considered stale by age
        # alone (the holder's own pid — this test process — is very much alive).
        old_time = time.time() - 1000
        os.utime(p, (old_time, old_time))

        thief = FileLock(p, timeout=0.2, auto_cleanup_stale=True)
        assert thief.acquire() is False
        assert p.exists()
        holder.release()

    def test_stale_by_age_and_dead_owner_is_stolen(self, tmp_path):
        p = tmp_path / "x.lock"
        dead_pid = _find_unused_pid()
        p.write_text(
            json.dumps(
                {
                    "pid": dead_pid,
                    "host": socket.gethostname(),
                    "acquired_at": time.time(),
                    "token": "orphaned-token",
                }
            )
        )
        old_time = time.time() - 1000
        os.utime(p, (old_time, old_time))

        thief = FileLock(p, timeout=1.0, auto_cleanup_stale=True)
        assert thief.acquire() is True
        thief.release()


class TestReleaseTokenSafety:
    def test_release_does_not_delete_lock_reclaimed_by_new_owner(self, tmp_path):
        p = tmp_path / "x.lock"
        first = FileLock(p)
        assert first.acquire() is True

        # Simulate another process reclaiming this path as stale mid-hold and
        # writing its own lock metadata with a different token.
        p.write_text(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "host": socket.gethostname(),
                    "acquired_at": time.time(),
                    "token": "someone-elses-token",
                }
            )
        )

        first.release()  # must NOT delete the new owner's lock file

        assert p.exists()
        assert json.loads(p.read_text())["token"] == "someone-elses-token"

    def test_release_deletes_own_unreclaimed_lock(self, tmp_path):
        p = tmp_path / "x.lock"
        lock = FileLock(p)
        assert lock.acquire() is True
        lock.release()
        assert not p.exists()


class TestLockManagerCleanup:
    def test_cleanup_all_with_held_lock_does_not_raise(self, tmp_path):
        # Regression: _cleanup_all() used to iterate _active_locks while
        # lock.release() -> unregister() mutated it, raising
        # "dictionary changed size during iteration" at interpreter shutdown.
        lock = FileLock(tmp_path / "held.lock")
        assert lock.acquire() is True
        manager = get_lock_manager()
        manager._cleanup_all()  # must not raise
        assert lock.is_acquired is False
