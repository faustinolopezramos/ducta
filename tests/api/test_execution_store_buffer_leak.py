"""Regression: `ExecutionStore.add`/`prune_stale`/`evict_old` only returned a
*count* of removed records — the caller (`ExecutionManager`, which also owns
the per-execution log buffers in `BufferedLogManager`) had no way to know
*which* executions were removed, so their log buffers were never cleaned up.
A record pruned/evicted from the metadata store left its buffer alive
forever: an unbounded aggregate memory leak across every execution the
server had ever run.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ducta.api.execution.store import ExecutionStore
from ducta.api.models.execution import ExecutionResponse, ExecutionStatus


def _record(exec_id, status=ExecutionStatus.SUCCESS, finished_at=None):
    return ExecutionResponse(
        id=exec_id,
        pipeline_name="p",
        env="dev",
        status=status,
        started_at=datetime.now(tz=timezone.utc),
        finished_at=finished_at,
    )


class TestEvictOldReturnsRemovedIds:
    def test_evict_old_returns_the_actual_ids(self):
        store = ExecutionStore(max_size=2)
        store._executions["a"] = _record("a")
        store._executions["b"] = _record("b")
        store._executions["c"] = _record("c")

        removed = store.evict_old()

        assert removed == ["a"]
        assert "a" not in store._executions

    def test_add_returns_ids_evicted_as_a_side_effect(self):
        store = ExecutionStore(max_size=1)
        store._executions["old"] = _record("old")

        removed = store.add(_record("new", status=ExecutionStatus.PENDING))

        assert removed == ["old"]
        assert "old" not in store._executions
        assert "new" in store._executions


class TestPruneStaleReturnsRemovedIds:
    def test_prune_stale_returns_the_actual_ids(self):
        store = ExecutionStore(max_size=500)
        old_finish = datetime.now(tz=timezone.utc) - timedelta(hours=2)
        store._executions["stale"] = _record("stale", finished_at=old_finish)
        store._executions["fresh"] = _record("fresh", finished_at=datetime.now(tz=timezone.utc))

        removed = store.prune_stale(retention_seconds=60)

        assert removed == ["stale"]
        assert "stale" not in store._executions
        assert "fresh" in store._executions
