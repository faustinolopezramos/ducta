"""Unit tests for ducta.core.resource_manager.ResourceManager."""

from __future__ import annotations

import threading
import time

import pytest

from ducta.core.resource_manager import ResourceManager


@pytest.fixture
def manager():
    # ResourceManager is a process-wide singleton; reset it so each test
    # starts from a clean slate instead of accumulating state across tests.
    ResourceManager._instance = None
    mgr = ResourceManager()
    yield mgr
    ResourceManager._instance = None


class TestCleanupContextLockScope:
    def test_cleanup_does_not_hold_the_lock_during_the_callback(self, manager):
        release_event = threading.Event()

        def slow_cleanup(_resource):
            release_event.wait(timeout=2.0)

        manager.register_resource("node1", object(), "generic", cleanup_fn=slow_cleanup)

        other_registered = threading.Event()

        def register_from_another_thread():
            manager.register_resource("node2", object(), "generic")
            other_registered.set()

        t = threading.Thread(target=manager.cleanup_context, args=("node1",))
        t.start()
        time.sleep(0.05)  # let cleanup_context enter the slow callback

        register_thread = threading.Thread(target=register_from_another_thread)
        register_thread.start()
        register_thread.join(timeout=1.0)

        # A concurrent register() for a different context must not be blocked
        # behind node1's slow cleanup callback.
        assert other_registered.is_set() is True

        release_event.set()
        t.join(timeout=2.0)

    def test_all_resources_are_cleaned_up(self, manager):
        cleaned = []
        manager.register_resource("node1", "a", "generic", cleanup_fn=lambda r: cleaned.append(r))
        manager.register_resource("node1", "b", "generic", cleanup_fn=lambda r: cleaned.append(r))

        manager.cleanup_context("node1")

        assert cleaned == ["b", "a"]  # reverse registration order

    def test_failed_cleanup_is_logged_not_silently_dropped(self, manager, monkeypatch):
        import ducta.core.resource_manager as rm_module

        errors = []
        monkeypatch.setattr(rm_module.logger, "error", lambda *a, **k: errors.append((a, k)))

        def raising_cleanup(_resource):
            raise RuntimeError("cleanup boom")

        manager.register_resource("node1", "a", "generic", cleanup_fn=raising_cleanup)
        manager.cleanup_context("node1")

        # ManagedResource.cleanup() catches the exception and returns False;
        # ResourceManager.cleanup_context must itself log an error for that
        # False return, not silently drop it (on top of ManagedResource's own
        # internal error log for the exception).
        assert len(errors) >= 1

    def test_context_with_no_resources_is_a_no_op(self, manager):
        manager.cleanup_context("does-not-exist")  # must not raise


class TestRegisterResourceIndexUnderConcurrency:
    def test_concurrent_registrations_get_distinct_indices(self, manager):
        ids = []
        ids_lock = threading.Lock()

        def register_one(i):
            rid = manager.register_resource("node1", i, "generic")
            with ids_lock:
                ids.append(rid)

        threads = [threading.Thread(target=register_one, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Every returned identifier must be unique — a race in computing the
        # index (register() append, then a separate re-lock to read length)
        # could make two concurrent calls return the same "index" for
        # different resources.
        assert len(ids) == len(set(ids)) == 20
