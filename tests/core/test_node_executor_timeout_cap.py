"""Regression test: NodeExecutor.node_timeout must respect the 24h cap,
mirroring BaseExecutor.timeout_seconds for the whole-pipeline timeout.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from ducta.core.execution.runner import NodeExecutor


def _node_executor(node_timeout_seconds) -> NodeExecutor:
    context = MagicMock()
    context.global_settings = {"node_timeout_seconds": node_timeout_seconds}
    context.is_ml_layer = False
    return NodeExecutor(context, MagicMock(), MagicMock(), max_workers=1)


class TestNodeTimeoutCap:
    def test_within_cap_is_used_as_is(self):
        ne = _node_executor(1800)
        assert ne.node_timeout == 1800

    def test_over_cap_is_clamped_to_24h(self):
        ne = _node_executor(999_999)
        assert ne.node_timeout == 86400

    def test_explicit_timeout_arg_is_also_clamped(self):
        context = MagicMock()
        context.global_settings = {}
        context.is_ml_layer = False
        ne = NodeExecutor(context, MagicMock(), MagicMock(), max_workers=1, timeout=999_999)
        assert ne.node_timeout == 86400
