"""Regression test: a hung shutdown step must not block PipelineExecutor.shutdown()
past its own per-step timeout.

Before the fix, each step ran inside `with ThreadPoolExecutor(max_workers=1) as
ex:`, whose `__exit__` calls `shutdown(wait=True)` — blocking until the hung
step's thread finished on its own (Python cannot forcibly stop a running
thread), regardless of the `.result(timeout=...)` that had already fired.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

from ducta.core.executor import PipelineExecutor


def _executor_with_context(context: MagicMock) -> PipelineExecutor:
    executor = PipelineExecutor.__new__(PipelineExecutor)
    executor.context = context
    executor._streaming_executor = None
    return executor


class TestShutdownDoesNotBlockOnHungStep:
    def test_hung_streaming_stop_does_not_block_past_its_timeout(self):
        context = MagicMock()
        context.has_spark_session.return_value = False
        del context.connection_pools  # hasattr(...) is False, _release_connection_pools no-ops
        executor = _executor_with_context(context)

        # _stop_streaming_queries has a 5s timeout in the shutdown sequence.
        executor._stop_streaming_queries = lambda: time.sleep(60)

        start = time.perf_counter()
        executor.shutdown()
        elapsed = time.perf_counter() - start

        # Bounded by the step timeouts (5 + ~0 + ~0), nowhere near the 60s the
        # hung step actually takes — the old `with ThreadPoolExecutor(...)`
        # behavior would have blocked here for the full 60s.
        assert elapsed < 15.0
