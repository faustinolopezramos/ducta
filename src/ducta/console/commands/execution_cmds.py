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

import json
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from ducta.console import execution
from ducta.console.config import ConfigManager
from ducta.console.core import CLIConfig, ExitCode


class ExecutionCommands:
    """Pipeline execution commands (ducta start).

    ``config`` and ``config_manager`` are populated by the entry points
    (:meth:`handle_start` and friends) before anything else runs, and every
    method below assumes that. They were plain ``Optional`` attributes, which
    meant ~100 accesses that a type checker could only read as "might be None"
    — so the one place where it genuinely might be got no more attention than
    the ninety-nine where it could not. Exposing them through properties that
    raise states the invariant once and turns a violation into a named error
    instead of ``AttributeError: 'NoneType' object has no attribute 'pipeline'``.
    """

    def __init__(self):
        self._config: Optional[CLIConfig] = None
        self._config_manager: Optional[ConfigManager] = None

    @property
    def config(self) -> CLIConfig:
        if self._config is None:
            raise RuntimeError(
                "ExecutionCommands.config read before it was parsed — call "
                "handle_start() (or another entry point) first."
            )
        return self._config

    @config.setter
    def config(self, value: CLIConfig) -> None:
        self._config = value

    @property
    def config_manager(self) -> ConfigManager:
        if self._config_manager is None:
            raise RuntimeError(
                "ExecutionCommands.config_manager read before it was built — call "
                "handle_start() (or another entry point) first."
            )
        return self._config_manager

    @config_manager.setter
    def config_manager(self, value: ConfigManager) -> None:
        self._config_manager = value

    def handle_start(self, parsed_args) -> int:
        from ducta.setting import detect_and_prepare_layered_execution

        if getattr(parsed_args, "reuse_upstream", False) and getattr(
            parsed_args, "rerun_all", False
        ):
            logger.error("--reuse-upstream and --rerun-all are mutually exclusive")
            return ExitCode.VALIDATION_ERROR.value

        is_layered, execution_mode, layer_context_args = detect_and_prepare_layered_execution(
            parsed_args
        )
        if is_layered and execution_mode == "single" and layer_context_args:
            return self._handle_layered_pipeline_execution(parsed_args, layer_context_args)

        self.config = self._parse_config(parsed_args)
        logger.info("Starting Ducta pipeline execution")
        self._try_print_header()

        self.config_manager = ConfigManager(
            base_path=getattr(parsed_args, "base_path", self.config.base_path),
            layer_name=getattr(parsed_args, "layer_name", self.config.layer_name),
            use_case=getattr(parsed_args, "use_case_name", self.config.use_case_name),
            config_type=getattr(parsed_args, "config_type", self.config.config_type),
            interactive=getattr(parsed_args, "interactive", False) or self.config.interactive,
            require_config=False,
        )
        self.config_manager.change_to_config_directory()
        context_init = execution.ContextInitializer(self.config_manager)

        if self.config.validate_only:
            return self._handle_validate_only(context_init)
        if self.config.sanity_only:
            return self._handle_sanity_only(context_init)
        if self.config.dry_run:
            return self._handle_dry_run(context_init)
        return self._execute_pipeline(context_init)

    @staticmethod
    def _resolve_sweep_parallel(parsed_args) -> int:
        """Cap --sweep-parallel at the number of available CPU cores."""
        import os

        requested = max(1, int(getattr(parsed_args, "sweep_parallel", 1) or 1))
        cpu_count = os.cpu_count() or 1
        if requested > cpu_count:
            logger.warning(
                "--sweep-parallel {} exceeds the {} logical core(s) available; "
                "workers would contend for CPU. Capping at {}.",
                requested,
                cpu_count,
                cpu_count,
            )
            return cpu_count
        return requested

    def _parse_config(self, parsed_args) -> CLIConfig:
        return CLIConfig(
            env=getattr(parsed_args, "env", ""),
            pipeline=getattr(parsed_args, "pipeline", ""),
            node=getattr(parsed_args, "node", None),
            start_date=getattr(parsed_args, "start_date", None),
            end_date=getattr(parsed_args, "end_date", None),
            base_path=(
                Path(parsed_args.base_path) if getattr(parsed_args, "base_path", None) else None
            ),
            layer_name=getattr(parsed_args, "layer_name", None),
            use_case_name=getattr(parsed_args, "use_case_name", None),
            config_type=getattr(parsed_args, "config_type", None),
            interactive=getattr(parsed_args, "interactive", False),
            list_configs=getattr(parsed_args, "list_configs", False),
            list_pipelines=getattr(parsed_args, "list_pipelines", False),
            pipeline_info=getattr(parsed_args, "pipeline_info", None),
            clear_cache=getattr(parsed_args, "clear_cache", False),
            log_level=getattr(parsed_args, "log_level", "INFO"),
            log_file=Path(parsed_args.log_file) if getattr(parsed_args, "log_file", None) else None,
            validate_only=getattr(parsed_args, "validate_only", False),
            dry_run=getattr(parsed_args, "dry_run", False),
            sanity_only=getattr(parsed_args, "sanity_only", False),
            verbose=getattr(parsed_args, "verbose", False),
            quiet=getattr(parsed_args, "quiet", False),
            model_version=getattr(parsed_args, "model_version", None),
            hyperparams=getattr(parsed_args, "hyperparams", None),
            sweep=getattr(parsed_args, "sweep", None),
            search=getattr(parsed_args, "search", False),
            search_metric=getattr(parsed_args, "search_metric", None),
            search_trials=getattr(parsed_args, "search_trials", None),
            sweep_reuse_upstream=not getattr(parsed_args, "no_sweep_reuse", False),
            sweep_parallel=self._resolve_sweep_parallel(parsed_args),
            max_sweep_size=int(getattr(parsed_args, "max_sweep_size", None) or 50),
            execution_mode=getattr(parsed_args, "mode", None) or "async",
            output_path=(
                Path(parsed_args.output_path) if getattr(parsed_args, "output_path", None) else None
            ),
            reuse_upstream=getattr(parsed_args, "reuse_upstream", False),
            rerun_all=getattr(parsed_args, "rerun_all", False),
        )

    def _try_print_header(self) -> None:
        try:
            from ducta.console.ux.rich_logger import print_execution_header

            print_execution_header(
                pipeline=self.config.pipeline,
                env=self.config.env,
                start_date=self.config.start_date,
                end_date=self.config.end_date,
                node=self.config.node,
            )
        except Exception:
            pass

    def _handle_layered_pipeline_execution(self, parsed_args, layer_context_args: Dict) -> int:
        self.config = self._parse_config(parsed_args)
        logger.info("Starting Ducta pipeline execution (layered mode)")
        self._try_print_header()

        try:
            from ducta.core import PipelineExecutor
            from ducta.setting.contexts import Context

            # The environment travels in the args dict, so this and every other
            # layered entry point resolve it in one place.
            layer_env = layer_context_args.get("env") or self.config.env
            context = Context(
                global_config=layer_context_args["global_config"],
                pipelines_config=layer_context_args["pipelines_config"],
                nodes_config=layer_context_args["nodes_config"],
                input_config=layer_context_args["input_config"],
                output_config=layer_context_args["output_config"],
                env=layer_env,
            )
            context._config_file_path = layer_context_args["global_config"]
            context.env = layer_env
            logger.info(f"Loaded context for layer: {layer_context_args.get('layer')}")

            executor = PipelineExecutor(context, Path(layer_context_args["layer_path"]))

            if self.config.validate_only:
                return self._validate_layered(executor)
            if self.config.sanity_only:
                return self._sanity_layered(context, executor)
            if self.config.dry_run:
                return self._dry_run_layered(executor, layer_context_args)

            from ducta.console.execution import report_run_outcome

            result = executor.run_pipeline_chain(
                pipeline_name=self.config.pipeline,
                node_name=self.config.node,
                start_date=self.config.start_date,
                end_date=self.config.end_date,
                execution_mode=self.config.execution_mode,
            )
            return report_run_outcome(result, pipeline=self.config.pipeline)

        except Exception as e:
            logger.error(f"Pipeline execution failed: {e}")
            if parsed_args.verbose or (
                hasattr(parsed_args, "log_level") and parsed_args.log_level == "DEBUG"
            ):
                traceback.print_exc()
            return ExitCode.GENERAL_ERROR.value

    def _validate_layered(self, executor) -> int:
        logger.info("Validating configuration (--validate-only)")
        try:
            executor.get_pipeline_info(self.config.pipeline)
            logger.info("Configuration is valid")
            return ExitCode.SUCCESS.value
        except Exception as e:
            logger.error(f"Validation failed: {e}")
            return ExitCode.GENERAL_ERROR.value

    def _run_sanity_checks(self, context, pipeline_name: str) -> int:
        """Run preflight sanity checks for *pipeline_name* and report the
        result. Shared by the layered and non-layered ``--sanity-only`` paths,
        which differ only in what wraps this call (pre-checks, traceback
        logging), not in how the checks themselves are run or reported."""
        from ducta.check.engine import QualityReporter, SanityPhaseRunner

        runner = SanityPhaseRunner(fail_fast=False)
        reports = runner.run_preflight_checks(
            {"nodes": context.nodes_config}, context, pipeline_name=pipeline_name
        )
        QualityReporter().render_pipeline_summary(reports, show_details=True)
        if all(r.passed for r in reports.values()):
            logger.success("All sanity checks passed!")
            return ExitCode.SUCCESS.value
        failed = sum(1 for r in reports.values() if not r.passed)
        logger.error("{} node(s) failed sanity checks", failed)
        return ExitCode.VALIDATION_ERROR.value

    def _sanity_layered(self, context, executor) -> int:
        logger.info("Running sanity checks only (--sanity-only)")
        try:
            return self._run_sanity_checks(context, self.config.pipeline)
        except Exception as e:
            logger.error("Sanity check error: {}", e)
            return ExitCode.GENERAL_ERROR.value

    def _report_dry_run(self, pipeline_info: dict, header: str) -> None:
        """Log the dry-run summary for *pipeline_info* under *header*. Shared
        by the layered and non-layered dry-run paths, which differ only in
        how ``pipeline_info`` was obtained and in the header text."""
        pipeline_nodes = pipeline_info.get("nodes", [])
        logger.info(header)
        logger.info("  Nodes: {}", ", ".join(pipeline_nodes) if pipeline_nodes else "None")
        if self.config.node:
            if pipeline_nodes and self.config.node not in pipeline_nodes:
                logger.warning(
                    f"Node '{self.config.node}' may not exist in pipeline '{self.config.pipeline}'"
                )
            else:
                logger.info("  Single node execution: {}", self.config.node)
        if self.config.start_date:
            logger.info("  Start date: {}", self.config.start_date)
        if self.config.end_date:
            logger.info("  End date: {}", self.config.end_date)
        logger.success("DRY-RUN completed successfully — no actual execution performed")

    def _dry_run_layered(self, executor, layer_context_args) -> int:
        logger.info(
            "DRY-RUN MODE (layered): Pipeline will not be executed, only validated and logged"
        )
        try:
            pipeline_info = executor.get_pipeline_info(self.config.pipeline)
            self._report_dry_run(
                pipeline_info,
                f"DRY-RUN: Pipeline '{self.config.pipeline}' configuration "
                f"in layer '{layer_context_args.get('layer')}'",
            )
            return ExitCode.SUCCESS.value
        except Exception as e:
            logger.error("Dry-run error: {}", e)
            return ExitCode.GENERAL_ERROR.value

    def _handle_validate_only(self, context_init) -> int:
        """``--validate-only``: check the configuration without executing it.

        This used to build the ``Context`` and stop — schema validation only —
        then report "Configuration validation successful". It accepted
        ``--pipeline`` and never looked at it, so everything preflight exists to
        catch (a check name that is not registered, a node function that cannot
        be imported, an output key missing from the catalog, a dependency cycle,
        a gate behavior that silently falls back) passed this command and failed
        the run. A pre-run check that cannot fail is worse than none: it is the
        one people put in CI.
        """
        logger.info("Validating configuration...")
        context = context_init.initialize(self.config.env)

        report = self._run_preflight_report(context)
        if report is not None and not report.ok:
            for warning in report.warnings:
                logger.warning("Preflight: {}", warning)
            for error in report.errors:
                logger.error("Preflight: {}", error)
            logger.error("Configuration validation failed: {} error(s)", len(report.errors))
            return ExitCode.VALIDATION_ERROR.value
        if report is not None:
            for warning in report.warnings:
                logger.warning("Preflight: {}", warning)

        logger.success("Configuration validation successful")
        logger.info("Execution Summary:")
        logger.info("  Environment: {}", context.env if hasattr(context, "env") else "base")
        logger.info("  Pipelines available: {}", len(getattr(context, "pipelines", {})))
        logger.info("  Nodes configured: {}", len(getattr(context, "nodes_config", {})))
        return ExitCode.SUCCESS.value

    def _run_preflight_report(self, context):
        """Preflight for the named pipeline, or every pipeline when none is named.

        Returns a single merged report, or ``None`` when preflight itself could
        not run — a broken checker must not turn a valid config into a failure.
        """
        from ducta.core.preflight import (
            PreflightReport,
            validate_all_pipelines,
            validate_pipeline,
        )

        try:
            if self.config.pipeline:
                return validate_pipeline(context, self.config.pipeline)

            merged = PreflightReport(pipeline_name="*")
            for name, report in sorted(validate_all_pipelines(context).items()):
                merged.errors.extend(f"[{name}] {e}" for e in report.errors)
                merged.warnings.extend(f"[{name}] {w}" for w in report.warnings)
            return merged
        except Exception as e:  # noqa: BLE001 — never fail a valid config on a checker bug
            logger.warning(
                "Preflight validation could not run and was skipped: {}. "
                "The configuration was still checked against its schema.",
                e,
            )
            return None

    def _handle_sanity_only(self, context_init) -> int:
        logger.info("Running sanity checks on pipeline '{}'...", self.config.pipeline)
        context = context_init.initialize(self.config.env)
        try:
            pipeline_config = context.pipelines.get(self.config.pipeline)
            if not pipeline_config:
                logger.error("Pipeline '{}' not found", self.config.pipeline)
                return ExitCode.VALIDATION_ERROR.value
            return self._run_sanity_checks(context, self.config.pipeline)
        except Exception as e:
            logger.error("Sanity check error: {}", e)
            if self.config.verbose:
                logger.exception("Full traceback:")
            return ExitCode.GENERAL_ERROR.value

    def _handle_dry_run(self, context_init) -> int:
        logger.info("DRY-RUN MODE: Pipeline will not be executed, only validated and logged")
        context = context_init.initialize(self.config.env)
        from ducta.core import PipelineExecutor

        exec_obj = PipelineExecutor(context, self.config_manager.get_config_directory())
        if not exec_obj.validate_pipeline(self.config.pipeline):
            available = exec_obj.list_pipelines()
            logger.error("Pipeline '{}' not found", self.config.pipeline)
            if available:
                logger.info("Available: {}", ", ".join(available))
            else:
                logger.info("No pipelines are defined in this configuration")
            return ExitCode.VALIDATION_ERROR.value
        try:
            pipeline_info = exec_obj.get_pipeline_info(self.config.pipeline)
            self._report_dry_run(
                pipeline_info, f"DRY-RUN: Pipeline '{self.config.pipeline}' configuration"
            )
            return ExitCode.SUCCESS.value
        except Exception as e:
            logger.error("Dry-run error: {}", e)
            if self.config.verbose:
                logger.exception("Full traceback:")
            return ExitCode.GENERAL_ERROR.value

    def _execute_pipeline(self, context_init) -> int:
        context = context_init.initialize(self.config.env)
        from ducta.core import PipelineExecutor

        exec_obj = PipelineExecutor(context, self.config_manager.get_config_directory())

        if not exec_obj.validate_pipeline(self.config.pipeline):
            available = exec_obj.list_pipelines()
            logger.error("Pipeline '{}' not found", self.config.pipeline)
            if available:
                logger.info("Available: {}", ", ".join(available))
            else:
                logger.info("No pipelines are defined in this configuration")
            return ExitCode.VALIDATION_ERROR.value

        if self.config.node:
            pipeline_info = exec_obj.get_pipeline_info(self.config.pipeline)
            pipeline_nodes = pipeline_info.get("nodes", [])
            if pipeline_nodes and self.config.node not in pipeline_nodes:
                logger.warning(
                    f"Node '{self.config.node}' may not exist in pipeline '{self.config.pipeline}'"
                )

        base_hyperparams: Optional[Dict[str, Any]] = None
        if self.config.hyperparams:
            try:
                base_hyperparams = json.loads(self.config.hyperparams)
            except json.JSONDecodeError as e:
                logger.error("Invalid hyperparams JSON: {}", e)
                return ExitCode.VALIDATION_ERROR.value

        if self.config.search:
            return self._execute_search(exec_obj, base_hyperparams)

        if self.config.sweep:
            return self._execute_sweep(exec_obj, base_hyperparams)

        result = exec_obj.run_pipeline_chain(
            pipeline_name=self.config.pipeline,
            node_name=self.config.node,
            start_date=self.config.start_date,
            end_date=self.config.end_date,
            model_version=self.config.model_version,
            hyperparams=base_hyperparams,
            execution_mode=self.config.execution_mode,
            reuse_upstream=self.config.reuse_upstream,
            rerun_all=self.config.rerun_all,
        )

        from ducta.console.execution import report_run_outcome

        return report_run_outcome(result, pipeline=self.config.pipeline)

    def _execute_sweep(self, exec_obj, base_hyperparams) -> int:
        from ducta.core.sweep import SweepError, expand_sweep, load_sweep_spec, new_sweep_id

        try:
            spec = load_sweep_spec(self.config.sweep)
            combos = expand_sweep(spec, max_runs=self.config.max_sweep_size)
        except SweepError as e:
            logger.error("Invalid sweep spec: {}", e)
            return ExitCode.VALIDATION_ERROR.value

        self._warn_if_sweep_without_validation_split(exec_obj)
        sweep_id = new_sweep_id()
        logger.info(
            "Starting sweep {} on pipeline '{}': {} run(s)",
            sweep_id,
            self.config.pipeline,
            len(combos),
        )

        if self.config.sweep_parallel > 1:
            self._warn_if_parallel_spark(exec_obj, self.config.sweep_parallel)
            trials = []
            for index, combo in enumerate(combos, start=1):
                hyperparams = self._build_trial_hyperparams(
                    base_hyperparams, combo, sweep_id, index
                )
                trials.append({"index": index, "params": combo, "hyperparams": hyperparams})

            if self.config.sweep_reuse_upstream:
                logger.info(
                    "--sweep-parallel does not use --no-sweep-reuse's chain-level "
                    "upstream reuse (reuse_upstream on run_pipeline_chain) — trial 1 "
                    "still materializes a shared prefix that trials 2..N can read "
                    "missing inputs from, but nothing here skips re-running a node."
                )
            outcomes = self._run_trials_parallel(
                exec_obj, trials, sweep_id, self.config.sweep_parallel
            )
            if outcomes is not None:
                failures = 0
                for outcome in outcomes:
                    if outcome["failed"]:
                        failures += 1
                        logger.error(
                            "Sweep run {}/{} failed: {}",
                            outcome["index"],
                            len(combos),
                            outcome["reason"],
                        )
                    else:
                        logger.info(
                            "Sweep run {}/{} done: {}",
                            outcome["index"],
                            len(combos),
                            outcome["metrics"] or "no metrics logged",
                        )
                return self._report_sweep_result(sweep_id, len(combos), failures)

        failures = 0
        for index, combo in enumerate(combos, start=1):
            hyperparams = self._build_trial_hyperparams(base_hyperparams, combo, sweep_id, index)
            logger.info("Sweep run {}/{}: {}", index, len(combos), combo)
            try:
                run = self._run_trial(exec_obj, hyperparams, trial_index=index)
                if run.gate_blocked:
                    failures += 1
                    logger.error(
                        "Sweep run {}/{} was blocked by a quality gate: {}",
                        index,
                        len(combos),
                        ", ".join(sorted(run.gate_blocked)),
                    )
            except Exception as e:
                failures += 1
                logger.error("Sweep run {}/{} failed: {}", index, len(combos), e)

        return self._report_sweep_result(sweep_id, len(combos), failures)

    @staticmethod
    def _report_sweep_result(sweep_id: str, total: int, failures: int) -> int:
        """Final sweep summary and exit code, shared by the sequential and
        parallel paths so both report identically."""
        logger.info(
            "Sweep {} finished: {}/{} run(s) succeeded. Compare runs in the experiment tracker filtering by tag sweep_id={}",
            sweep_id,
            total - failures,
            total,
            sweep_id,
        )
        if failures:
            logger.error("Sweep completed with {} failed run(s)", failures)
            return ExitCode.GENERAL_ERROR.value
        logger.success("Ducta sweep execution completed successfully")
        return ExitCode.SUCCESS.value

    def _parallel_worker_args(self, exec_obj) -> Dict[str, Any]:
        """Everything a worker process needs to rebuild this run's Context."""
        base_output_path = None
        try:
            gs = getattr(exec_obj.context, "global_config", {}) or {}
            base_output_path = gs.get("output_path") or getattr(
                exec_obj.context, "output_path", None
            )
        except Exception as e:
            logger.debug("Could not resolve output_path for trial isolation: {}", e)
        return {
            "env": self.config.env,
            "pipeline": self.config.pipeline,
            "base_output_path": str(base_output_path) if base_output_path else None,
            "base_path": self.config.base_path,
            "layer_name": self.config.layer_name,
            "use_case_name": self.config.use_case_name,
            "config_type": self.config.config_type,
            "node": self.config.node,
            "start_date": self.config.start_date,
            "end_date": self.config.end_date,
            "model_version": self.config.model_version,
        }

    def _run_trials_parallel(self, exec_obj, trials, search_id: str, workers: int):
        """Run pre-generated trials concurrently, one process each."""
        import multiprocessing
        from concurrent.futures import ProcessPoolExecutor, as_completed

        from ducta.core.sweep_worker import (
            build_payloads,
            run_trial_in_process,
            shared_prefix_path,
        )

        mp_context = multiprocessing.get_context("spawn")

        worker_args = self._parallel_worker_args(exec_obj)
        if not worker_args["base_output_path"]:
            logger.warning(
                "Cannot resolve output_path, so parallel trials cannot be given "
                "isolated output directories and would clobber each other's node "
                "outputs. Falling back to sequential execution."
            )
            return None

        if not trials:
            return []

        first_trial, *rest_trials = trials
        shared_path = shared_prefix_path(worker_args["base_output_path"], search_id)

        logger.info(
            "Running trial {} first (sequentially) into the shared prefix {} — "
            "the rest run in parallel afterward.",
            first_trial["index"],
            shared_path,
        )
        first_payload = build_payloads([first_trial], search_id=search_id, **worker_args)[0]
        first_payload["output_path"] = shared_path
        first_outcome = run_trial_in_process(first_payload)
        outcomes = [first_outcome]

        read_fallback_paths: List[str] = []
        if first_outcome.get("failed"):
            logger.warning(
                "Trial {} failed ({}); the rest will run without the read fallback "
                "(each trial resolves its inputs entirely on its own).",
                first_trial["index"],
                first_outcome.get("reason"),
            )
        else:
            read_fallback_paths = [shared_path]

        if not rest_trials:
            return sorted(outcomes, key=lambda o: o.get("index") or 0)

        payloads = build_payloads(
            rest_trials,
            search_id=search_id,
            read_fallback_paths=read_fallback_paths,
            **worker_args,
        )
        logger.info(
            "Running {} more trial(s) across {} worker process(es); each writes to "
            "its own directory under {}/_trials/{}",
            len(payloads),
            workers,
            worker_args["base_output_path"],
            search_id,
        )

        with ProcessPoolExecutor(max_workers=workers, mp_context=mp_context) as pool:
            futures = {pool.submit(run_trial_in_process, payload): payload for payload in payloads}
            for future in as_completed(futures):
                payload = futures[future]
                try:
                    outcomes.append(future.result())
                except Exception as e:  # noqa: BLE001 — a dead worker is one failed trial
                    outcomes.append(
                        {
                            "index": payload["trial_index"],
                            "params": payload["params"],
                            "metrics": {},
                            "gate_blocked": [],
                            "failed": True,
                            "reason": f"worker process died: {type(e).__name__}: {e}",
                        }
                    )
        return sorted(outcomes, key=lambda o: o.get("index") or 0)

    @staticmethod
    def _build_trial_hyperparams(
        base_hyperparams: Optional[Dict[str, Any]],
        params: Dict[str, Any],
        run_id: str,
        index: int,
    ) -> Dict[str, Any]:
        """Merge one sweep/search trial's params onto the shared base and stamp
        which run/index produced them."""
        hyperparams = {**(base_hyperparams or {}), **params}
        hyperparams["sweep_id"] = run_id
        hyperparams["sweep_index"] = index
        return hyperparams

    def _run_trial(self, exec_obj, hyperparams: Dict[str, Any], trial_index: int):
        """Execute one sweep/search trial."""
        if not self.config.sweep_reuse_upstream:
            return exec_obj.run_pipeline(
                pipeline_name=self.config.pipeline,
                node_name=self.config.node,
                start_date=self.config.start_date,
                end_date=self.config.end_date,
                model_version=self.config.model_version,
                hyperparams=hyperparams,
            )

        return exec_obj.run_pipeline_chain(
            pipeline_name=self.config.pipeline,
            node_name=self.config.node,
            start_date=self.config.start_date,
            end_date=self.config.end_date,
            model_version=self.config.model_version,
            hyperparams=hyperparams,
            # Trial 1 has nothing to reuse yet and must build the prefix.
            reuse_upstream=trial_index > 1,
            rerun_all=False,
        )

    def _make_trial_runner(self, exec_obj, base_hyperparams, run_id: str, n_trials: int):
        """Build a ``(params, index) -> RunResult`` callable for a search
        strategy's sequential fallback path — the same shape needed by
        ``_execute_search`` and by ``_run_search_parallel``'s replay when
        parallel execution isn't available."""

        def run_trial(params, index):
            hyperparams = self._build_trial_hyperparams(base_hyperparams, params, run_id, index)
            logger.info("Trial {}/{}: {}", index, n_trials, params)
            return self._run_trial(exec_obj, hyperparams, trial_index=index)

        return run_trial

    def _execute_search(self, exec_obj, base_hyperparams) -> int:
        """Drive a real search strategy from the pipeline's hyperparams_config."""
        from ducta.core.sweep import new_search_id, run_search
        from ducta.mlrun.hyperparams import HyperparamConfigError
        from ducta.mlrun.search import SearchError, build_search_strategy, resolve_objective

        hp_config = self._resolve_hyperparams_config(exec_obj)
        if hp_config is None:
            logger.error(
                "--search needs a hyperparams_config for pipeline '{}'. Declare one "
                "(hyperparams_config in the pipeline config, or hyperparams_config_path "
                "in global_config) with an algorithm, a search_space and an "
                "objective.metric. Use --sweep FILE for a plain grid instead.",
                self.config.pipeline,
            )
            return ExitCode.VALIDATION_ERROR.value

        try:
            metric, direction = resolve_objective(hp_config)
            if self.config.search_metric:
                metric = self.config.search_metric
            strategy = build_search_strategy(
                hp_config,
                n_trials=self.config.search_trials,
                seed=self._resolve_seed(exec_obj),
                study_name=hp_config.study_name,
            )
        except (SearchError, HyperparamConfigError) as e:
            logger.error("Invalid search configuration: {}", e)
            return ExitCode.VALIDATION_ERROR.value

        self._warn_if_sweep_without_validation_split(exec_obj)
        if metric.startswith("test_"):
            logger.warning(
                "Search objective is '{}': selecting hyperparameters on a test metric "
                "invalidates it as an unbiased estimate. Point objective.metric at a "
                "validation metric (e.g. val_{}).",
                metric,
                metric[len("test_") :],
            )

        search_id = new_search_id()
        logger.info(
            "Starting {} search {} on pipeline '{}': up to {} trial(s), optimizing {} ({})",
            hp_config.algorithm,
            search_id,
            self.config.pipeline,
            strategy.n_trials,
            metric,
            direction,
        )

        parallel = self.config.sweep_parallel
        if parallel > 1 and hp_config.algorithm == "bayesian":
            logger.warning(
                "Bayesian search chooses each trial from the results of the previous "
                "ones, so it cannot be run in parallel without discarding exactly the "
                "feedback that makes it Bayesian. Running sequentially; use "
                "algorithm='random' with --sweep-parallel to trade sample efficiency "
                "for wall-clock."
            )
            parallel = 1

        if parallel > 1:
            self._warn_if_parallel_spark(exec_obj, parallel)
            outcome = self._run_search_parallel(
                exec_obj, strategy, metric, base_hyperparams, search_id, parallel
            )
        else:
            run_trial = self._make_trial_runner(
                exec_obj, base_hyperparams, search_id, strategy.n_trials
            )
            outcome = run_search(strategy, metric, run_trial, search_id=search_id)

        for trial in outcome.trials:
            if trial.failed:
                logger.error("Trial {} failed: {}", trial.index, trial.reason)

        logger.info(
            "Search {} finished: {}/{} trial(s) scored. Compare runs in the experiment "
            "tracker filtering by tag sweep_id={}",
            search_id,
            outcome.succeeded,
            len(outcome.trials),
            search_id,
        )
        if outcome.best_params is not None:
            logger.success(
                "Best {}={:.6f} with {}", metric, outcome.best_score, outcome.best_params
            )
        else:
            logger.error(
                "No trial produced a usable '{}' value — nothing to select. Check that the "
                "training node logs that metric to the experiment tracker.",
                metric,
            )
            return ExitCode.GENERAL_ERROR.value

        if outcome.failures:
            logger.error("Search completed with {} failed trial(s)", outcome.failures)
            return ExitCode.GENERAL_ERROR.value
        logger.success("Ducta search execution completed successfully")
        return ExitCode.SUCCESS.value

    def _run_search_parallel(
        self, exec_obj, strategy, metric: str, base_hyperparams, search_id: str, workers: int
    ):
        """Run a grid/random search with concurrent trials."""
        from ducta.core.sweep import SearchOutcome, TrialOutcome, run_search

        proposals = []
        while (params := strategy.ask()) is not None:
            proposals.append(params)

        trials = []
        for index, params in enumerate(proposals, start=1):
            hyperparams = self._build_trial_hyperparams(base_hyperparams, params, search_id, index)
            trials.append({"index": index, "params": params, "hyperparams": hyperparams})

        results = self._run_trials_parallel(exec_obj, trials, search_id, workers)
        if results is None:
            queued = iter(proposals)

            class _Replay:
                direction = strategy.direction
                n_trials = strategy.n_trials

                def ask(self_inner):
                    return next(queued, None)

                def tell(self_inner, params, score):
                    strategy.tell(params, score)

                @property
                def best(self_inner):
                    return strategy.best

            run_trial = self._make_trial_runner(
                exec_obj, base_hyperparams, search_id, strategy.n_trials
            )
            return run_search(_Replay(), metric, run_trial, search_id=search_id)

        outcome = SearchOutcome(search_id=search_id, metric=metric, direction=strategy.direction)
        for result in results:
            params = result["params"]
            metrics = result["metrics"] or {}
            score = None
            failed = bool(result["failed"])
            reason = result["reason"]

            if not failed:
                if metric in metrics:
                    score = float(metrics[metric])
                else:
                    failed = True
                    reason = (
                        f"run logged no '{metric}' metric "
                        f"(logged: {', '.join(sorted(metrics)) or 'none'})"
                    )

            strategy.tell(params, score)
            outcome.trials.append(
                TrialOutcome(
                    index=result["index"],
                    params=params,
                    score=score,
                    failed=failed,
                    reason=reason,
                )
            )

        best = strategy.best
        if best is not None:
            outcome.best_params, outcome.best_score = best
        return outcome

    def _resolve_hyperparams_config(self, exec_obj):
        """Fetch the pipeline's HyperparamConfig via the Context, if any."""
        try:
            context = exec_obj.context
            if hasattr(context, "get_pipeline_ml_info"):
                ml_info = context.get_pipeline_ml_info(self.config.pipeline) or {}
                return ml_info.get("hyperparams_config")
        except Exception as e:
            logger.debug("Could not resolve hyperparams_config: {}", e)
        return None

    def _resolve_seed(self, exec_obj):
        """Global random seed, so a random/Bayesian search is reproducible."""
        try:
            gs = getattr(exec_obj.context, "global_config", {}) or {}
            seed = gs.get("random_seed")
            return int(seed) if seed is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _warn_if_parallel_spark(exec_obj, parallel: int) -> None:
        """Warn when Spark-backed pipelines run sweep/search trials in parallel."""
        spark = getattr(exec_obj.context, "spark", None)
        if spark is not None:
            logger.warning(
                "Pipeline uses Spark and sweep_parallel={} was requested: each worker "
                "process opens its own SparkSession/JVM, multiplying driver memory and "
                "startup cost. Consider --sweep-parallel=1 for Spark-backed pipelines, "
                "or reduce it.",
                parallel,
            )

    def _warn_if_sweep_without_validation_split(self, exec_obj) -> None:
        try:
            pipelines_config = getattr(exec_obj.context, "pipelines_config", {}) or {}
            pipeline_cfg = pipelines_config.get(self.config.pipeline, {}) or {}
            split = pipeline_cfg.get("split")
            if split is not None and hasattr(split, "model_dump"):
                split = split.model_dump()
            val_size = split.get("val_size") if isinstance(split, dict) else None
        except Exception:
            return
        if not split:
            logger.warning(
                "Sweep on pipeline '{}' without a declarative split: nothing enforces that candidates are selected on validation data. Define 'split' with 'val_size' in the pipeline config.",
                self.config.pipeline,
            )
        elif not val_size:
            logger.warning(
                "Sweep on pipeline '{}' whose split has no 'val_size': selecting the best run by test metrics invalidates the test estimate. Add 'val_size' to the split and select on validation metrics.",
                self.config.pipeline,
            )
