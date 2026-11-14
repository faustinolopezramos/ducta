"""Data breakpoints: a run pauses after a node until it is resumed or cancelled."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from ducta.core.execution.coordinator import ParallelCoordinator
from ducta_server.execution.manager import ExecutionManager
from ducta_server.models.execution import ExecutionResponse, ExecutionStatus


class _Store(dict):
    def get(self, key):  # noqa: D401 — the manager's store raises on a miss
        return self[key]


@pytest.fixture
def manager():
    mgr = object.__new__(ExecutionManager)
    mgr._execution_lock = threading.RLock()
    mgr._store = _Store()
    mgr.emitted = []
    mgr.emit_execution_status = lambda record: mgr.emitted.append(record.status)
    mgr._timeout_manager = SimpleNamespace(cancel_handler=lambda _id: None)
    mgr._execution_queue = SimpleNamespace(cancel_execution=lambda _id: None)
    mgr._active_engines = {}
    mgr._task_lock = threading.Lock()
    mgr._execution_tasks = {}
    mgr._running_tasks = set()
    mgr._store["r1"] = ExecutionResponse(
        id="r1",
        pipeline_name="p",
        env="dev",
        status=ExecutionStatus.RUNNING,
        started_at=datetime.now(timezone.utc),
    )
    return mgr


def _pause_in_thread(manager, node="silver.clean"):
    errors = []

    def run():
        try:
            manager.wait_at_breakpoint("r1", node)
        except RuntimeError as e:
            errors.append(e)

    t = threading.Thread(target=run)
    t.start()
    for _ in range(100):
        if manager._store["r1"].status == ExecutionStatus.PAUSED:
            break
        time.sleep(0.01)
    return t, errors


def test_pauses_then_resumes(manager):
    t, errors = _pause_in_thread(manager)
    record = manager._store["r1"]
    assert record.status == ExecutionStatus.PAUSED and record.paused_at == "silver.clean"
    assert manager.resume("r1") is True
    t.join(2)
    assert not t.is_alive() and not errors
    assert record.status == ExecutionStatus.RUNNING and record.paused_at is None
    assert manager.resume("r1") is False  # not paused any more


def test_cancelling_a_paused_run_stops_it(manager):
    t, errors = _pause_in_thread(manager)
    assert manager.cancel_execution("r1") is True
    t.join(2)
    assert not t.is_alive()
    assert errors and "cancelled while paused" in str(errors[0])
    assert manager._store["r1"].status == ExecutionStatus.CANCELLED


def test_the_coordinator_pauses_only_at_breakpoints():
    hits = []
    coord = object.__new__(ParallelCoordinator)
    coord.context = SimpleNamespace(pause_after={"b"}, breakpoint_hook=hits.append)
    coord._run_started = time.time()
    started = coord._run_started
    coord._maybe_pause("a")
    coord._maybe_pause("b")
    assert hits == ["b"]
    assert coord._run_started >= started  # the pause is not charged to the run's timeout


def test_cancelling_stops_the_engine_of_a_run_in_this_process(manager):
    """A run in this process is a thread that cannot be killed: cancelling must tell the
    engine, or the run keeps writing and seals a success certificate."""
    calls = []
    manager._bg_shutdown_lock = threading.Lock()
    manager._bg_shutdown_threads = set()

    class Engine:
        def cancel_run(self):
            calls.append("cancel_run")

        def shutdown(self):
            calls.append("shutdown")

    manager._active_engines["r1"] = Engine()
    assert manager.cancel_execution("r1") is True
    for _ in range(100):
        if "shutdown" in calls:
            break
        time.sleep(0.01)
    assert calls == ["cancel_run", "shutdown"]


def test_an_engine_without_cancel_run_is_still_shut_down(manager):
    """A run in its own process is stopped by SIGTERM; its engine has no cancel_run."""
    calls = []
    manager._bg_shutdown_lock = threading.Lock()
    manager._bg_shutdown_threads = set()
    manager._active_engines["r1"] = SimpleNamespace(shutdown=lambda: calls.append("shutdown"))
    assert manager.cancel_execution("r1") is True
    for _ in range(100):
        if calls:
            break
        time.sleep(0.01)
    assert calls == ["shutdown"]
