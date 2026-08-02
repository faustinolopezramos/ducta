"""Unit tests for ducta.check.gate.QualityGateEvaluator."""

from __future__ import annotations

from ducta.check.core import CheckResult, CheckSeverity, QualityReport
from ducta.check.gate import GateAction, GateBehavior, QualityGateEvaluator


def _report(results):
    passed = all(r.passed for r in results)
    return QualityReport(dataset_name="d", passed=passed, results=results)


class TestComputeScore:
    def test_all_pass_is_one(self):
        report = _report([CheckResult("a", passed=True), CheckResult("b", passed=True)])
        assert QualityGateEvaluator.compute_score(report, {}) == 1.0

    def test_error_failure_lowers_score(self):
        report = _report(
            [
                CheckResult("a", passed=False, severity=CheckSeverity.ERROR),
                CheckResult("b", passed=True),
            ]
        )
        assert QualityGateEvaluator.compute_score(report, {}) == 0.5

    def test_warning_counts_half(self):
        report = _report([CheckResult("a", passed=False, severity=CheckSeverity.WARNING)])
        assert QualityGateEvaluator.compute_score(report, {}) == 0.5

    def test_empty_report_is_one(self):
        assert QualityGateEvaluator.compute_score(_report([]), {}) == 1.0


class TestFromConfig:
    def test_disabled_returns_none(self):
        report = _report([CheckResult("a", passed=True)])
        assert QualityGateEvaluator.from_config(report, {"enabled": False}) is None

    def test_max_errors_blocks(self):
        report = _report([CheckResult("a", passed=False, severity=CheckSeverity.ERROR)])
        gate = QualityGateEvaluator.from_config(report, {"max_errors": 0})
        assert gate.action == GateAction.BLOCK
        assert gate.passed is False

    def test_errors_within_budget_passes(self):
        report = _report([CheckResult("a", passed=False, severity=CheckSeverity.ERROR)])
        # min_pass_rate=0 disables the pass-rate rule so we isolate max_errors
        gate = QualityGateEvaluator.from_config(report, {"max_errors": 1, "min_pass_rate": 0})
        assert gate.action == GateAction.PASS
        assert gate.passed is True

    def test_required_check_missing_blocks(self):
        report = _report([CheckResult("a", passed=True)])
        gate = QualityGateEvaluator.from_config(
            report, {"max_errors": 5, "required_checks": ["not_run"]}
        )
        assert gate.action == GateAction.BLOCK

    def test_min_pass_rate_blocks(self):
        report = _report([CheckResult("a", passed=True), CheckResult("b", passed=False)])
        gate = QualityGateEvaluator.from_config(report, {"max_errors": 5, "min_pass_rate": 0.9})
        assert gate.action == GateAction.BLOCK

    def test_behavior_alias_block_maps_to_stop_all(self):
        report = _report([CheckResult("a", passed=True)])
        gate = QualityGateEvaluator.from_config(report, {"behavior": "block"})
        assert gate.behavior == GateBehavior.STOP_ALL

    def test_default_behavior_skip_downstream(self):
        report = _report([CheckResult("a", passed=True)])
        gate = QualityGateEvaluator.from_config(report, {"max_errors": 0})
        assert gate.behavior == GateBehavior.SKIP_DOWNSTREAM

    def test_max_errors_negative_means_unlimited(self):
        # Regression: max_errors=-1 must mean "unlimited" like max_warnings already
        # does, not "block on any error" (errors(>=0) > -1 was always true before).
        report = _report([CheckResult("a", passed=False, severity=CheckSeverity.ERROR)])
        gate = QualityGateEvaluator.from_config(report, {"max_errors": -1, "min_pass_rate": 0})
        assert gate.action == GateAction.PASS
        assert gate.passed is True

    def test_node_config_overrides_global(self):
        report = _report([CheckResult("a", passed=False, severity=CheckSeverity.ERROR)])
        gate = QualityGateEvaluator.from_config(
            report,
            node_gate_cfg={"max_errors": 5, "min_pass_rate": 0},
            global_gate_cfg={"max_errors": 0},
        )
        # node's more lenient max_errors wins -> passes
        assert gate.action == GateAction.PASS
