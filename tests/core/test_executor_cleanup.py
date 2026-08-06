"""Unit tests for PipelineExecutor._cleanup_memory's Spark-session guard.

Phase 1 (lazy Spark session) changed this guard from
`getattr(context, "spark", None)` to `context.has_spark_session()` — the
former would force a lazy session into existence just to check for one, only
to then try clearing a cache it never populated. These tests lock in that the
guard neither creates a session nor blows up when none was ever materialized,
and still clears the catalog cache when one was.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from ducta.core.executors.facade import PipelineExecutor


def _executor_with_context(context: MagicMock) -> PipelineExecutor:
    executor = PipelineExecutor.__new__(PipelineExecutor)
    executor.context = context
    return executor


class TestCleanupMemorySparkGuard:
    def test_no_session_materialized_skips_cache_clear(self):
        context = MagicMock()
        context.has_spark_session.return_value = False
        executor = _executor_with_context(context)

        executor._cleanup_memory()

        context.has_spark_session.assert_called_once()
        context.spark.catalog.clearCache.assert_not_called()

    def test_materialized_session_clears_cache(self):
        context = MagicMock()
        context.has_spark_session.return_value = True
        executor = _executor_with_context(context)

        executor._cleanup_memory()

        context.spark.catalog.clearCache.assert_called_once()

    def test_clear_cache_failure_is_swallowed(self):
        context = MagicMock()
        context.has_spark_session.return_value = True
        context.spark.catalog.clearCache.side_effect = RuntimeError("boom")
        executor = _executor_with_context(context)

        executor._cleanup_memory()  # must not raise
