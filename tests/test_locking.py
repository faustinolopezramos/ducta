"""`ducta.locking`: the one advisory-lock implementation Ducta uses.

The run lock, the API's config lock and Sentinel take it without waiting
(`try_lock_fd`); the quality history waits for it (`exclusive_lock`). The quality
history used to carry its own copy, whose Windows fix the shared one lacked.
"""

from __future__ import annotations

import os
import threading
import time

from ducta.locking import exclusive_lock, try_lock_fd, unlock_fd


def test_a_held_lock_refuses_a_second_taker_until_released(tmp_path):
    path = tmp_path / "x.lock"
    path.touch()
    first = os.open(path, os.O_RDWR)
    second = os.open(path, os.O_RDWR)
    try:
        assert try_lock_fd(first) is True
        assert try_lock_fd(second) is False
        unlock_fd(first)
        assert try_lock_fd(second) is True
        unlock_fd(second)
    finally:
        os.close(first)
        os.close(second)


def test_exclusive_lock_waits_for_the_holder(tmp_path):
    path = tmp_path / "x.lock"
    path.touch()
    events = []

    def holder():
        with open(path, "r+") as f, exclusive_lock(f):
            events.append("held")
            time.sleep(0.3)
            events.append("released")

    thread = threading.Thread(target=holder)
    thread.start()
    while not events:
        time.sleep(0.01)
    with open(path, "r+") as f, exclusive_lock(f):
        events.append("second")
    thread.join()

    assert events == ["held", "released", "second"]


def test_the_file_position_survives_the_lock(tmp_path):
    path = tmp_path / "data.json"
    path.write_text("0123456789")
    with open(path, "r+") as f:
        f.seek(4)
        with exclusive_lock(f):
            assert f.read(2) == "45"
        assert f.tell() == 6


def test_the_non_blocking_lock_keeps_the_descriptor_position(tmp_path):
    path = tmp_path / "x.lock"
    path.write_text("0123456789")
    fd = os.open(path, os.O_RDWR)
    try:
        os.lseek(fd, 5, os.SEEK_SET)
        assert try_lock_fd(fd)
        assert os.lseek(fd, 0, os.SEEK_CUR) == 5
        unlock_fd(fd)
    finally:
        os.close(fd)


def test_on_windows_lock_and_unlock_name_the_same_byte(tmp_path, monkeypatch):
    """msvcrt locks from the current position: both calls are pinned to byte 0."""
    import importlib
    import sys
    import types

    import ducta.locking as locking

    calls = []

    def fake_locking(fd, mode, nbytes):
        calls.append((mode, os.lseek(fd, 0, os.SEEK_CUR), nbytes))

    fake = types.SimpleNamespace(LK_LOCK=1, LK_UNLCK=0, LK_NBLCK=2, locking=fake_locking)
    monkeypatch.setitem(sys.modules, "msvcrt", fake)
    monkeypatch.setattr(sys, "platform", "win32")
    windows = importlib.reload(locking)  # as the module loads on Windows
    try:
        path = tmp_path / "data.json"
        path.write_text("0123456789")
        with open(path, "r+") as f:
            f.seek(4)
            with windows.exclusive_lock(f):
                f.seek(8)
    finally:
        monkeypatch.undo()
        importlib.reload(locking)

    assert calls == [(1, 0, 1), (0, 0, 1)]
