"""The seam between the config schema and the gate evaluator.

``tests/check/test_gate.py::TestDefaultsAreIndependent`` fixes the *evaluator's*
defaults: out of the box a gate means "any ERROR blocks", and a warning alone
does not. ``tests/setting/test_schemas.py::test_quality_gate_defaults`` fixes the
*schema's* defaults. Both suites passed while the two disagreed about
``min_pass_rate``, because neither crossed the seam between them.

A node's gate config does not reach the evaluator as the user wrote it: it goes
through ``NodeSchema`` and comes back out of ``model_dump(exclude_none=True)``,
which drops ``None`` but keeps every default the schema filled in. So a schema
default is not documentation — it is a value the evaluator will act on, exactly
as if the user had typed it.

These tests walk that whole path: raw config dict → ``NodeSchema`` → dump →
``QualityGateEvaluator``. That is what `ducta start` does, and it is the only
place the disagreement is observable.
"""

from __future__ import annotations

from typing import Any, Dict

from ducta.check.core import CheckResult, CheckSeverity, QualityReport
from ducta.check.gate import GateAction, QualityGateEvaluator
from ducta.setting.schemas import NodeSchema


def _gate_cfg_through_schema(quality_gate: Dict[str, Any]) -> Dict[str, Any]:
    """The gate config as the engine sees it, after schema validation."""
    node = NodeSchema(
        module="nodes",
        function="f",
        input=["a"],
        output=["b"],
        data_quality={"checks": {}, "quality_gate": quality_gate},
    )
    return node.model_dump(exclude_none=True)["data_quality"]["quality_gate"]


def _report(results):
    return QualityReport(dataset_name="d", passed=all(r.passed for r in results), results=results)


def _one_pass_one_warning() -> QualityReport:
    return _report(
        [
            CheckResult("row_count", passed=True),
            CheckResult("freshness", passed=False, severity=CheckSeverity.WARNING),
        ]
    )


class TestSchemaDefaultsDoNotChangeGateSemantics:
    """A default the user never wrote must not decide the run's outcome."""

    def test_warning_alone_does_not_block_after_schema_validation(self):
        """The bug this file exists for.

        A node declaring only ``max_errors: 0`` and ``max_warnings: -1``
        (unlimited warnings) had its run blocked by a *warning*, because the
        schema silently supplied ``min_pass_rate: 1.0`` — a rule that counts
        every failed check regardless of severity.
        """
        cfg = _gate_cfg_through_schema({"max_errors": 0, "max_warnings": -1})

        gate = QualityGateEvaluator.from_config(_one_pass_one_warning(), node_gate_cfg=cfg)

        assert gate is not None
        assert gate.passed, f"a warning must not block; triggered: {gate.triggered_rules}"
        assert gate.action is not GateAction.BLOCK

    def test_matches_the_same_config_without_schema_validation(self):
        """Both load paths must agree.

        ``Context(validate=True)`` (the CLI and API default) sends config through
        the schema; a raw dict built without going through it does not. The same
        YAML must mean the same thing either way.
        """
        raw = {"max_errors": 0, "max_warnings": -1}
        validated = _gate_cfg_through_schema(raw)
        report = _one_pass_one_warning()

        assert (
            QualityGateEvaluator.from_config(report, node_gate_cfg=raw).action
            is QualityGateEvaluator.from_config(report, node_gate_cfg=validated).action
        )

    def test_an_error_still_blocks_after_schema_validation(self):
        """The fix must not disarm the gate — that is what it is for."""
        cfg = _gate_cfg_through_schema({"max_errors": 0})
        report = _report([CheckResult("row_count", passed=False, severity=CheckSeverity.ERROR)])

        gate = QualityGateEvaluator.from_config(report, node_gate_cfg=cfg)

        assert gate is not None
        assert not gate.passed
        assert gate.action is GateAction.BLOCK

    def test_min_pass_rate_still_applies_when_the_user_asks_for_it(self):
        """Written explicitly, the rule must survive the round trip."""
        cfg = _gate_cfg_through_schema({"max_errors": 0, "min_pass_rate": 1.0})

        gate = QualityGateEvaluator.from_config(_one_pass_one_warning(), node_gate_cfg=cfg)

        assert gate is not None
        assert not gate.passed
        assert any("min_pass_rate" in rule for rule in gate.triggered_rules)
