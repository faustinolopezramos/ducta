"""A quality verdict is a decision, not an unknown error.

``classify_error`` matched regexes against the exception's *message*, so a
blocked quality gate — an outcome the engine deliberately produces, with the
exact rules it tripped on attached — was rendered as:

    ❌ Unknown Error in node 'transform'

which tells the reader something broke and gives them nothing to act on. The
function had accepted the exception object all along and never looked at it.
"""

from __future__ import annotations

import pytest

from ducta.check.core import QualityGateBlocked
from ducta.check.gate import GateAction, GateBehavior, GateResult
from ducta.console.ux.error_analyzer import classify_error


def _blocked() -> QualityGateBlocked:
    gate_result = GateResult(
        gate_name="quality_gate",
        passed=False,
        score=0.66,
        action=GateAction.BLOCK,
        triggered_rules=["1 ERROR failure(s) exceed max_errors 0"],
        dataset_name="transform",
        behavior=GateBehavior.SKIP_DOWNSTREAM,
    )
    return QualityGateBlocked(gate_result=gate_result, dataset_name="transform")


class TestQualityGateClassification:
    def test_a_blocked_gate_is_not_an_unknown_error(self):
        error = _blocked()

        analysis = classify_error(str(error), error)

        assert analysis["error_type"] == "Quality Gate Blocked"
        assert analysis["error_type"] != "Unknown Error"

    def test_it_surfaces_the_rules_that_tripped(self):
        """The actionable part: which rule, not just that something failed."""
        error = _blocked()

        analysis = classify_error(str(error), error)

        assert any("max_errors" in s for s in analysis["suggestions"])

    def test_it_is_not_flagged_as_a_high_severity_defect(self):
        error = _blocked()

        analysis = classify_error(str(error), error)

        assert analysis["severity"] != "high"

    def test_the_gate_name_is_carried(self):
        error = _blocked()

        analysis = classify_error(str(error), error)

        assert analysis["context"].get("gate") == "quality_gate"


class TestOrdinaryErrorsAreUnaffected:
    def test_a_real_exception_still_classifies_normally(self):
        analysis = classify_error("boom", RuntimeError("boom"))

        assert analysis["error_type"] == "Unknown Error"
        assert analysis["severity"] == "high"

    def test_a_recognised_spark_error_still_matches_its_pattern(self):
        msg = "cannot resolve 'amount' given input columns: [id, name]"

        analysis = classify_error(msg, RuntimeError(msg))

        assert analysis["error_type"] == "Column Not Found"

    def test_no_exception_object_still_works(self):
        analysis = classify_error("something went wrong")

        assert analysis["error_type"] == "Unknown Error"
