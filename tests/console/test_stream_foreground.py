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
        # One Ctrl+C, as in life: the status read that follows the stop must work.
        if self.interrupt_after is not None and self.polls == self.interrupt_after + 1:
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


def test_ctrl_c_ends_with_what_the_run_processed(capsys):
    stopped = {
        "active_queries": 0,
        "status": "stopped",
        "uptime_seconds": 7,
        "query_statuses": {"n": {"isActive": False}},
        "totals": {"n": {"rows": 1500.0, "batches": 3}},
    }
    executor = _Executor([{"active_queries": 1}, stopped], interrupt_after=1)
    assert execution._stay_in_foreground(executor, "events", "e1") == ExitCode.SUCCESS.value
    out = capsys.readouterr().out
    assert "Stopped" in out and "1,500" in out


def test_a_run_that_ends_on_its_own_prints_the_same_summary(capsys):
    done = {
        "active_queries": 0,
        "status": "completed",
        "uptime_seconds": 3,
        "query_statuses": {"n": {"isActive": False}},
        "totals": {"n": {"rows": 40.0, "batches": 1}},
    }
    executor = _Executor([{"active_queries": 1}, done])
    assert execution._stay_in_foreground(executor, "events", "e1") == ExitCode.SUCCESS.value
    assert "Finished" in capsys.readouterr().out
