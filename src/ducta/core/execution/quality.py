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

Sanity and data-quality phases around a node's execution.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from loguru import logger  # type: ignore

from ducta.check import (
    QualityOutputConfig,
    QualityReport,
    QualityReporter,
    SanityPhaseRunner,
)
from ducta.core.errors import SanityCheckFailedError
from ducta.core.ledger import ledger_for
from ducta.core.settings import CoreSettings


class QualityCheckExecutor:
    """Runs pre- and post-execution quality checks for a node."""

    DEFAULT_ML_SANITY_CONFIG = {
        "enabled": True,
        "fail_fast": True,
        "checks": {"empty_dataset": {}},
    }

    def __init__(
        self,
        context: Any,
        quality_output_manager: Optional[Any] = None,
        settings: Optional[CoreSettings] = None,
    ) -> None:
        self.context = context
        self.settings = settings or CoreSettings.from_context(context)
        self._ledger = ledger_for(context)
        self.quality_output_manager = quality_output_manager

    def _load_quality_profiles(self) -> Dict[str, Any]:
        """Load quality profiles from global_config."""
        try:
            from ducta.check.profiles import load_profiles as _load_profiles

            gs = getattr(self.context, "global_config", {}) or {}
            return _load_profiles(gs) if isinstance(gs, dict) else {}
        except Exception:
            return {}

    def _ml_default_sanity_enabled(self) -> bool:
        """Whether global config allow the default ML sanity checks (on by default)."""
        return self.settings.ml_default_sanity_checks

    def _deposit_quality_summary(self, node_name: str, phase: str, report: Any) -> None:
        """Record a compact quality summary on the context so it reaches the certificate.

        Deposited for every node whose checks ran and did not abort (pass or
        warn_only) — no ``output.enabled`` required. Best-effort; never raises.
        """
        if report is None:
            return
        try:
            entry = {
                "node": node_name,
                "phase": phase,
                "passed": bool(getattr(report, "passed", True)),
                "score": round(float(getattr(report, "score", 1.0)), 4),
                "errors": int(getattr(report, "errors_count", 0)),
                "warnings": int(getattr(report, "warnings_count", 0)),
                "checks": int(getattr(report, "checks_count", 0)),
            }
            self._ledger.record_quality(entry)
        except Exception as e:  # noqa: BLE001
            logger.debug("Could not deposit quality summary for '{}': {}", node_name, e)

    def _deposit_quality_abort(self, node_name: str, phase: str, error: Exception) -> None:
        """Record the quality outcome that *aborted* the run."""
        try:
            entry: Dict[str, Any] = {
                "node": node_name,
                "phase": phase,
                "passed": False,
                "score": 0.0,
                "errors": int(getattr(error, "errors_count", 1) or 1),
                "warnings": int(getattr(error, "warnings_count", 0) or 0),
                "checks": len(getattr(error, "results", []) or []),
                "aborted": True,
                "reason": str(error),
            }
            gate_result = getattr(error, "gate_result", None)
            if gate_result is not None:
                entry["gate"] = getattr(gate_result, "gate_name", None)
                entry["triggered_rules"] = list(getattr(gate_result, "triggered_rules", []) or [])
            self._ledger.record_quality(entry)
        except Exception as e:  # noqa: BLE001
            logger.debug("Could not deposit quality abort for '{}': {}", node_name, e)

    def run_sanity_checks(
        self,
        dfs: List[Any],
        node_config: Dict[str, Any],
        node_name: str,
        pipeline_type: Optional[str] = None,
        pipeline_name: Optional[str] = None,
    ) -> Optional[QualityReport]:
        """Run sanity checks on node input DataFrames if configured."""
        sanity_config = node_config.get("sanity_checks")
        if sanity_config is None and pipeline_type == "ml" and self._ml_default_sanity_enabled():
            sanity_config = self.DEFAULT_ML_SANITY_CONFIG
            node_config = {**node_config, "sanity_checks": sanity_config}
            logger.info(
                "Node '{}': applying default ML sanity checks ({}). Disable with "
                "sanity_checks.enabled=false on the node or "
                "global_config.ml_default_sanity_checks=false.",
                node_name,
                ", ".join(sanity_config["checks"]),
            )
        if not sanity_config or not sanity_config.get("enabled", True):
            return None

        profiles = self._load_quality_profiles()
        runner = SanityPhaseRunner(
            fail_fast=sanity_config.get("fail_fast", True), profiles=profiles
        )
        run_kwargs = {"pipeline_name": pipeline_name} if pipeline_name else {}
        report = runner.run_node_checks(dfs, node_config, node_name, **run_kwargs)

        QualityReporter().render_report(report)

        self._deposit_quality_summary(node_name, "sanity", report)

        # A node that declared a sanity_gate has already been judged by it inside
        # the runner: a blocking verdict raised QualityGateBlocked and never got
        # here, and reaching this line means the gate passed the node or was set
        # to warn_only. Failing it now would overrule the gate's own decision —
        # `warn_only` in particular means "log this and carry on", and this line
        # turned it into a hard node failure.
        gate_decided = bool(sanity_config.get("sanity_gate"))
        if not gate_decided and not report.passed and sanity_config.get("fail_fast", True):
            raise SanityCheckFailedError(node_name, report.errors_count)

        return report

    def run_dq_checks(
        self,
        result_df: Any,
        node_config: Dict[str, Any],
        node_name: str,
        context_dfs: Optional[Dict[str, Any]] = None,
        pipeline_name: Optional[str] = None,
    ) -> Optional[Any]:
        """Run data quality checks on node output if configured."""
        dq_config = node_config.get("data_quality")
        if not dq_config or not dq_config.get("enabled", True):
            return None

        if result_df is None:
            logger.debug(f"Skipping DQ checks for '{node_name}': result_df is None")
            return None

        try:
            from ducta.check import ValidationPhaseRunner

            profiles = self._load_quality_profiles()
            _global_gate_cfg = self.settings.quality.get("gate")
            runner = ValidationPhaseRunner(
                context=self.context,
                fail_fast=dq_config.get("fail_fast", False),
                profiles=profiles,
                global_gate_config=_global_gate_cfg,
            )

            dataset_name = dq_config.get("dataset_name", node_name)
            run_id = dq_config.get("run_id")

            run_kwargs = {"pipeline_name": pipeline_name} if pipeline_name else {}
            report = runner.run(
                dataset_name=dataset_name,
                df=result_df,
                config=dq_config,
                context_datasets=context_dfs,
                run_id=run_id,
                **run_kwargs,
            )

            reporter = QualityReporter()
            reporter.render_report(report)

            if not report.passed:
                failed_count = sum(1 for r in report.results if not r.passed)
                logger.warning(
                    f"Data quality: {failed_count} failed check(s) for '{dataset_name}' "
                    f"(run {report.run_id}); continuing. Set data_quality.fail_fast=true "
                    "to abort on error-severity failures."
                )

            self._deposit_quality_summary(node_name, "data_quality", report)
            return report

        except Exception as e:
            from ducta.check import QualityChecksFailed
            from ducta.check.core import QualityGateBlocked

            if isinstance(e, (QualityGateBlocked, QualityChecksFailed)):
                self._deposit_quality_abort(node_name, "data_quality", e)
                raise
            logger.error(f"Data quality check execution failed for node '{node_name}': {e}")
            if dq_config.get("fail_fast", False):
                self._deposit_quality_abort(node_name, "data_quality", e)
                raise
            return None

    def _create_quality_output_config(
        self, config_dict: Dict[str, Any]
    ) -> Optional[QualityOutputConfig]:
        """Create QualityOutputConfig from node configuration dictionary."""
        if not config_dict:
            return None

        if not config_dict.get("enabled", False):
            return None

        try:
            return QualityOutputConfig(
                enabled=config_dict.get("enabled", False),
                format=config_dict.get("format", "parquet"),
                write_mode=config_dict.get("write_mode", "overwrite"),
                partition_by=config_dict.get("partition_by"),
                per_node=config_dict.get("per_node", True),
                global_summary=config_dict.get("global_summary", False),
                base_path=config_dict.get("base_path"),
            )
        except Exception as e:
            logger.error(f"Failed to create quality output config: {e}")
            return None

    def persist_report(
        self,
        report: Any,
        report_type: str,
        config_key: str,
        node_name: str,
        node_config: Dict[str, Any],
        ml_info: Dict[str, Any],
        pipeline_name: Optional[str] = None,
    ) -> None:
        """Persist quality report and register output path."""
        if not report or not self.quality_output_manager:
            return
        try:
            config_dict = node_config.get(config_key, {}).get("output", {})
            if not config_dict:
                global_quality = self.settings.quality
                global_output = global_quality.get("output", {})
                if not global_output or not global_quality.get("enabled", False):
                    return
                config_dict = {**global_output, "enabled": True}
            output_config = self._create_quality_output_config(config_dict)
            if not output_config:
                return
            persist_kwargs = {"pipeline_name": pipeline_name} if pipeline_name else {}
            output_path = self.quality_output_manager.persist_quality_report(
                report=report,
                node_name=node_name,
                run_id=ml_info.get("run_id", f"run_{int(time.time())}"),
                config=output_config,
                report_type=report_type,
                **persist_kwargs,
            )
            if output_path and self.context and hasattr(self.context, "add_quality_output_path"):
                self.context.add_quality_output_path(output_path)
        except Exception as e:
            logger.error(f"Failed to persist {report_type} report for node {node_name}: {e}")
