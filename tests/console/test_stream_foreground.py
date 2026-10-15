"""`ducta stream run` keeps its process alive while the queries run.

The queries live in this process's Spark session. The command used to return
after startup, which ended the process and killed them before they wrote a row.
"""

from __future__ import annotations

import pytest

from ducta.console import execution
from ducta.console.core import ExitCode


class _Executor:
    def __init__(self, statuses, interrupt_after=None):
        self.statuses = list(statuses)
        self.interrupt_after = interrupt_after
        self.polls = 0
        self.stopped = None

    def get_streaming_pipeline_status(self, execution_id):
        self.polls += 1
        if self.interrupt_after is not None and self.polls > self.interrupt_after:
            raise KeyboardInterrupt
        return self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]

    def wait_for_streaming_startup(self, execution_id, timeout=None):
        self.waited = True
        return {}

    def stop_streaming_pipeline(self, execution_id, graceful=True):
        self.stopped = (execution_id, graceful)
        return True


@pytest.fixture(autouse=True)
def _no_wait(monkeypatch):
    monkeypatch.setattr(execution, "_FOREGROUND_POLL_SECONDS", 0)


def test_waits_while_queries_run_and_ends_with_them():
    executor = _Executor([{"active_queries": 2}, {"active_queries": 1}, {"active_queries": 0}])
    assert execution._stay_in_foreground(executor, "events", "e1") == ExitCode.SUCCESS.value
    assert executor.polls >= 3 and executor.stopped is None


def test_ctrl_c_stops_the_queries_gracefully():
    executor = _Executor([{"active_queries": 2}], interrupt_after=2)
    assert execution._stay_in_foreground(executor, "events", "e1") == ExitCode.SUCCESS.value
    assert executor.stopped == ("e1", True)


def test_a_failed_query_fails_the_command():
    executor = _Executor([{"active_queries": 0, "failed_queries": 1, "status": "partial_failure"}])
    assert execution._stay_in_foreground(executor, "events", "e1") == ExitCode.EXECUTION_ERROR.value
