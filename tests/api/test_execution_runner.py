"""Regression tests for `_acquire_stdout_capture_lock` (api.execution.runner).

`with _stdout_capture_lock:` blocked forever. A hung execution (cancel/timeout
can't actually kill a running thread — same limitation as
`ducta.core.node_executor`) keeps holding this process-global lock, which
serialises the entire pipeline body (os.dup2/os.chdir/sys.path mutation are
process-global). That silently wedged every future execution forever with no
visible error. `_acquire_stdout_capture_lock` fails fast with a clear
`ExecutionError` instead.
"""

from __future__ import annotations

import threading

import pytest

from ducta.api.exceptions import ExecutionError
from ducta.api.execution.runner import _acquire_stdout_capture_lock, _stdout_capture_lock


class TestAcquireStdoutCaptureLock:
    def test_acquires_and_releases_when_free(self):
        with _acquire_stdout_capture_lock(timeout=1):
            assert _stdout_capture_lock.locked() is True
        assert _stdout_capture_lock.locked() is False

    def test_raises_execution_error_when_held_by_another_thread(self):
        _stdout_capture_lock.acquire()
        try:
            with pytest.raises(ExecutionError, match="Output capture busy"):
                with _acquire_stdout_capture_lock(timeout=0.05):
                    pass
        finally:
            _stdout_capture_lock.release()

    def test_releases_lock_even_if_body_raises(self):
        with pytest.raises(ValueError):
            with _acquire_stdout_capture_lock(timeout=1):
                raise ValueError("boom")
        assert _stdout_capture_lock.locked() is False

    def test_does_not_block_forever_past_timeout(self):
        _stdout_capture_lock.acquire()
        try:
            start = threading.Event()
            errored = threading.Event()

            def _try_acquire():
                start.set()
                try:
                    with _acquire_stdout_capture_lock(timeout=0.1):
                        pass
                except ExecutionError:
                    errored.set()

            t = threading.Thread(target=_try_acquire)
            t.start()
            t.join(timeout=2)
            assert not t.is_alive()
            assert errored.is_set()
        finally:
            _stdout_capture_lock.release()
