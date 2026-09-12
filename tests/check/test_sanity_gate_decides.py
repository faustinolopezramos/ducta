"""A declared ``sanity_gate`` must decide the node's fate, like a DQ gate does.

The sanity phase defaults to ``fail_fast: true``, and that raise happened inside
the per-check loop — *before* the gate was ever evaluated. So a node declaring a
``sanity_gate`` got the gate it configured only in the sense that the object was
built: the first ERROR-severity failure aborted the node first.

Concretely, ``sanity_gate: {behavior: warn_only}`` — which says "log this and
carry on" — hard-failed the node, and ``skip_downstream`` surfaced as a *failed*
node rather than a blocked one, so the run came back FAILED instead of
GATE_BLOCKED and no descendant-skip cascade ran.

Fail-fast itself is untouched when no gate is declared: that is the documented
behaviour of this phase and the reason its default differs from data_quality's.
"""

from __future__ import annotations

import pandas as pd
import pytest

from ducta.check.core import QualityChecksFailed, QualityGateBlocked
from ducta.core.errors import SanityCheckFailedError
from ducta.core.execution.quality import QualityCheckExecutor


class _Ctx:
    global_config: dict = {}
    nodes_config: dict = {}


@pytest.fixture
def executor() -> QualityCheckExecutor:
    return QualityCheckExecutor(_Ctx())


@pytest.fixture
def frame() -> pd.DataFrame:
    return pd.DataFrame({"id": [1, 2, 3]})


#: Fails cleanly: three rows against a floor of a thousand.
FAILING_CHECK = {"row_count": {"min": 1000}}


def _run(executor, frame, sanity):
    return executor.run_sanity_checks([frame], {"sanity_checks": sanity}, "n")


class TestGateDecidesWhenDeclared:
    def test_skip_downstream_blocks_rather_than_fails(self, executor, frame):
        """The verdict the coordinator turns into a descendant-skip cascade."""
        with pytest.raises(QualityGateBlocked):
            _run(
                executor,
                frame,
                {
                    "enabled": True,
                    "checks": FAILING_CHECK,
                    "sanity_gate": {"max_errors": 0, "behavior": "skip_downstream"},
                },
            )

    def test_warn_only_lets_the_node_continue(self, executor, frame):
        """The case that proved the gate was not being consulted at all."""
        report = _run(
            executor,
            frame,
            {
                "enabled": True,
                "checks": FAILING_CHECK,
                "sanity_gate": {"max_errors": 0, "behavior": "warn_only"},
            },
        )

        assert report is not None
        assert not report.passed, "the failure is still reported, just not fatal"

    def test_a_gate_within_budget_lets_the_node_continue(self, executor, frame):
        report = _run(
            executor,
            frame,
            {
                "enabled": True,
                "checks": FAILING_CHECK,
                "sanity_gate": {"max_errors": 5, "behavior": "skip_downstream"},
            },
        )

        assert report is not None


class TestFailFastSurvivesWithoutAGate:
    """The phase's documented default must not be softened by the fix."""

    def test_default_fail_fast_still_aborts(self, executor, frame):
        from ducta.check.core import QualityCheckError

        with pytest.raises((QualityCheckError, SanityCheckFailedError)):
            _run(executor, frame, {"enabled": True, "checks": FAILING_CHECK})

    def test_fail_fast_false_still_collects_and_raises(self, executor, frame):
        with pytest.raises(QualityChecksFailed):
            _run(
                executor,
                frame,
                {"enabled": True, "fail_fast": False, "checks": FAILING_CHECK},
            )

    def test_passing_checks_are_unaffected(self, executor, frame):
        report = _run(executor, frame, {"enabled": True, "checks": {"row_count": {"min": 1}}})

        assert report is not None
        assert report.passed
