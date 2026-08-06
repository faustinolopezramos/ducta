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
from typing import Any, Dict, Optional

from loguru import logger

from ducta.console import execution
from ducta.console.config import ConfigManager
from ducta.console.core import CLIConfig, ExitCode


class ExecutionCommands:
    """Pipeline execution commands (ducta start)."""

    def __init__(self):
        self.config: Optional[CLIConfig] = None
        self.config_manager: Optional[ConfigManager] = None

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
            base_path=getattr(
                parsed_args, "base_path", self.config.base_path if self.config else None
            ),
            layer_name=getattr(
                parsed_args, "layer_name", self.config.layer_name if self.config else None
            ),
            use_case=getattr(
                parsed_args, "use_case_name", self.config.use_case_name if self.config else None
            ),
            config_type=getattr(
                parsed_args, "config_type", self.config.config_type if self.config else None
            ),
            interactive=getattr(parsed_args, "interactive", False)
            or (self.config.interactive if self.config else False),
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
                global_settings=layer_context_args["global_settings"],
                pipelines_config=layer_context_args["pipelines_config"],
                nodes_config=layer_context_args["nodes_config"],
                input_config=layer_context_args["input_config"],
                output_config=layer_context_args["output_config"],
                env=layer_env,
            )
            context._config_file_path = layer_context_args["global_settings"]
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

    def _sanity_layered(self, context, executor) -> int:
        from ducta.check.engine import QualityReporter, SanityPhaseRunner

        logger.info("Running sanity checks only (--sanity-only)")
        try:
            runner = SanityPhaseRunner(fail_fast=False)
            reports = runner.run_preflight_checks(
                {"nodes": context.nodes_config}, context, pipeline_name=self.config.pipeline
            )
            QualityReporter().render_pipeline_summary(reports, show_details=True)
            if all(r.passed for r in reports.values()):
                logger.success("All sanity checks passed!")
                return ExitCode.SUCCESS.value
            failed = sum(1 for r in reports.values() if not r.passed)
            logger.error("{} node(s) failed sanity checks", failed)
            return ExitCode.VALIDATION_ERROR.value
        except Exception as e:
            logger.error("Sanity check error: {}", e)
            return ExitCode.GENERAL_ERROR.value

    def _dry_run_layered(self, executor, layer_context_args) -> int:
        logger.info(
            "DRY-RUN MODE (layered): Pipeline will not be executed, only validated and logged"
        )
        try:
            pipeline_info = executor.get_pipeline_info(self.config.pipeline)
            raw_nodes = pipeline_info.get("nodes", [])
            pipeline_nodes = []
            for n in raw_nodes:
                if isinstance(n, dict):
                    pipeline_nodes.append(n.get("name") or list(n.keys())[0] if n else "unknown")
                else:
                    pipeline_nodes.append(str(n))
            logger.info(
                "DRY-RUN: Pipeline '{}' configuration in layer '{}'",
                self.config.pipeline,
                layer_context_args.get("layer"),
            )
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
            return ExitCode.SUCCESS.value
        except Exception as e:
            logger.error("Dry-run error: {}", e)
            return ExitCode.GENERAL_ERROR.value

    def _handle_validate_only(self, context_init) -> int:
        logger.info("Validating configuration...")
        context = context_init.initialize(self.config.env)
        logger.success("Configuration validation successful")
        logger.info("Execution Summary:")
        logger.info("  Environment: {}", context.env if hasattr(context, "env") else "base")
        logger.info("  Pipelines available: {}", len(getattr(context, "pipelines", {})))
        logger.info("  Nodes configured: {}", len(getattr(context, "nodes_config", {})))
        return ExitCode.SUCCESS.value

    def _handle_sanity_only(self, context_init) -> int:
        from ducta.check.engine import QualityReporter, SanityPhaseRunner

        logger.info("Running sanity checks on pipeline '{}'...", self.config.pipeline)
        context = context_init.initialize(self.config.env)
        try:
            pipeline_config = context.pipelines.get(self.config.pipeline)
            if not pipeline_config:
                logger.error("Pipeline '{}' not found", self.config.pipeline)
                return ExitCode.VALIDATION_ERROR.value
            runner = SanityPhaseRunner(fail_fast=False)
            node_configs = context.nodes_config
            reports = runner.run_preflight_checks(
                {"nodes": node_configs}, context, pipeline_name=self.config.pipeline
            )
            QualityReporter().render_pipeline_summary(reports, show_details=True)
            if all(r.passed for r in reports.values()):
                logger.success("All sanity checks passed!")
                return ExitCode.SUCCESS.value
            failed = sum(1 for r in reports.values() if not r.passed)
            logger.error("{} node(s) failed sanity checks", failed)
            return ExitCode.VALIDATION_ERROR.value
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
            raw_nodes = pipeline_info.get("nodes", [])
            pipeline_nodes = []
            for n in raw_nodes:
                if isinstance(n, dict):
                    pipeline_nodes.append(n.get("name") or list(n.keys())[0] if n else "unknown")
                else:
                    pipeline_nodes.append(str(n))
            logger.info("DRY-RUN: Pipeline '{}' configuration", self.config.pipeline)
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

        if self.config.sweep:
            return self._execute_sweep(exec_obj, base_hyperparams)

        # Everything the CLI needs to report now arrives on the result. This
        # used to reach through two levels of private attributes
        # (exec_obj._batch_executor.node_executor.gate_blocked) and had to know
        # which executor a given pipeline type happened to use.
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

        # `skip_downstream` (the default gate behavior) lets the run return
        # normally — no exception — so without this check a blocked gate looked
        # identical to a clean run and the CLI reported exit 0.
        from ducta.console.execution import report_run_outcome

        return report_run_outcome(result, pipeline=self.config.pipeline)

    def _execute_sweep(self, exec_obj, base_hyperparams) -> int:
        from ducta.core.sweep import SweepError, expand_sweep, load_sweep_spec, new_sweep_id

        try:
            spec = load_sweep_spec(self.config.sweep)
            combos = expand_sweep(spec)
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

        failures = 0
        for index, combo in enumerate(combos, start=1):
            hyperparams = {**(base_hyperparams or {}), **combo}
            hyperparams["sweep_id"] = sweep_id
            hyperparams["sweep_index"] = index
            logger.info("Sweep run {}/{}: {}", index, len(combos), combo)
            try:
                run = exec_obj.run_pipeline(
                    pipeline_name=self.config.pipeline,
                    node_name=self.config.node,
                    start_date=self.config.start_date,
                    end_date=self.config.end_date,
                    model_version=self.config.model_version,
                    hyperparams=hyperparams,
                )
                # A blocked quality gate does not raise, so counting only
                # exceptions reported a sweep run that produced nothing as a
                # success and skewed the comparison the sweep exists to make.
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

        succeeded = len(combos) - failures
        logger.info(
            "Sweep {} finished: {}/{} run(s) succeeded. Compare runs in the experiment tracker filtering by tag sweep_id={}",
            sweep_id,
            succeeded,
            len(combos),
            sweep_id,
        )
        if failures:
            logger.error("Sweep completed with {} failed run(s)", failures)
            return ExitCode.GENERAL_ERROR.value
        logger.success("Ducta sweep execution completed successfully")
        return ExitCode.SUCCESS.value

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
