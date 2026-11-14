"""A node's failure is shown once.

``NodeExecutor`` reports the error and re-raises it; the coordinator receives the same
exception from the future and reported it again, so every failure was printed twice.
"""

from __future__ import annotations

from ducta.core.execution.output import report_node_failure
from ducta.reporting import RunReporter, set_reporter


class _Recorder(RunReporter):
    def __init__(self):
        self.failed = []

    def node_failed(self, node, error):
        self.failed.append((node, error))


def test_the_same_error_is_reported_once():
    recorder = _Recorder()
    previous = set_reporter(recorder)
    try:
        error = ValueError("boom")
        report_node_failure(error, "n")
        report_node_failure(error, "n")  # the coordinator, on the same exception
    finally:
        set_reporter(previous)
    assert recorder.failed == [("n", error)]


def test_a_different_error_is_still_reported():
    recorder = _Recorder()
    previous = set_reporter(recorder)
    try:
        report_node_failure(ValueError("a"), "n")
        report_node_failure(ValueError("b"), "m")
    finally:
        set_reporter(previous)
    assert [node for node, _ in recorder.failed] == ["n", "m"]
