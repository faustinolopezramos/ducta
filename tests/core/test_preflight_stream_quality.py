"""The streaming engine runs no quality checks, so preflight says so.

A `quality` block on a stream node was accepted and never evaluated: a stream with
an impossible check and `on_fail: stop_all` wrote its output and exited 0.
"""

from __future__ import annotations

from ducta.core.preflight import PreflightReport, _check_stream_quality


def _warnings(node):
    report = PreflightReport(pipeline_name="p")
    _check_stream_quality(report, "clean_events", node)
    return report.warnings


def test_quality_on_a_stream_node_is_reported():
    node = {"streaming": {"trigger": "5s"}, "data_quality": {"checks": {"row_count": {"min": 1}}}}
    [warning] = _warnings(node)
    assert "do not run on stream nodes" in warning


def test_a_stream_node_without_quality_is_fine():
    assert _warnings({"streaming": {"trigger": "5s"}}) == []


def test_quality_on_a_batch_node_is_fine():
    assert _warnings({"data_quality": {"checks": {"row_count": {"min": 1}}}}) == []
