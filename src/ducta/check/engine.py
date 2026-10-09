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

import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger  # type: ignore

from ducta.check.core import (
    QUALITY_CHECKS_REGISTRY,
    CheckResult,
    CheckSeverity,
    DFAdapter,
    QualityCheckError,
    QualityChecksFailed,
    QualityConfigError,
    QualityGateBlocked,
    QualityReport,
)
from ducta.check.profiles import QualityProfile, apply_auto_tune, resolve_checks_config
from ducta.check.storage import (
    DEFAULT_PIPELINE_NAME,
    ContextAwareStorageBackend,
    FileStorageBackend,
    StorageBackend,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


#: Default quality storage, under ``${output_path}/${environment}``: visible, so a
#: project can browse or ship its reports (see "Ducta storage convention").
QUALITY_DIR_NAME = "quality"
#: The pre-convention default, still used where it already holds a history.
LEGACY_QUALITY_DIR_NAME = ".quality"


def _default_quality_dir(env_root: Path) -> str:
    """``<env_root>/quality``, or ``<env_root>/.quality`` if only the legacy one exists.

    Baselines and score history live in this directory, so a project that already
    has them under the old hidden name keeps using it rather than starting over.
    Renaming the directory to ``quality`` moves the project to the new default.
    """
    current = env_root / QUALITY_DIR_NAME
    legacy = env_root / LEGACY_QUALITY_DIR_NAME
    if not current.exists() and legacy.is_dir():
        logger.info(
            f"Quality reports stay in legacy '{legacy}'; rename it to '{current}' "
            "to use the current default."
        )
        return str(legacy)
    return str(current)


def _raise_or_warn_gate(gate_result: Any, dataset_name: str, run_id: Optional[str] = None) -> None:
    """Apply a failed gate's ``behavior``.

    ``warn_only`` logs and lets the node proceed; ``skip_downstream`` and
    ``stop_all`` raise :class:`QualityGateBlocked` (carrying the behavior) so the
    executor can skip descendants or abort. Kept here so both the sanity and
    data-quality gate sites share one policy.
    """
    behavior = getattr(getattr(gate_result, "behavior", None), "value", None) or str(
        getattr(gate_result, "behavior", "skip_downstream")
    )
    if behavior == "warn_only":
        logger.warning(
            "Quality gate '{}' failed for '{}' (score {:.4f}) but behavior=warn_only; continuing. "
            "Triggered: {}",
            getattr(gate_result, "gate_name", "quality_gate"),
            dataset_name,
            getattr(gate_result, "score", 0.0),
            getattr(gate_result, "triggered_rules", []),
        )
        return
    raise QualityGateBlocked(gate_result=gate_result, dataset_name=dataset_name, run_id=run_id)


def _replace_result(
    result: "CheckResult",
    *,
    check_name: Optional[str] = None,
    severity: Optional[CheckSeverity] = None,
) -> "CheckResult":
    """Rebuild *result* with one or more fields overridden, carrying over
    everything else — including ``executed_at``, so a rebuilt copy still
    reports when the check actually ran, not when it was rebuilt. Shared by
    ``_rename_result`` and ``_apply_configured_severity``."""
    return result.__class__(
        check_name=check_name if check_name is not None else result.check_name,
        passed=result.passed,
        severity=severity if severity is not None else result.severity,
        message=result.message,
        details=result.details,
        executed_at=result.executed_at,
    )


def _rename_result(result: "CheckResult", check_name: str) -> "CheckResult":
    return _replace_result(result, check_name=check_name)


def _configured_severity(
    check_config_dict: Dict[str, Any], check_name: str
) -> Optional[CheckSeverity]:
    """Resolve a node's ``severity`` override, or ``None`` if it declared none.

    Resolved *before* the check runs so a typo is reported as what it is — a
    configuration error — instead of being swallowed by the execution-error
    handler and surfacing as "check execution failed", which points the reader
    at their data rather than at their config.
    """
    raw = check_config_dict.get("severity")
    if raw is None:
        return None
    try:
        return CheckSeverity.from_str(raw)
    except ValueError as e:
        raise QualityConfigError(f"Invalid severity for check '{check_name}': {e}") from e


def _apply_configured_severity(
    result: "CheckResult", severity: Optional[CheckSeverity]
) -> "CheckResult":
    """Re-stamp a result with the severity the node's check config asked for.

    Each check hard-codes a severity on its class, and ``_create_result``
    resolves it as ``severity or self.severity`` — so a ``severity: "warning"``
    written on a node's check was accepted by the config object and then read by
    nothing. The check stayed an ERROR and still blocked at
    ``quality_gate.max_errors``, which is the opposite of what the key asks for.
    Downgrading is the whole point of it, so it is applied here, at the one
    place holding both the result and the config that produced it.
    """
    if severity is None or severity == result.severity:
        return result
    return _replace_result(result, severity=severity)


def _build_execution_error_result(check_name: str, exc: Exception) -> "CheckResult":
    return CheckResult(
        check_name=check_name,
        passed=False,
        severity=CheckSeverity.ERROR,
        message=f"Check execution failed: {str(exc)}",
        details={"error": str(exc)},
    )


def _build_unknown_check_type_result(check_name: str, registry_key: str) -> "CheckResult":
    # A check referenced by a name/type not in QUALITY_CHECKS_REGISTRY used to
    # just log a warning and be skipped — a typo in `type:` (or a quality
    # extension that failed to load) silently dropped the check from the
    # report entirely, so `report.passed`/`errors_count` never reflected it.
    return CheckResult(
        check_name=check_name,
        passed=False,
        severity=CheckSeverity.ERROR,
        message=f"Check type '{registry_key}' not found in registry",
        details={"registry_key": registry_key},
    )


class QualityReporter:
    def __init__(self) -> None:
        self.rich_available = False
        try:
            from rich.console import Console  # noqa: F401

            self.rich_available = True
        except ImportError:
            pass

    def _rich(self):
        from rich.console import Console  # type: ignore

        return Console()

    def render_report(self, report: QualityReport, verbose: bool = False) -> None:
        if not report:
            logger.warning("No quality report to render")
            return

        if self.rich_available:
            from rich.table import Table  # type: ignore

            console = self._rich()
            table = Table(title=f"Quality Check Report: {report.dataset_name}")
            table.add_column("Check", style="cyan")
            table.add_column("Status", style="magenta")
            table.add_column("Severity", style="yellow")
            table.add_column("Message", style="white")
            for r in report.results:
                ok, sev = r.passed, r.severity
                table.add_row(
                    r.check_name,
                    f"[{'green' if ok else 'red'}]{'✓ PASS' if ok else '✗ FAIL'}[/]",
                    f"[{'red' if sev == CheckSeverity.ERROR else 'yellow'}]{sev.value}[/]",
                    r.message[:80],
                )
            console.print(table)
            console.print(
                f"[{'green' if report.passed else 'red'}]Overall: {'PASS' if report.passed else 'FAIL'} ({report.errors_count} errors, {report.warnings_count} warnings) in {report.elapsed_seconds:.2f}s[/]"
            )
            if verbose:
                for r in report.results:
                    if r.details:
                        console.print(f"  {r.check_name}: {r.details}")
        else:
            logger.info(
                f"Quality Check Report: {report.dataset_name} [{'PASS' if report.passed else 'FAIL'}] ({report.errors_count} errors, {report.warnings_count} warnings, {report.elapsed_seconds:.2f}s)"
            )
            for r in report.results:
                logger.log(
                    "ERROR" if r.is_error else "WARNING" if r.is_warning else "INFO",
                    f"  {'✓' if r.passed else '✗'} {r.check_name}: {r.message}",
                )
                if verbose and r.details:
                    logger.debug(f"    Details: {r.details}")

    def render_summary(self, reports: List[QualityReport], verbose: bool = False) -> None:
        if not reports:
            logger.warning("No quality reports to render")
            return
        total_passed = sum(1 for r in reports if r.passed)
        total_errors = sum(r.errors_count for r in reports)
        total_warnings = sum(r.warnings_count for r in reports)
        if self.rich_available:
            from rich.table import Table  # type: ignore

            console = self._rich()
            table = Table(title="Quality Check Summary")
            table.add_column("Dataset", style="cyan")
            table.add_column("Status", style="magenta")
            table.add_column("Errors", style="red")
            table.add_column("Warnings", style="yellow")
            table.add_column("Checks", style="blue")
            for r in reports:
                table.add_row(
                    r.dataset_name,
                    f"[{'green' if r.passed else 'red'}]{'✓ PASS' if r.passed else '✗ FAIL'}[/]",
                    str(r.errors_count),
                    str(r.warnings_count),
                    str(r.checks_count),
                )
            console.print(table)
            console.print(
                f"{'[green]ALL PASSED[/green]' if len(reports) == total_passed else '[red]SOME FAILED[/red]'} - {total_passed}/{len(reports)} datasets passed ({total_errors} total errors, {total_warnings} total warnings)"
            )
            if verbose:
                for r in reports:
                    for res in r.results:
                        if not res.passed:
                            console.print(f"  {r.dataset_name}.{res.check_name}: {res.message}")
        else:
            logger.info(
                f"Quality Check Summary: {total_passed}/{len(reports)} passed ({total_errors} errors, {total_warnings} warnings)"
            )
            for r in reports:
                logger.info(
                    f"  {'✓ PASS' if r.passed else '✗ FAIL'} {r.dataset_name} ({r.errors_count} errors, {r.warnings_count} warnings)"
                )
                if verbose:
                    for res in r.results:
                        if not res.passed:
                            logger.warning(f"    {res.check_name}: {res.message}")

    def render_pipeline_summary(
        self, reports: Any, show_details: bool = False, verbose: bool = False
    ) -> None:
        """Alias for render_summary that handles both dicts and lists of reports."""
        if isinstance(reports, dict):
            report_list = list(reports.values())
        elif isinstance(reports, list):
            report_list = reports
        else:
            logger.warning(f"Unsupported reports type for summary: {type(reports)}")
            return

        self.render_summary(report_list, verbose=show_details or verbose)

    def render_gate_result(self, gate_result: Any) -> None:
        action = getattr(gate_result, "action", None)
        action_str = action.value.upper() if action else "UNKNOWN"
        score = getattr(gate_result, "score", 0.0)
        triggered = getattr(gate_result, "triggered_rules", [])
        gate_name = getattr(gate_result, "gate_name", "quality_gate")
        dataset_name = getattr(gate_result, "dataset_name", "?")
        action_color = {"PASS": "green", "WARN": "yellow", "BLOCK": "red"}.get(action_str, "white")
        if self.rich_available:
            from rich.table import Table  # type: ignore

            console = self._rich()
            table = Table(title=f"Quality Gate: {gate_name} — {dataset_name}")
            table.add_column("Field", style="cyan")
            table.add_column("Value")
            table.add_row("Action", f"[{action_color}]{action_str}[/{action_color}]")
            table.add_row("Score", f"{score:.4f}")
            for i, rule in enumerate(triggered, 1):
                table.add_row(f"  Rule {i}", rule)
            console.print(table)
        else:
            level = (
                "INFO" if action_str == "PASS" else ("WARNING" if action_str == "WARN" else "ERROR")
            )
            logger.log(
                level,
                f"Quality Gate '{gate_name}' [{action_str}] score={score:.4f} dataset='{dataset_name}'",
            )
            for rule in triggered:
                logger.log(level, f"  Triggered: {rule}")

    def render_pipeline_score(self, pipeline_score: Any) -> None:
        sanity = getattr(pipeline_score, "sanity_score", 1.0)
        dq = getattr(pipeline_score, "dq_score", 1.0)
        health = getattr(pipeline_score, "health_index", 1.0)
        blocked = getattr(pipeline_score, "nodes_blocked", [])
        run_id = getattr(pipeline_score, "run_id", None)
        if self.rich_available:
            from rich.table import Table  # type: ignore

            console = self._rich()
            table = Table(title="Pipeline Quality Score" + (f" (run: {run_id})" if run_id else ""))
            table.add_column("Metric", style="cyan")
            table.add_column("Score")
            table.add_row("Sanity Score", f"{sanity:.4f}")
            table.add_row("DQ Score", f"{dq:.4f}")
            hc = "green" if health >= 0.8 else ("yellow" if health >= 0.5 else "red")
            table.add_row("Health Index", f"[{hc}]{health:.4f}[/{hc}]")
            table.add_row(
                "Nodes Blocked",
                str(len(blocked)) if not blocked else f"[red]{', '.join(blocked)}[/red]",
            )
            console.print(table)
        else:
            logger.info(
                f"Pipeline Quality: sanity={sanity:.4f} dq={dq:.4f} health={health:.4f} blocked={blocked}"
            )


class SanityPhaseRunner:
    """Orchestrates sanity checks on node inputs (pre-execution phase).

    Sanity checks are structural validations running on inputs before expensive
    processing occurs. Typically run at the NodeExecutor level.
    """

    def __init__(
        self,
        fail_fast: bool = True,
        profiles: Optional[Dict[str, QualityProfile]] = None,
        global_gate_config: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialize sanity phase runner."""
        self.fail_fast = fail_fast
        self._profiles: Dict[str, QualityProfile] = profiles or {}
        self._global_gate_config: Optional[Dict[str, Any]] = global_gate_config
        self._reporter = QualityReporter()

    def run_node_checks(
        self,
        dfs: List[Any],
        node_config: dict,
        node_name: str,
        pipeline_name: str = DEFAULT_PIPELINE_NAME,
    ) -> QualityReport:
        """Run sanity checks on a node's inputs.

        *pipeline_name* isn't used for persistence here today (this runner
        doesn't call a StorageBackend directly — QualityOutputManager does
        that, wired separately from node_executor.py), but is accepted and
        threaded through so any future storage/advisor use inside this class
        stays scoped per pipeline like the rest of ducta.check.
        """
        start_time = time.time()

        # Get sanity checks config
        sanity_config_dict = node_config.get("sanity_checks")
        if not sanity_config_dict:
            logger.debug(f"Node '{node_name}' has no sanity_checks config")
            return QualityReport(
                dataset_name=node_name,
                passed=True,
                results=[],
                elapsed_seconds=0.0,
            )

        if not isinstance(sanity_config_dict, dict):
            logger.warning(f"Invalid sanity_checks config for node '{node_name}'")
            return QualityReport(
                dataset_name=node_name,
                passed=True,
                results=[],
                elapsed_seconds=0.0,
            )

        enabled = sanity_config_dict.get("enabled", True)
        if not enabled:
            logger.debug(f"Sanity checks disabled for node '{node_name}'")
            return QualityReport(
                dataset_name=node_name,
                passed=True,
                results=[],
                elapsed_seconds=0.0,
            )

        # If no DataFrames, return early
        if not dfs:
            logger.warning(f"Node '{node_name}' has no input DataFrames")
            return QualityReport(
                dataset_name=node_name,
                passed=True,
                results=[],
                elapsed_seconds=0.0,
            )

        input_index = sanity_config_dict.get("input_index", 0)
        if input_index >= len(dfs):
            logger.warning(
                f"Node '{node_name}': input_index={input_index} out of range "
                f"(only {len(dfs)} inputs available), using index 0"
            )
            input_index = 0
        df = dfs[input_index]

        try:
            adapter = DFAdapter(df)
        except Exception as e:
            logger.error(f"Failed to create DFAdapter for node '{node_name}': {e}")
            return QualityReport(
                dataset_name=node_name,
                passed=False,
                results=[],
                elapsed_seconds=time.time() - start_time,
            )

        # Execute checks
        results = []
        raw_checks_config = sanity_config_dict.get("checks", {})

        # A node's own sanity_checks.fail_fast overrides the runner's
        # constructor-time default for this call. node_executor.py's real
        # per-node execution already constructs a fresh runner per node with
        # this value, so this is a no-op there; run_preflight_checks reuses
        # one runner across every node in the pipeline, so without this a
        # node's fail_fast: false would be silently ignored during preflight.
        fail_fast = sanity_config_dict.get("fail_fast", self.fail_fast)

        # A declared sanity_gate is the thing that decides what a failure means,
        # so it must get to decide. `fail_fast` defaults to true for this phase,
        # and its raise happens inside the per-check loop below — before the gate
        # is ever evaluated. The result was that declaring
        # `sanity_gate: {behavior: warn_only}` did nothing at all: the node
        # hard-failed on the first ERROR regardless of the behavior the config
        # asked for, and `skip_downstream` came back as a failed node rather than
        # a blocked one. Collecting the results instead lets the gate rule, which
        # is what the data_quality phase already does. With no gate declared,
        # fail-fast is untouched.
        gate_will_decide = bool(sanity_config_dict.get("sanity_gate") or self._global_gate_config)
        if gate_will_decide and fail_fast:
            logger.debug(
                "Node '{}': sanity_gate declared, so its behavior decides the outcome "
                "instead of fail_fast aborting on the first ERROR.",
                node_name,
            )
            fail_fast = False

        # Resolve profile: merge profile defaults with node-level checks
        profile_name = sanity_config_dict.get("profile")
        checks_config = resolve_checks_config(raw_checks_config, profile_name, self._profiles)

        for check_name, check_config_dict in checks_config.items():
            if not isinstance(check_config_dict, dict):
                continue

            check_enabled = check_config_dict.get("enabled", True)
            if not check_enabled:
                logger.debug(f"Check '{check_name}' disabled for node '{node_name}'")
                continue

            # Support named instances via the ``type`` field:
            #   check_name  → display name used in reports
            #   registry_key → the check class to instantiate
            registry_key = check_config_dict.get("type") or check_name
            check_class = QUALITY_CHECKS_REGISTRY.get(registry_key)
            if not check_class:
                logger.warning(f"Unknown check type: '{registry_key}' (entry: '{check_name}')")
                result = _build_unknown_check_type_result(check_name, registry_key)
                results.append(result)
                if fail_fast:
                    raise QualityCheckError(
                        check_name=check_name,
                        message=result.message,
                        node_name=node_name,
                    )
                continue

            configured_severity = _configured_severity(check_config_dict, check_name)

            try:
                # Create check instance
                check = check_class()

                # Create config object (named-instance entries carry ``type`` as an
                # attribute; checks that look for it via getattr won't be confused
                # since no builtin check uses a ``type`` attribute internally)
                check_config = type("CheckConfig", (), check_config_dict)()

                # Execute check
                logger.debug(
                    f"Executing check '{registry_key}' (as '{check_name}') for node '{node_name}'"
                )
                result = check.run(df, check_config, adapter, None)
                # Applied before fail_fast is consulted below, so a check the
                # config downgraded to a warning does not abort the run.
                result = _apply_configured_severity(result, configured_severity)
                # Override check_name with display name so reports use the node alias
                if registry_key != check_name:
                    result = _rename_result(result, check_name)
                results.append(result)

                # Fail-fast mode: raise immediately on error
                if fail_fast and not result.passed and result.is_error:
                    raise QualityCheckError(
                        check_name=check_name,
                        message=result.message,
                        node_name=node_name,
                        severity=result.severity.value,
                    )

            except QualityCheckError:
                raise
            except Exception as e:
                logger.error(f"Error executing check '{check_name}' for node '{node_name}': {e}")
                result = _build_execution_error_result(check_name, e)
                results.append(result)
                if fail_fast:
                    raise QualityCheckError(
                        check_name=check_name,
                        message=str(e),
                        node_name=node_name,
                    )

        # Build report
        elapsed = time.time() - start_time
        report = QualityReport(
            dataset_name=node_name,
            passed=all(r.passed for r in results),
            results=results,
            elapsed_seconds=elapsed,
        )

        # Compute weighted score and evaluate sanity gate if configured
        # IMPORTANT: Gate evaluation happens BEFORE raising QualityChecksFailed
        # in non-fail-fast mode so that gate result is always available
        node_gate_cfg = sanity_config_dict.get("sanity_gate")
        try:
            QualityGateEvaluator = None
            try:
                from ducta.check.gate import QualityGateEvaluator  # lazy import
            except ImportError:
                logger.debug("Quality gate module not available, skipping gate evaluation")

            if QualityGateEvaluator and (node_gate_cfg or self._global_gate_config):
                gate_result = QualityGateEvaluator.from_config(
                    report,
                    node_gate_cfg=node_gate_cfg,
                    global_gate_cfg=self._global_gate_config,
                )
                if gate_result is not None:
                    report.score = gate_result.score
                    if not gate_result.passed:
                        _raise_or_warn_gate(gate_result, node_name)
            elif QualityGateEvaluator:
                report.score = QualityGateEvaluator.compute_score(report, {})
        except QualityGateBlocked:
            raise
        except Exception as e:
            logger.exception(f"Sanity gate evaluation failed for node '{node_name}': {e}")
            try:
                from ducta.check.gate import QualityGateEvaluator as _GE  # lazy import

                report.score = _GE.compute_score(report, {})
            except Exception:
                pass

        # Non-fail-fast mode: raise collected failures (AFTER gate so gate result
        # is available). Skipped when a gate was in charge — it has already had
        # its say above, and for `warn_only` that say was "log this and carry
        # on". Raising here anyway would take the node down for the failures the
        # gate just declared tolerable, which is the same way round the
        # fail-fast raise used to pre-empt the gate.
        if not fail_fast and not gate_will_decide:
            errors = [r for r in results if r.is_error]
            if errors:
                raise QualityChecksFailed(results, node_name)

        return report

    def run_preflight_checks(
        self,
        pipeline_config: dict,
        context: Any,
        pipeline_name: str = DEFAULT_PIPELINE_NAME,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, QualityReport]:
        """Run sanity checks on all nodes before pipeline execution.

        Loads each node's inputs the same way real execution does
        (``InputLoader.load_inputs``, not a per-input dict loop keyed on a
        nonexistent config shape) so checks actually run instead of silently
        no-opping. A node whose inputs aren't available yet (e.g. it depends
        on an earlier node in the same pipeline) is expected during a
        whole-pipeline preflight pass and is skipped, not treated as failure.

        ``run_node_checks`` always raises on a failing check (immediately as
        ``QualityCheckError`` when ``fail_fast``, or collected as
        ``QualityChecksFailed`` otherwise) — there is no silent-failure return
        path. In ``fail_fast=False`` mode (used by 3 of the 4 real callers),
        a single node's collected failure is caught here and turned into a
        ``passed=False`` report so the rest of the pipeline still gets
        preflighted, instead of aborting the whole run on the first bad node.

        ``QualityGateBlocked`` is handled by its gate's ``behavior``: this is
        a flat, whole-pipeline scan with no DAG/dependency awareness, so
        ``skip_downstream`` has no "downstream" to skip here — only
        ``stop_all`` aborts the entire preflight (and thus the pipeline run,
        since callers don't catch it). ``skip_downstream``/``warn_only``
        are recorded as a failed report and the loop continues; the *real*
        skip-downstream enforcement (skip only this node's descendants)
        happens correctly later, per-node, during actual DAG execution in
        ``node_executor.py``, which evaluates the same gate again.
        """
        from ducta.gate.exceptions import MissingDependencyError
        from ducta.gate.input import InputLoader

        reports: Dict[str, QualityReport] = {}

        nodes_config = pipeline_config.get("nodes", {})
        if not nodes_config:
            logger.info("No nodes in pipeline config")
            return reports

        loader = InputLoader(context)

        for node_name, node_config in nodes_config.items():
            sanity_config = node_config.get("sanity_checks")
            if not sanity_config or not sanity_config.get("enabled", True):
                logger.debug(f"Skipping preflight checks for node '{node_name}'")
                continue

            try:
                # The run's window: an incremental input is checked on what the
                # run will read, not on the whole table.
                dfs = loader.load_inputs(node_config, node_name, start_date, end_date)
            except MissingDependencyError as e:
                logger.info(
                    f"Skipping preflight for node '{node_name}': input not yet available ({e})"
                )
                continue
            except Exception as e:
                logger.error(f"Failed to load inputs for node '{node_name}': {e}")
                if self.fail_fast:
                    raise
                continue

            if not dfs:
                continue

            try:
                reports[node_name] = self.run_node_checks(
                    dfs, node_config, node_name, pipeline_name=pipeline_name
                )
            except QualityGateBlocked as e:
                from ducta.check.gate import GateBehavior

                behavior = getattr(e.gate_result, "behavior", GateBehavior.STOP_ALL)
                if behavior == GateBehavior.STOP_ALL:
                    raise
                logger.warning(
                    f"Preflight gate blocked node '{node_name}' (behavior={behavior}); "
                    "continuing preflight — real per-node execution will enforce this gate."
                )
                reports[node_name] = QualityReport(
                    dataset_name=node_name,
                    passed=False,
                    results=[],
                    score=getattr(e.gate_result, "score", 0.0),
                )
            except QualityChecksFailed as e:
                reports[node_name] = QualityReport(
                    dataset_name=node_name, passed=False, results=e.results
                )
            except QualityCheckError as e:
                # A node's own sanity_checks.fail_fast (which run_node_checks lets
                # override self.fail_fast per-node) can raise this even when this
                # runner's own fail_fast is False — only abort the whole preflight
                # when the runner itself is configured to fail fast; otherwise
                # record this node as failed and keep preflighting the rest.
                if self.fail_fast:
                    raise
                logger.warning(
                    f"Node '{node_name}' aborted its own checks early "
                    f"(sanity_checks.fail_fast override): {e}. Continuing preflight "
                    "for remaining nodes."
                )
                reports[node_name] = QualityReport(dataset_name=node_name, passed=False, results=[])
            except Exception as e:
                logger.error(f"Preflight check failed for node '{node_name}': {e}")
                if self.fail_fast:
                    raise

        return reports


class ValidationPhaseRunner:
    """Orchestrates data quality checks on dataset outputs."""

    def __init__(
        self,
        workspace_path: str = ".",
        storage_backend: Optional[StorageBackend] = None,
        fail_fast: bool = False,
        profiles: Optional[Dict[str, QualityProfile]] = None,
        context: Optional[Any] = None,
        global_gate_config: Optional[Dict[str, Any]] = None,
        format: Optional[str] = None,
    ) -> None:
        """Initialize validation phase runner."""
        if context is not None:
            gs = getattr(context, "global_config", {}) or {}
            if not isinstance(gs, dict):
                gs = {}

            # Enforce Ducta Standard: All I/O should be centralized in global_config
            output_cfg = gs.get("quality", {}).get("output", {})
            output_fmt = format or output_cfg.get("format", "json")
            base_path = output_cfg.get("base_path")
            writer_options = output_cfg.get("writer_options", {})

            if base_path and "${" in base_path:
                from ducta.setting.interpolator import VariableInterpolator

                base_path = VariableInterpolator.interpolate(base_path, gs)

            if not base_path:
                global_output = gs.get("output_path") or getattr(context, "output_path", None)
                if not global_output:
                    from ducta.check.core import QualityConfigError

                    raise QualityConfigError(
                        "Ducta Standard Violation: All data input/output must be explicitly configured. "
                        "Missing 'output_path' in global_config or 'base_path' in global_config.quality.output."
                    )
                env = gs.get("environment", "base")
                base_path = _default_quality_dir(Path(global_output) / env)

            self.workspace_path = base_path
            self.storage = storage_backend or ContextAwareStorageBackend(
                context, format=output_fmt, base_path=base_path, writer_options=writer_options
            )
        else:
            self.workspace_path = workspace_path
            self.storage = storage_backend or FileStorageBackend(workspace_path)
        self.fail_fast = fail_fast
        self._profiles: Dict[str, QualityProfile] = profiles or {}
        self._global_gate_config: Optional[Dict[str, Any]] = global_gate_config
        self._reporter = QualityReporter()

        logger.debug(f"ValidationPhaseRunner initialized at {self.workspace_path}")

    def run(
        self,
        dataset_name: str,
        df: Any,
        config: Dict[str, Any],
        context_datasets: Optional[Dict[str, Any]] = None,
        run_id: Optional[str] = None,
        pipeline_name: str = DEFAULT_PIPELINE_NAME,
    ) -> QualityReport:
        """Execute validation checks on a dataset.

        *pipeline_name* scopes every report/baseline/history read+write on
        this run under its own bucket (see ``ducta.check.storage
        .StorageBackend``), so two pipelines with a node of the same name
        never mix or overwrite each other's quality history.
        """
        run_id = run_id or str(uuid.uuid4())[:8]
        start_time = time.perf_counter()

        logger.info(
            f"Starting validation run {run_id} for dataset '{dataset_name}' "
            f"(pipeline '{pipeline_name}')"
        )

        try:
            # Create adapter
            adapter = DFAdapter(df)
            logger.debug(f"Detected DataFrame engine: {adapter.engine}")

            # Parse config
            if isinstance(config, dict):
                enabled = config.get("enabled", True)
                checks_config = config.get("checks", {})
            else:
                enabled = getattr(config, "enabled", True)
                checks_config = getattr(config, "checks", {})

            if not enabled:
                logger.info(f"Validation checks disabled for '{dataset_name}'")
                return QualityReport(
                    dataset_name=dataset_name,
                    passed=True,
                    run_id=run_id,
                    workspace_path=self.workspace_path,
                )

            # Load baseline and history for temporal checks
            baseline = self.storage.load_baseline(dataset_name, pipeline_name)
            history = self.storage.load_history(dataset_name, pipeline_name) or []

            # Execute checks
            results = []
            raw_checks = checks_config if isinstance(checks_config, dict) else {}

            # Resolve profile: merge profile defaults with node-level checks
            profile_name = (
                config.get("profile")
                if isinstance(config, dict)
                else getattr(config, "profile", None)
            )
            checks_config = resolve_checks_config(raw_checks, profile_name, self._profiles)

            for check_name, check_config_dict in checks_config.items():
                if not isinstance(check_config_dict, dict):
                    continue

                check_enabled = check_config_dict.get("enabled", True)
                if not check_enabled:
                    logger.debug(f"Check '{check_name}' disabled")
                    continue

                # Support named instances via ``type`` field
                registry_key = check_config_dict.get("type") or check_name
                check_class = QUALITY_CHECKS_REGISTRY.get(registry_key)
                if not check_class:
                    logger.warning(f"Unknown check type: '{registry_key}' (entry: '{check_name}')")
                    result = _build_unknown_check_type_result(check_name, registry_key)
                    results.append(result)
                    if self.fail_fast:
                        self._abort_with_failure(
                            dataset_name, results, result, run_id, pipeline_name, start_time
                        )
                    continue

                configured_severity = _configured_severity(check_config_dict, check_name)

                try:
                    # Create check instance
                    check = check_class()

                    # Create config object from dict
                    check_config = type("CheckConfig", (), check_config_dict)()

                    # Inject baseline and history for temporal checks
                    # Use registry_key for type-based look-up so named instances work too
                    if registry_key in ("anomaly_detection", "incremental_volume"):
                        check_config._baseline = baseline
                        check_config._history = history

                    if registry_key == "drift_detection":
                        check_config._baseline = baseline

                    # Execute check
                    logger.debug(f"Executing check: {registry_key} (as '{check_name}')")
                    result = check.run(df, check_config, adapter, context_datasets)
                    # Applied before fail_fast is consulted below, so a check the
                    # config downgraded to a warning does not abort the run.
                    result = _apply_configured_severity(result, configured_severity)
                    # Use the node-level alias (check_name) in reports for named instances
                    if registry_key != check_name:
                        result = _rename_result(result, check_name)
                    results.append(result)

                    # Fail-fast mode
                    if self.fail_fast and not result.passed and result.is_error:
                        self._abort_with_failure(
                            dataset_name, results, result, run_id, pipeline_name, start_time
                        )

                except QualityChecksFailed:
                    raise
                except Exception as e:
                    logger.error(f"Error executing check '{check_name}': {e}")
                    result = _build_execution_error_result(check_name, e)
                    results.append(result)
                    if self.fail_fast:
                        self._abort_with_failure(
                            dataset_name, results, result, run_id, pipeline_name, start_time
                        )

            # Build report
            elapsed = time.perf_counter() - start_time
            report = QualityReport(
                dataset_name=dataset_name,
                passed=all(r.passed for r in results),
                results=results,
                run_id=run_id,
                workspace_path=self.workspace_path,
                elapsed_seconds=elapsed,
            )

            # Extract gate config early so score_weights can be used for pre-gate scoring
            node_gate_cfg = (
                config.get("quality_gate")
                if isinstance(config, dict)
                else getattr(config, "quality_gate", None)
            )
            if hasattr(node_gate_cfg, "model_dump"):
                node_gate_cfg = node_gate_cfg.model_dump(exclude_none=True)
            elif hasattr(node_gate_cfg, "dict"):
                node_gate_cfg = node_gate_cfg.dict(exclude_none=True)

            node_gate_cfg = apply_auto_tune(
                self._profiles.get(profile_name) if profile_name else None,
                node_gate_cfg,
                dataset_name,
                self.storage,
                pipeline_name,
            )

            # Compute weighted score and assign to report before persisting
            try:
                from ducta.check.gate import QualityGateEvaluator  # lazy import

                _weights: Dict[str, float] = {}
                if node_gate_cfg and isinstance(node_gate_cfg, dict):
                    _weights = node_gate_cfg.get("score_weights") or {}
                elif self._global_gate_config:
                    _weights = self._global_gate_config.get("score_weights") or {}
                report.score = QualityGateEvaluator.compute_score(report, _weights)
            except ImportError:
                logger.debug("Quality gate module not available, using default score")
                report.score = 1.0
            except Exception as e:
                logger.warning(f"Failed to compute quality score: {e}")
                report.score = 1.0

            # Save report (now includes score)
            try:
                self.storage.save_report(report.to_dict(), run_id, dataset_name, pipeline_name)
                logger.debug(f"Saved validation report {run_id}")
            except Exception as e:
                logger.warning(f"Failed to save validation report: {e}")
                report.persistence_warnings.append(f"Failed to save validation report: {e}")

            # Save/update baseline (first run)
            if not baseline:
                try:
                    self._create_and_save_baseline(df, adapter, dataset_name, pipeline_name)
                    logger.debug(f"Created baseline for '{dataset_name}'")
                except Exception as e:
                    logger.warning(f"Failed to create baseline: {e}")
                    report.persistence_warnings.append(f"Failed to create baseline: {e}")

            dq_gate_result = None
            if node_gate_cfg or self._global_gate_config:
                try:
                    from ducta.check.gate import QualityGateEvaluator  # lazy import

                    dq_gate_result = QualityGateEvaluator.from_config(
                        report,
                        node_gate_cfg=node_gate_cfg,
                        global_gate_cfg=self._global_gate_config,
                    )
                    if dq_gate_result is not None:
                        # Gate score supersedes the pre-computed uniform score
                        report.score = dq_gate_result.score
                        # Persist gate result alongside the quality report
                        try:
                            self.storage.save_gate_result(
                                dq_gate_result.to_dict(), run_id, dataset_name, pipeline_name
                            )
                        except Exception as ge:
                            logger.warning(f"Failed to save gate result: {ge}")
                            report.persistence_warnings.append(f"Failed to save gate result: {ge}")
                except ImportError:
                    logger.debug("Quality gate module not available, skipping gate evaluation")
                except Exception as e:
                    # A gate was explicitly configured (node_gate_cfg or
                    # self._global_gate_config truthy, per the `if` above) — if it
                    # can't be evaluated, the node must fail closed, not silently
                    # continue as if the gate had passed.
                    logger.exception(f"Quality gate evaluation failed: {e}")
                    raise
            # ---- end gate --------------------------------------------------

            # Append to history AFTER gate so gate_action can be recorded
            try:
                _gate_action = dq_gate_result.action.value if dq_gate_result else None
                self._append_to_history(
                    dataset_name,
                    adapter,
                    report=report,
                    gate_action=_gate_action,
                    pipeline_name=pipeline_name,
                )
                logger.debug(f"Updated history for '{dataset_name}'")
            except Exception as e:
                logger.warning(f"Failed to update history: {e}")
                report.persistence_warnings.append(f"Failed to update history: {e}")

            # Raise if gate decision is BLOCK (after history is safely written)
            if dq_gate_result is not None and not dq_gate_result.passed:
                _raise_or_warn_gate(dq_gate_result, dataset_name, run_id=run_id)

            # Non-fail-fast mode: check for errors (AFTER gate so gate result is
            # persisted). Not when a gate decided: as at the sanity site, its
            # `warn_only` means "log and carry on", and raising here regardless
            # would take the node down for failures the gate declared tolerable.
            if not self.fail_fast and dq_gate_result is None:
                errors = [r for r in results if r.is_error]
                if errors:
                    raise QualityChecksFailed(results, dataset_name, run_id)

            logger.info(f"Validation run {run_id} completed for '{dataset_name}' - {report.passed}")
            return report

        except (QualityChecksFailed, QualityGateBlocked):
            raise
        except Exception as e:
            logger.exception(f"Validation runner failed: {e}")
            raise

    def _abort_with_failure(
        self,
        dataset_name: str,
        results: list,
        failing_result: "CheckResult",
        run_id: str,
        pipeline_name: str,
        start_time: float,
    ) -> None:
        """Build+save the report so far and raise ``QualityChecksFailed`` for
        *failing_result*. Shared by the three fail-fast abort points in
        ``run()`` (unknown check type, a failed ERROR-severity check, and an
        exception during check execution) — always raises, never returns."""
        elapsed = time.perf_counter() - start_time
        report = QualityReport(
            dataset_name=dataset_name,
            passed=False,
            results=results,
            run_id=run_id,
            workspace_path=self.workspace_path,
            elapsed_seconds=elapsed,
        )
        self._assign_best_effort_score(report)
        self.storage.save_report(report.to_dict(), run_id, dataset_name, pipeline_name)
        raise QualityChecksFailed([failing_result], dataset_name, run_id)

    @staticmethod
    def _assign_best_effort_score(report: QualityReport) -> None:
        """Set ``report.score`` from its own results before an early (fail-fast) save.

        Without this, a report saved on a fail-fast abort keeps the ``QualityReport``
        dataclass default of ``1.0`` regardless of the failure that triggered the
        abort — persisted reports would show a perfect score alongside ``passed:
        false``. Unweighted scoring (no ``score_weights``) is used here, same as
        the ImportError/Exception fallback further down in this method, since the
        node's gate config (with any real weights) isn't resolved yet at this point.
        """
        try:
            from ducta.check.gate import QualityGateEvaluator

            report.score = QualityGateEvaluator.compute_score(report, {})
        except Exception:
            pass

    def _create_and_save_baseline(
        self,
        df: Any,
        adapter: DFAdapter,
        dataset_name: str,
        pipeline_name: str = DEFAULT_PIPELINE_NAME,
    ) -> None:
        """Create initial baseline from current data."""
        # For Spark, sample to avoid transferring full dataset to driver
        _MAX_BASELINE_ROWS = 100_000
        import pandas as pd  # lazy import — only needed for baseline creation

        if adapter.engine == "spark" and adapter.count() > _MAX_BASELINE_ROWS:
            fraction = _MAX_BASELINE_ROWS / adapter.count()
            pdf = df.sample(fraction=fraction, seed=42).toPandas()
            logger.debug(
                f"Baseline sampled {_MAX_BASELINE_ROWS} rows ({fraction:.1%}) from Spark DataFrame"
            )
        else:
            pdf = adapter.to_pandas()
        baseline = {}

        for column in pdf.columns:
            try:
                col_data = pdf[column].dropna()

                if pd.api.types.is_numeric_dtype(col_data):
                    baseline[column] = {
                        "mean": float(col_data.mean()),
                        "std": float(col_data.std()),
                    }
                else:
                    # Convert keys to str to ensure JSON serializability
                    # (e.g. pd.Timestamp keys from datetime columns)
                    baseline[column] = {
                        "value_counts": {
                            str(k): int(v) for k, v in col_data.value_counts().head(100).items()
                        },
                    }
            except Exception as e:
                logger.warning(f"Failed to profile column '{column}': {e}")

        self.storage.save_baseline(baseline, dataset_name, pipeline_name)

    def _append_to_history(
        self,
        dataset_name: str,
        adapter: DFAdapter,
        report: Optional[QualityReport] = None,
        gate_action: Optional[str] = None,
        pipeline_name: str = DEFAULT_PIPELINE_NAME,
    ) -> None:
        """Append run metrics to history."""
        try:
            from datetime import datetime, timezone

            metric_entry: Dict[str, Any] = {
                "row_count": adapter.count(),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "score": report.score if report is not None else 1.0,
                "errors_count": report.errors_count if report is not None else 0,
                "warnings_count": report.warnings_count if report is not None else 0,
                "gate_action": gate_action or "none",
            }
            self.storage.append_history(dataset_name, metric_entry, pipeline_name)
        except Exception as e:
            logger.warning(f"Failed to append to history: {e}")

    def render_report(self, report: QualityReport, verbose: bool = False) -> None:
        """Render a validation report.

        Args:
            report: QualityReport to render
            verbose: If True, show detailed results
        """
        self._reporter.render_report(report, verbose)

    def render_summary(self, reports: List[QualityReport], verbose: bool = False) -> None:
        """Render summary of multiple reports.

        Args:
            reports: List of QualityReport objects
            verbose: If True, show detailed results
        """
        self._reporter.render_summary(reports, verbose)


#: Type aliases (no DeprecationWarning possible on a plain assignment).
DQReport = QualityReport
SanityCheckReport = QualityReport
DQConfig = dict


def SanityCheckRunner(*args: Any, **kwargs: Any) -> SanityPhaseRunner:
    """Deprecated: use SanityPhaseRunner."""
    import warnings

    warnings.warn(
        "SanityCheckRunner is deprecated, use SanityPhaseRunner instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return SanityPhaseRunner(*args, **kwargs)


def DQRunner(*args: Any, **kwargs: Any) -> ValidationPhaseRunner:
    """Deprecated: use ValidationPhaseRunner."""
    import warnings

    warnings.warn(
        "DQRunner is deprecated, use ValidationPhaseRunner instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return ValidationPhaseRunner(*args, **kwargs)


def SanityReporter(*args: Any, **kwargs: Any) -> QualityReporter:
    """Deprecated: use QualityReporter."""
    import warnings

    warnings.warn(
        "SanityReporter is deprecated, use QualityReporter instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return QualityReporter(*args, **kwargs)


def DQReporter(*args: Any, **kwargs: Any) -> QualityReporter:
    """Deprecated: use QualityReporter."""
    import warnings

    warnings.warn(
        "DQReporter is deprecated, use QualityReporter instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return QualityReporter(*args, **kwargs)
