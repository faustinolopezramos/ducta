"""`_spawn_db_task` must keep a strong reference to what it schedules.

The event loop holds only a weak reference to a task, so a fire-and-forget
`create_task(...)` whose sole strong reference is a local variable can be
collected mid-await. These particular tasks persist the execution record, so
losing one loses a run from the database with nothing logged.
"""

from __future__ import annotations

import asyncio
import gc

import pytest

from ducta.api.execution.manager import _DB_TASKS, _spawn_db_task


@pytest.fixture(autouse=True)
def _clean_registry():
    _DB_TASKS.clear()
    yield
    _DB_TASKS.clear()


class TestSpawnDbTask:
    def test_task_survives_garbage_collection_while_pending(self):
        finished = []

        async def scenario():
            started = asyncio.Event()
            release = asyncio.Event()

            async def _slow():
                started.set()
                await release.wait()
                finished.append(True)

            _spawn_db_task(_slow(), "add")
            await started.wait()

            # Nothing in this frame references the task; only the registry does.
            gc.collect()
            assert len(_DB_TASKS) == 1, "task was not strongly referenced"

            release.set()
            for _ in range(5):
                await asyncio.sleep(0)

        asyncio.run(scenario())
        assert finished == [True], "task did not run to completion"

    def test_registry_is_emptied_when_the_task_completes(self):
        async def scenario():
            async def _noop():
                return None

            _spawn_db_task(_noop(), "update")
            assert len(_DB_TASKS) == 1

            for _ in range(5):
                await asyncio.sleep(0)
            assert _DB_TASKS == set(), "completed tasks must not accumulate"

        asyncio.run(scenario())

    def test_a_failing_task_is_discarded_without_raising(self):
        async def scenario():
            async def _boom():
                raise RuntimeError("db is down")

            _spawn_db_task(_boom(), "flush_logs")
            for _ in range(5):
                await asyncio.sleep(0)
            assert _DB_TASKS == set()

        asyncio.run(scenario())

    def test_no_running_loop_closes_the_coroutine_instead_of_leaking(self):
        async def _never_awaited():
            return None

        coro = _never_awaited()
        _spawn_db_task(coro, "add")  # no running loop here

        assert _DB_TASKS == set()
        # The coroutine was closed rather than left dangling, so it can no
        # longer be started — and it emits no "never awaited" RuntimeWarning.
        with pytest.raises(RuntimeError):
            coro.send(None)
