import threading
import time

from ducta.gate.concurrency import run_parallel


class TestRunParallelSuccess:
    def test_preserves_order(self):
        def fn(item):
            time.sleep(0.01 * (5 - item))
            return item * 10

        outcome = run_parallel(list(range(5)), fn, max_workers=5)
        assert outcome.results == [0, 10, 20, 30, 40]
        assert outcome.errors == []
        assert outcome.aborted is False


class TestRunParallelFailFast:
    def test_aborts_without_waiting_for_blocked_tasks(self):
        release = threading.Event()

        def fn(item):
            if item == 0:
                raise RuntimeError("boom")
            release.wait(timeout=5)
            return item

        start = time.monotonic()
        outcome = run_parallel([0, 1, 2, 3], fn, max_workers=4, fail_fast=True)
        elapsed = time.monotonic() - start

        assert outcome.aborted is True
        assert len(outcome.errors) == 1
        assert outcome.errors[0][0] == 0
        assert isinstance(outcome.errors[0][1], RuntimeError)
        assert elapsed < 1.0

        release.set()


class TestRunParallelNoFailFast:
    def test_collects_all_errors_with_index(self):
        def fn(item):
            if item % 2 == 0:
                raise ValueError(f"bad {item}")
            return item

        outcome = run_parallel([0, 1, 2, 3], fn, max_workers=4, fail_fast=False)

        assert outcome.aborted is False
        error_indices = {idx for idx, _ in outcome.errors}
        assert error_indices == {0, 2}
        assert outcome.results[1] == 1
        assert outcome.results[3] == 3
