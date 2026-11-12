"""`--node` runs one node under its time limit, as a whole-pipeline run does.

It used to call the node directly: `timeout_seconds: 2` on a node that took 6s
ended with exit 0 (review 2026-11-11).
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from ducta.core.errors import NodeTimeoutError
from ducta.core.execution.cancellation import is_cancelled
from ducta.core.execution.coordinator import node_timeout_for
from ducta.core.executors.batch import BatchExecutor
from ducta.core.ledger import ledger_for
from tests.core.fakes import FakeContext


class _SlowNode:
    def __init__(self, seconds: float, node_timeout: int = 1800) -> None:
        self.seconds = seconds
        self.node_timeout = node_timeout
        self.finished = threading.Event()
        self.shut_down = False

    def execute_single_node(self, node_name, start_date, end_date, ml_info) -> None:
        time.sleep(self.seconds)
        self.finished.set()

    def shutdown(self) -> None:
        self.shut_down = True


def _batch(context: FakeContext, node: _SlowNode) -> SimpleNamespace:
    return SimpleNamespace(context=context, node_executor=node)


def test_node_over_its_timeout_fails_and_is_cancelled():
    context = FakeContext(nodes_config={"slow": {"timeout": 1}})
    node = _SlowNode(seconds=3)

    started = time.monotonic()
    with pytest.raises(NodeTimeoutError):
        BatchExecutor._execute_atomic_node(_batch(context, node), "slow", None, None, {})  # type: ignore[arg-type]

    assert time.monotonic() - started < 2.5  # did not wait for the node
    assert is_cancelled(context, "slow")
    assert any("exceeded its timeout of 1s" in gap for gap in ledger_for(context).record_failures)
    assert node.shut_down


def test_node_within_its_timeout_succeeds():
    context = FakeContext(nodes_config={"quick": {"timeout": 5}})
    node = _SlowNode(seconds=0.05)

    BatchExecutor._execute_atomic_node(_batch(context, node), "quick", None, None, {})  # type: ignore[arg-type]

    assert node.finished.is_set()
    assert not is_cancelled(context, "quick")


def test_node_error_propagates_unchanged():
    context = FakeContext(nodes_config={"bad": {}})

    class _Failing(_SlowNode):
        def execute_single_node(self, *args) -> None:
            raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        BatchExecutor._execute_atomic_node(_batch(context, _Failing(0)), "bad", None, None, {})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("config", "expected"),
    [({"timeout": 7}, 7), ({}, 30), (None, 30), ({"timeout": "soon"}, 30), ({"timeout": 0}, 30)],
)
def test_node_timeout_for(config, expected):
    assert node_timeout_for(config, 30) == expected
