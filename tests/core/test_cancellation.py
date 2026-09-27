"""Timeouts that stop the work, not just the bookkeeping.

A Python thread cannot be killed, so a timed-out node used to keep running —
and keep writing — after its run had been reported failed. Cancellation now
acts where the work happens: the node's Spark jobs (tagged per run and node,
cancelled on timeout), its dataset writes (refused), and `run_in_process`
workers (terminated).
"""

from __future__ import annotations

import time
from concurrent.futures import Future
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ducta.core.errors import NodeCancelledError
from ducta.core.execution import cancellation
from ducta.core.execution.coordinator import ParallelCoordinator
from ducta.core.execution.output import OutputWriter
from ducta.core.execution.runner import NodeExecutor
from ducta.core.execution.state import ThreadSafeExecutionState
from ducta.core.execution_context import node_id_var
from ducta.core.ledger import ledger_for
from tests.core.fakes import FakeContext


class _SparkContext:
    def __init__(self):
        self.calls = []

    def clearJobTags(self):  # noqa: N802 — Spark API name
        self.calls.append(("clear",))

    def addJobTag(self, tag):  # noqa: N802
        self.calls.append(("add", tag))

    def cancelJobsWithTag(self, tag):  # noqa: N802
        self.calls.append(("cancel", tag))


class _Ctx(FakeContext):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.spark = SimpleNamespace(sparkContext=_SparkContext())


class TestSparkJobs:
    def test_a_node_tags_its_jobs_after_clearing_the_previous_nodes_tag(self):
        ctx = _Ctx()
        cancellation.tag_current_thread(ctx, "load")
        assert ctx.spark.sparkContext.calls == [
            ("clear",),
            ("add", cancellation.job_tag(ctx, "load")),
        ]

    def test_cancelling_a_node_cancels_exactly_its_tag(self):
        ctx = _Ctx()
        cancellation.cancel_node(ctx, "load")
        assert ctx.spark.sparkContext.calls == [("cancel", cancellation.job_tag(ctx, "load"))]
        assert cancellation.is_cancelled(ctx, "load")
        assert not cancellation.is_cancelled(ctx, "transform")

    def test_the_tag_is_unique_per_run(self):
        """Runs share one SparkContext in the API server: cancelling `load`
        of one run must not touch `load` of another."""
        assert cancellation.job_tag(_Ctx(), "load") != cancellation.job_tag(_Ctx(), "load")

    def test_spark_connect_sessions_use_interrupt_tag(self):
        session = MagicMock(spec=["addTag", "clearTags", "interruptTag"])
        ctx = FakeContext()
        ctx.spark = session
        cancellation.cancel_node(ctx, "load")
        session.interruptTag.assert_called_once_with(cancellation.job_tag(ctx, "load"))

    def test_no_spark_session_is_fine(self):
        ctx = FakeContext()
        cancellation.tag_current_thread(ctx, "n")
        cancellation.cancel_node(ctx, "n")
        assert cancellation.is_cancelled(ctx, "n")


class TestWritesAreRefused:
    def test_a_cancelled_node_cannot_write(self):
        ctx = FakeContext()
        manager = MagicMock()
        writer = OutputWriter(manager, ctx)
        cancellation.cancel_node(ctx, "load")

        with pytest.raises(NodeCancelledError):
            writer.save(MagicMock(), {}, "load", "2026-01-01", "2026-01-01", {})
        manager.save_output.assert_not_called()

    def test_the_current_threads_node_is_used_by_default(self):
        ctx = FakeContext()
        cancellation.cancel_node(ctx, "load")
        token = node_id_var.set("load")
        try:
            with pytest.raises(NodeCancelledError):
                cancellation.ensure_not_cancelled(ctx)
        finally:
            node_id_var.reset(token)
        cancellation.ensure_not_cancelled(ctx, "other")


def _coordinator(ctx, *, node_timeout=10, execution_timeout=None):
    if execution_timeout is not None:
        ctx.global_config["execution_timeout_seconds"] = execution_timeout
    return ParallelCoordinator(
        context=ctx,
        max_workers=2,
        node_timeout=node_timeout,
        is_ml_layer=False,
        execute_callback=lambda *a, **k: None,
        ml_builder=None,
    )


def _running(names, started_ago):
    state = ThreadSafeExecutionState(list(names), {n: {} for n in names})
    for name in names:
        future: Future = Future()
        future.set_running_or_notify_cancel()
        state.add_running_future(
            future, {"node_name": name, "start_time": time.time() - started_ago, "config": {}}
        )
    return state


class TestCoordinator:
    def test_node_timeout_cancels_the_node_and_records_the_gap(self):
        ctx = _Ctx()
        coordinator = _coordinator(ctx, node_timeout=10)
        state = _running(["hung"], started_ago=999)

        coordinator._fail_timed_out_nodes(state)

        assert state.is_failed()
        assert cancellation.is_cancelled(ctx, "hung")
        assert ("cancel", cancellation.job_tag(ctx, "hung")) in ctx.spark.sparkContext.calls
        assert any("hung" in gap for gap in ledger_for(ctx).record_failures)

    def test_execution_timeout_is_enforced_for_the_whole_run(self):
        """It used to be only a polling cap: a run over it just kept going."""
        ctx = _Ctx()
        coordinator = _coordinator(ctx, node_timeout=3600, execution_timeout=60)
        coordinator._run_started = time.time() - 120
        state = _running(["a", "b"], started_ago=5)  # each node well inside its own budget

        coordinator._fail_timed_out_nodes(state)

        assert state.is_failed()
        assert cancellation.is_cancelled(ctx, "a") and cancellation.is_cancelled(ctx, "b")
        assert state.get_running_count() == 0

    def test_inside_every_budget_nothing_is_cancelled(self):
        ctx = _Ctx()
        coordinator = _coordinator(ctx, node_timeout=3600, execution_timeout=3600)
        coordinator._run_started = time.time()
        state = _running(["a"], started_ago=1)

        coordinator._fail_timed_out_nodes(state)

        assert not state.is_failed()
        assert not cancellation.is_cancelled(ctx, "a")


def _never_returns(payload, conn):
    while True:
        time.sleep(1)


def _returns_success(payload, conn):
    conn.send({"status": "success"})
    conn.close()


class TestRunInProcess:
    def _executor(self, ctx):
        executor = NodeExecutor.__new__(NodeExecutor)
        executor.context = ctx
        executor._children = set()
        return executor

    def test_a_cancelled_worker_process_is_terminated(self):
        ctx = FakeContext()
        executor = self._executor(ctx)
        import threading

        threading.Timer(1.0, cancellation.cancel_node, args=(ctx, "cpu")).start()
        started = time.time()
        with pytest.raises(NodeCancelledError):
            executor._run_child("cpu", {}, target=_never_returns)
        assert time.time() - started < 20
        assert executor._children == set()

    def test_a_worker_that_finishes_returns_its_outcome(self):
        executor = self._executor(FakeContext())
        assert executor._run_child("cpu", {}, target=_returns_success) == {"status": "success"}
