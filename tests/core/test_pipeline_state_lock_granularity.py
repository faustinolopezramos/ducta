"""Regression test: fail_node_execution must not hold its lock while a
dependent streaming query's (potentially slow) .stop() call runs.

Before the fix, `stop_dependent_streaming_nodes` — called from
`_propagate_failure`, itself called from inside `fail_node_execution`'s
`with self._lock:` block — ran `streaming_query.stop()` with that lock held.
Since it's an RLock, the nested re-acquisitions inside stop_dependent_streaming_
nodes only look released to the *same* thread; every other thread stayed
blocked on the still-held outer lock for as long as `.stop()` took, stalling
unrelated nodes' state transitions.
"""

from __future__ import annotations

import threading
import time

from ducta.core.pipeline_state import NodeType, UnifiedPipelineState


class _SlowStreamingQuery:
    def __init__(self, release_event: threading.Event):
        self._release_event = release_event

    def stop(self):
        self._release_event.wait(timeout=2.0)


class TestFailNodeExecutionDoesNotBlockOtherThreads:
    def test_concurrent_status_read_is_not_blocked_by_slow_stop(self):
        state = UnifiedPipelineState()
        state.register_node("batch1", NodeType.BATCH)
        state.register_node("stream1", NodeType.STREAMING, dependencies=["batch1"])

        release_event = threading.Event()
        state.register_streaming_query("stream1", _SlowStreamingQuery(release_event))

        state.start_node_execution("batch1")

        fail_thread = threading.Thread(
            target=state.fail_node_execution,
            args=("batch1", "[QualityGateBlocked] bad data"),
        )
        fail_thread.start()
        time.sleep(0.05)  # let fail_node_execution reach the slow .stop() call

        # A concurrent, unrelated read must not be blocked behind the still-
        # running .stop() call.
        read_done = threading.Event()

        def read_status():
            state.get_node_status("batch1")
            read_done.set()

        read_thread = threading.Thread(target=read_status)
        read_thread.start()
        read_thread.join(timeout=1.0)

        assert read_done.is_set() is True

        release_event.set()
        fail_thread.join(timeout=2.0)
