"""What preflight says about quality on stream nodes.

A stream node's own `quality` block runs on every micro-batch; input contracts
(`sanity_checks`) do not, and preflight says so rather than letting them be
accepted and ignored.
"""

from __future__ import annotations

from ducta.core.preflight import PreflightReport, _check_stream_quality


def _warnings(node):
    report = PreflightReport(pipeline_name="p")
    _check_stream_quality(report, "clean_events", node)
    return report.warnings


def test_quality_on_a_stream_node_runs_so_nothing_is_said():
    node = {"streaming": {"trigger": "5s"}, "data_quality": {"checks": {"row_count": {"min": 1}}}}
    assert _warnings(node) == []


def test_an_input_contract_on_a_stream_node_is_reported():
    node = {"streaming": {"trigger": "5s"}, "sanity_checks": {"inputs": {"events": {}}}}
    [warning] = _warnings(node)
    assert "input contracts do not run on stream nodes" in warning


def test_a_stream_node_without_quality_is_fine():
    assert _warnings({"streaming": {"trigger": "5s"}}) == []


def test_quality_on_a_batch_node_is_fine():
    assert _warnings({"sanity_checks": {"inputs": {"events": {}}}}) == []
