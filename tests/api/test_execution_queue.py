"""`ExecutionQueue` — concurrency cap and priority ordering.

The queue had no tests at all, which is how its central feature came to do
nothing. `dequeue()` popped the *highest-priority* item and put that id into
`_active`, then returned it — and `_run_execution` threw the return value away
and ran its own execution instead, releasing its own id when done. The count
balanced by coincidence, so the cap held; but `_active` named runs that were not
running (and that is what `GET /executions/queue` reports), and the order was
decided by asyncio task-creation order rather than by `ExecutionPriority`.

`acquire_slot(execution_id)` returns only once *that* execution holds a slot, so
these tests can assert on the two things that were silently untrue: who runs
first, and who `_active` says is running.
"""

from __future__ import annotations

import asyncio

import pytest

from ducta.api.execution.queue import ExecutionPriority, ExecutionQueue


def _queue(max_concurrent: int = 2) -> ExecutionQueue:
    return ExecutionQueue(max_concurrent=max_concurrent)


class TestPriorityDecidesOrder:
    def test_a_higher_priority_execution_runs_before_one_queued_earlier(self):
        queue = _queue(max_concurrent=1)
        started: list[str] = []

        # One execution already occupies the only slot. Then "low" is queued
        # first and its waiter starts first — but "high" must still take the
        # slot when it frees. Under the old dequeue() this was decided by
        # asyncio task-creation order, so "low" won.
        queue.enqueue("blocker", "p", ExecutionPriority.NORMAL)

        async def waiter(execution_id: str) -> None:
            await queue.acquire_slot(execution_id)
            started.append(execution_id)

        async def scenario() -> None:
            await queue.acquire_slot("blocker")
            started.append("blocker")

            queue.enqueue("low", "p", ExecutionPriority.LOW)
            queue.enqueue("high", "p", ExecutionPriority.HIGH)

            low = asyncio.create_task(waiter("low"))
            high = asyncio.create_task(waiter("high"))
            await asyncio.sleep(0)  # let both register as waiters

            queue.mark_complete("blocker")
            await asyncio.wait_for(high, timeout=2)

            queue.mark_complete("high")
            await asyncio.wait_for(low, timeout=2)

        asyncio.run(scenario())

        assert started == ["blocker", "high", "low"]

    def test_equal_priority_keeps_fifo(self):
        queue = _queue(max_concurrent=1)
        started: list[str] = []

        for name in ("first", "second"):
            queue.enqueue(name, "p", ExecutionPriority.NORMAL)

        async def scenario() -> None:
            await queue.acquire_slot("first")
            started.append("first")
            task = asyncio.create_task(queue.acquire_slot("second"))
            await asyncio.sleep(0)
            queue.mark_complete("first")
            await asyncio.wait_for(task, timeout=1)
            started.append("second")

        asyncio.run(scenario())

        assert started == ["first", "second"]


class TestTheConcurrencyCap:
    def test_no_more_than_max_concurrent_hold_slots(self):
        queue = _queue(max_concurrent=2)
        for name in ("a", "b", "c"):
            queue.enqueue(name, "p")

        async def scenario() -> None:
            await queue.acquire_slot("a")
            await queue.acquire_slot("b")
            assert queue.active_count == 2
            assert queue.is_over_capacity

            third = asyncio.create_task(queue.acquire_slot("c"))
            await asyncio.sleep(0)
            assert not third.done(), "the third execution must wait for a slot"

            queue.mark_complete("a")
            await asyncio.wait_for(third, timeout=1)
            assert queue.active_count == 2

        asyncio.run(scenario())

    def test_a_waiter_blocks_until_a_slot_frees(self):
        queue = _queue(max_concurrent=1)
        queue.enqueue("busy", "p")
        queue.enqueue("next", "p")

        async def scenario() -> None:
            await queue.acquire_slot("busy")
            task = asyncio.create_task(queue.acquire_slot("next"))
            await asyncio.sleep(0.01)
            assert not task.done()
            queue.mark_complete("busy")
            await asyncio.wait_for(task, timeout=1)

        asyncio.run(scenario())


class TestActiveReflectsWhatIsRunning:
    def test_active_holds_the_ids_that_acquired_slots(self):
        # The regression: `_active` used to hold whichever id the heap surfaced,
        # not the ones actually running.
        queue = _queue(max_concurrent=2)
        queue.enqueue("low", "p", ExecutionPriority.LOW)
        queue.enqueue("high", "p", ExecutionPriority.HIGH)

        async def scenario() -> None:
            await queue.acquire_slot("high")
            assert "high" in queue._active
            await queue.acquire_slot("low")
            assert queue._active == {"high", "low"}

        asyncio.run(scenario())

    def test_completing_releases_that_id(self):
        queue = _queue(max_concurrent=1)
        queue.enqueue("solo", "p")

        asyncio.run(queue.acquire_slot("solo"))
        assert queue.active_count == 1

        assert queue.mark_complete("solo") is True
        assert queue.active_count == 0
        assert queue.get_stats()["total_completed"] == 1

    def test_completing_an_unknown_id_is_a_no_op(self):
        queue = _queue()
        assert queue.mark_complete("never-seen") is False
        assert queue.active_count == 0


class TestCancellation:
    def test_a_cancelled_execution_never_takes_a_slot(self):
        queue = _queue(max_concurrent=1)
        queue.enqueue("doomed", "p", ExecutionPriority.HIGH)
        queue.enqueue("survivor", "p", ExecutionPriority.LOW)

        assert queue.cancel_execution("doomed") is True

        async def scenario() -> None:
            # Even though "doomed" had the higher priority, the slot goes to the
            # survivor rather than being held by an execution that will not run.
            await asyncio.wait_for(queue.acquire_slot("survivor"), timeout=1)

        asyncio.run(scenario())

        assert queue._active == {"survivor"}
        assert queue.get_stats()["total_cancelled"] == 1

    def test_cancelling_an_unqueued_id_returns_false(self):
        queue = _queue()
        assert queue.cancel_execution("never-seen") is False


class TestDefensiveGrant:
    def test_acquiring_without_enqueuing_grants_rather_than_hangs(self):
        # A bookkeeping slip must not deadlock a pipeline run forever.
        queue = _queue(max_concurrent=1)

        asyncio.run(asyncio.wait_for(queue.acquire_slot("orphan"), timeout=1))

        assert "orphan" in queue._active

    def test_acquiring_twice_is_idempotent(self):
        queue = _queue(max_concurrent=1)
        queue.enqueue("solo", "p")

        async def scenario() -> None:
            await queue.acquire_slot("solo")
            await asyncio.wait_for(queue.acquire_slot("solo"), timeout=1)

        asyncio.run(scenario())

        assert queue.active_count == 1


class TestStats:
    def test_stats_report_capacity_and_depth(self):
        queue = _queue(max_concurrent=3)
        queue.enqueue("a", "p")
        queue.enqueue("b", "p")

        stats = queue.get_stats()

        assert stats["capacity"] == 3
        assert stats["queued"] == 2
        assert stats["active"] == 0
        assert stats["total_queued"] == 2


@pytest.mark.parametrize(
    "env,expected",
    [("prod", ExecutionPriority.HIGH), ("production", ExecutionPriority.HIGH)],
)
def test_production_environments_map_to_high_priority(env, expected):
    # Priority only matters now that it actually orders execution.
    assert ExecutionPriority.from_env(env) is expected
