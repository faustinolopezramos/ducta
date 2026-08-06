"""
Copyright (C) 2024-2026 Faustino Lopez Ramos

This file is part of ducta.

Licensed under the Apache License, Version 2.0 (the "License"); you may not
use this file except in compliance with the License. You may obtain a copy
of the License at

    https://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
License for the specific language governing permissions and limitations
under the License.

SPDX-License-Identifier: Apache-2.0

"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from loguru import logger  # type: ignore

from ducta.check.core import CheckSeverity, QualityConfigError, QualityReport


class GateAction(str, Enum):
    PASS = "pass"
    WARN = "warn"
    BLOCK = "block"


class GateBehavior(str, Enum):
    """What happens to the pipeline when a gate blocks a node."""

    SKIP_DOWNSTREAM = "skip_downstream"
    STOP_ALL = "stop_all"
    WARN_ONLY = "warn_only"


@dataclass
class GateResult:
    gate_name: str
    passed: bool
    score: float
    action: GateAction
    triggered_rules: List[str] = field(default_factory=list)
    dataset_name: str = ""
    run_id: Optional[str] = None
    behavior: GateBehavior = GateBehavior.SKIP_DOWNSTREAM
    evaluated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "gate_name": self.gate_name,
            "passed": self.passed,
            "score": self.score,
            "action": self.action.value,
            "triggered_rules": self.triggered_rules,
            "dataset_name": self.dataset_name,
            "run_id": self.run_id,
            "behavior": self.behavior.value,
            "evaluated_at": self.evaluated_at,
        }


class QualityGateEvaluator:
    """Evaluates quality gates based on report scores and thresholds."""

    @staticmethod
    def compute_score(report: QualityReport, weights: Dict[str, float]) -> float:
        """Compute a weighted quality score from a report."""
        if not report.results:
            return 1.0

        total_weight = 0.0
        weighted_sum = 0.0

        for res in report.results:
            w = weights.get(res.check_name, 1.0)
            total_weight += w
            if res.passed:
                weighted_sum += w
            elif res.severity == CheckSeverity.WARNING:
                # Warnings contribute 50% of their weight to the score
                weighted_sum += w * 0.5

        return weighted_sum / total_weight if total_weight > 0 else 1.0

    @classmethod
    def from_config(
        cls,
        report: QualityReport,
        node_gate_cfg: Optional[Dict[str, Any]] = None,
        global_gate_cfg: Optional[Dict[str, Any]] = None,
    ) -> Optional[GateResult]:
        """Evaluate a gate from combined configuration."""
        # Merge configs (node takes precedence)
        cfg = (global_gate_cfg or {}).copy()
        if node_gate_cfg and isinstance(node_gate_cfg, dict):
            cfg.update(node_gate_cfg)

        if not cfg or not cfg.get("enabled", True):
            return None

        gate_name = cfg.get("gate_name") or cfg.get("name") or "quality_gate"
        weights = cfg.get("score_weights") or {}
        # Coerced under one try/except so a malformed value (e.g. `max_errors:
        # null` — a plausible typo when someone means "disable this") raises a
        # clear, catchable QualityConfigError instead of a raw TypeError/
        # ValueError. The caller (engine.py) must not swallow this: a gate the
        # user explicitly configured has to fail closed, not silently pass,
        # when it can't be evaluated.
        try:
            max_errors = int(cfg.get("max_errors", 0))
            max_warnings = int(cfg.get("max_warnings", -1))
            # Default 0.0 = off. It used to default to 1.0, which contradicted
            # `max_warnings: -1` sitting right above it: the pass rate counts
            # every failed check regardless of severity, so a gate configured
            # with nothing but `enabled: true` blocked on the very warnings the
            # other knob declared tolerable. Each knob is now independent, and
            # the out-of-the-box gate means exactly one thing: any ERROR blocks.
            min_pass_rate = float(cfg.get("min_pass_rate", 0.0))
            score_threshold = float(cfg.get("score_threshold", 0.0))
            # Optional legacy thresholds. Coerced here rather than at the use
            # site so a malformed value raises QualityConfigError like every
            # other key instead of a raw TypeError from `float(None)`.
            raw_block = cfg.get("block_threshold")
            raw_warn = cfg.get("warn_threshold")
            block_threshold = float(raw_block) if raw_block is not None else None
            warn_threshold = float(raw_warn) if raw_warn is not None else None
        except (TypeError, ValueError) as e:
            raise QualityConfigError(
                f"Invalid quality gate config for '{gate_name}': {e}. "
                "'max_errors'/'max_warnings' must be integers, "
                "'min_pass_rate'/'score_threshold'/'block_threshold'/'warn_threshold' "
                "must be numbers."
            ) from e
        required_checks = cfg.get("required_checks") or []
        raw_behavior = str(cfg.get("behavior", GateBehavior.SKIP_DOWNSTREAM.value))
        aliases = {"block": GateBehavior.STOP_ALL.value, "warn": GateBehavior.WARN_ONLY.value}
        normalized = aliases.get(raw_behavior, raw_behavior)
        try:
            behavior = GateBehavior(normalized)
        except ValueError:
            logger.warning(
                "Unknown gate behavior '{}' for gate '{}'; falling back to '{}'. "
                "Valid values: skip_downstream, stop_all, warn_only.",
                raw_behavior,
                gate_name,
                GateBehavior.SKIP_DOWNSTREAM.value,
            )
            behavior = GateBehavior.SKIP_DOWNSTREAM

        # Compute score
        score = cls.compute_score(report, weights)

        # Evaluate rules
        triggered = []
        action = GateAction.PASS
        passed = True

        def _block(rule: str) -> None:
            nonlocal action, passed
            action = GateAction.BLOCK
            passed = False
            triggered.append(rule)

        def _warn(rule: str) -> None:
            nonlocal action
            if action != GateAction.BLOCK:
                action = GateAction.WARN
            triggered.append(rule)

        errors = report.errors_count
        warnings = report.warnings_count
        if max_errors >= 0 and errors > max_errors:
            _block(f"{errors} ERROR failure(s) exceed max_errors {max_errors}")

        if max_warnings >= 0 and warnings > max_warnings:
            _warn(f"{warnings} WARNING failure(s) exceed max_warnings {max_warnings}")

        if min_pass_rate > 0 and report.results:
            pass_rate = sum(1 for r in report.results if r.passed) / len(report.results)
            if pass_rate < min_pass_rate:
                _block(f"Pass rate {pass_rate:.4f} below min_pass_rate {min_pass_rate}")

        if score_threshold > 0 and score < score_threshold:
            _block(f"Score {score:.4f} below score_threshold {score_threshold}")

        # required_checks must pass; a missing check also blocks.
        for check_name in required_checks:
            res = next((r for r in report.results if r.check_name == check_name), None)
            if res is None:
                _block(f"Required check '{check_name}' did not run")
            elif not res.passed:
                _block(f"Required check '{check_name}' failed")

        # Legacy score thresholds, only when explicitly configured.
        if block_threshold is not None and score < block_threshold:
            _block(f"Score {score:.4f} below block_threshold {block_threshold}")
        elif warn_threshold is not None and score < warn_threshold:
            _warn(f"Score {score:.4f} below warn_threshold {warn_threshold}")

        # Legacy mandatory_checks: blocks on failure (absence tolerated).
        for check_name in cfg.get("mandatory_checks") or []:
            res = next((r for r in report.results if r.check_name == check_name), None)
            if res and not res.passed:
                _block(f"Mandatory check '{check_name}' failed")

        return GateResult(
            gate_name=gate_name,
            passed=passed,
            score=score,
            action=action,
            triggered_rules=triggered,
            dataset_name=report.dataset_name,
            run_id=report.run_id,
            behavior=behavior,
        )
