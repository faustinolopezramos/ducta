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

import inspect
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from concurrent.futures import as_completed as thread_as_completed
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from loguru import logger  # type: ignore

from ducta.check import (
    QualityOutputConfig,
    QualityOutputManager,
    QualityReport,
    QualityReporter,
    SanityPhaseRunner,
)
from ducta.core.commands import Command, MLNodeCommand, NodeCommand
from ducta.core.execution_context import node_id_var
from ducta.core.import_security import ModuleImportError, SecureModuleImporter
from ducta.core.pipeline_validator import PipelineValidator
from ducta.core.resource_manager import get_resource_manager
from ducta.core.utils import compile_function


class ThreadSafeExecutionState:
    """Thread-safe execution state for parallel node execution."""

    def __init__(self, execution_order: List[str], node_configs: Dict[str, Dict[str, Any]]):
        self._lock = threading.RLock()
        self.ready_queue = deque()
        self.running: Dict = {}
        self.completed: Set[str] = set()
        self.failed = False
        self.execution_results: Dict[str, Any] = {}
        # Nodes skipped because an upstream quality gate blocked (skip_downstream),
        # and nodes whose gate blocked. Neither counts as failure.
        self.skipped: Dict[str, str] = {}
        self.gate_blocked: Dict[str, Any] = {}
        # Merged (explicit ∪ dataset-inferred) deps — the same source of truth
        # build_dependency_graph uses, so runtime readiness matches the DAG.
        # warn=False here: build_dependency_graph already emitted any warnings.
        from ducta.core.dependency_inference import resolve_node_dependencies

        self.node_deps: Dict[str, List[str]] = resolve_node_dependencies(
            execution_order, node_configs, warn=False
        )
        self._initialize_ready_queue(execution_order)

    def _initialize_ready_queue(self, execution_order: List[str]) -> None:
        """Initialize queue with nodes that have no dependencies."""
        for node in execution_order:
            if not self.node_deps[node]:
                self.ready_queue.append(node)

    def mark_completed(self, node_name: str, result: Dict[str, Any]) -> None:
        """Thread-safe mark node as completed."""
        with self._lock:
            self.completed.add(node_name)
            self.execution_results[node_name] = result

    def mark_failed(self, node_name: str, error_info: Dict[str, Any]) -> None:
        """Thread-safe mark node as failed and store result."""
        with self._lock:
            self.failed = True
            self.execution_results[node_name] = error_info

    def mark_gate_blocked(self, node_name: str, info: Dict[str, Any]) -> None:
        """Record a node whose quality gate blocked (not a failure)."""
        with self._lock:
            self.gate_blocked[node_name] = info
            self.execution_results[node_name] = info

    def mark_skipped(self, node_name: str, reason: str) -> None:
        """Record a node skipped because an upstream gate blocked (not a failure)."""
        with self._lock:
            self.skipped[node_name] = reason

    def is_completed(self, node_name: str) -> bool:
        """Thread-safe check if node is completed."""
        with self._lock:
            return node_name in self.completed

    def add_to_ready_queue(self, nodes: List[str]) -> None:
        """Thread-safe add nodes to ready queue."""
        with self._lock:
            self.ready_queue.extend(nodes)

    def pop_ready_node(self) -> Optional[str]:
        """Thread-safe pop node from ready queue."""
        with self._lock:
            if self.ready_queue:
                return self.ready_queue.popleft()
            return None

    def add_running_future(self, future, node_info: Dict[str, Any]) -> None:
        """Thread-safe add running future."""
        with self._lock:
            self.running[future] = node_info

    def remove_running_future(self, future) -> Optional[Dict[str, Any]]:
        """Thread-safe remove running future."""
        with self._lock:
            return self.running.pop(future, None)

    def get_running_count(self) -> int:
        """Thread-safe get count of running nodes."""
        with self._lock:
            return len(self.running)

    def has_work_pending(self) -> bool:
        """Thread-safe check if there's work pending."""
        with self._lock:
            return bool(self.ready_queue or self.running) and not self.failed

    def has_ready_nodes(self) -> bool:
        """Thread-safe check if any node is waiting in the ready queue."""
        with self._lock:
            return bool(self.ready_queue)

    def get_running_futures_snapshot(self) -> List:
        """Thread-safe snapshot of running future keys."""
        with self._lock:
            return list(self.running.keys())

    def get_running_items_snapshot(self) -> List:
        """Thread-safe snapshot of running (future, node_info) pairs."""
        with self._lock:
            return list(self.running.items())

    def get_running_node_names(self) -> Set[str]:
        """Thread-safe get set of currently running node names."""
        with self._lock:
            return {info["node_name"] for info in self.running.values()}

    def get_queued_node_names(self) -> Set[str]:
        """Thread-safe get set of queued node names."""
        with self._lock:
            return set(self.ready_queue)

    def get_completed_count(self) -> int:
        """Thread-safe get count of completed nodes."""
        with self._lock:
            return len(self.completed)

    def get_execution_results_copy(self) -> Dict[str, Any]:
        """Thread-safe copy of execution results."""
        with self._lock:
            return dict(self.execution_results)

    def is_failed(self) -> bool:
        """Thread-safe check if execution has failed."""
        with self._lock:
            return self.failed

    def set_failed(self) -> None:
        """Thread-safe set failed flag."""
        with self._lock:
            self.failed = True

    def check_running_future(self, future) -> Optional[Dict[str, Any]]:
        """Thread-safe check if a future is still in running dict."""
        with self._lock:
            return self.running.get(future)

    def get_unaccounted_nodes(self) -> Set[str]:
        """Nodes with no recorded outcome (not completed, skipped, or gate-blocked)."""
        with self._lock:
            return set(self.node_deps) - self.completed - set(self.skipped) - set(self.gate_blocked)


class FunctionLoader:
    """Loads and caches node functions with security validation."""

    def __init__(self, context: Any, is_ml_layer: bool = False) -> None:
        self.context = context
        self.is_ml_layer = is_ml_layer
        self._function_cache: Dict[tuple, Callable] = {}
        self._init_secure_importer()

    def _init_secure_importer(self) -> None:
        """Initialize secure module importer with context-specific configuration."""
        allowed_prefixes = getattr(self.context, "allowed_module_prefixes", None)
        additional_paths = self._gather_search_paths()
        # Whitelist enforcement is on by default; global_settings.strict_module_import: false
        # is an explicit, logged opt-out for projects that import from outside the whitelist.
        gs = getattr(self.context, "global_settings", {}) or {}
        gs_strict = gs.get("strict_module_import", True) if isinstance(gs, dict) else True
        strict_mode = getattr(self.context, "strict_module_import", gs_strict)
        self.secure_importer = SecureModuleImporter(
            allowed_prefixes=allowed_prefixes,
            additional_search_paths=additional_paths,
            strict_mode=strict_mode,
        )
        logger.debug(
            "Secure module importer initialized (strict={}) with {} search paths",
            strict_mode,
            len(additional_paths),
        )

    def _gather_search_paths(self) -> List[Path]:
        """Gather additional module search paths from context and environment."""
        paths = []
        try:
            cwd = Path.cwd()
            paths.append(cwd)
            paths.append(cwd / "src")
            paths.append(cwd / "lib")
        except Exception as e:
            logger.debug("Could not access current working directory: {}", e)

        try:
            config_paths = getattr(self.context, "config_paths", None)
            if isinstance(config_paths, dict) and config_paths:
                first_path = next(iter(config_paths.values()))
                parent = Path(first_path).parent
                paths.append(parent)
                paths.append(parent / "src")
        except Exception:
            pass

        if hasattr(self.context, "_config_file_path"):
            try:
                config_file = Path(self.context._config_file_path)
                paths.append(config_file.parent)
                paths.append(config_file.parent / "src")
            except Exception:
                pass

        seen = set()
        unique_paths = []
        for path in paths:
            path_str = str(path)
            if path_str not in seen:
                seen.add(path_str)
                unique_paths.append(path)

        return unique_paths

    def load(self, node: Dict[str, Any]) -> Callable:
        """Load a node's function with comprehensive validation and security."""
        module_path = node.get("module")
        function_name = node.get("function")

        if not module_path or not function_name:
            node_name = node.get("name", "unknown")
            missing = []
            if not module_path:
                missing.append("'module'")
            if not function_name:
                missing.append("'function'")
            raise ValueError(
                f"Node configuration for '{node_name}' must include 'module' and 'function'. "
                f"Missing: {', '.join(missing)}. Configuration found: {node}"
            )

        cache_key = (module_path, function_name)
        cached = self._function_cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            func = self.secure_importer.get_function_from_module(module_path, function_name)

            # Performance Phase 3: Apply JIT compilation if function is decorated with @ducta.jit
            func = compile_function(func)

            try:
                sig = inspect.signature(func)
                params = list(sig.parameters.keys())

                required_params = {"start_date", "end_date"}
                if not required_params.issubset(params):
                    logger.warning(
                        "Function '{}' may not accept required parameters: "
                        "start_date and end_date. Parameters found: {}",
                        function_name,
                        params,
                    )

                if self.is_ml_layer and "ml_context" not in params:
                    accepts_kwargs = any(
                        p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
                    )
                    if not accepts_kwargs:
                        logger.debug(
                            "Function '{}' doesn't accept 'ml_context' parameter nor **kwargs. "
                            "ML-specific features may not be available.",
                            function_name,
                        )
            except ValueError as e:
                logger.warning("Signature validation skipped for {}: {}", function_name, e)

            self._function_cache[cache_key] = func
            return func

        except ModuleImportError as e:
            logger.error("Security validation failed for module '{}': {}", module_path, e)
            raise ValueError(f"Cannot load node function: {e}") from e
        except Exception as e:
            logger.error(
                "Unexpected error loading function '{}' from '{}': {}",
                function_name,
                module_path,
                e,
            )
            raise


class QualityCheckExecutor:
    """Runs pre- and post-execution quality checks for a node."""

    # Minimal structural floor for ML pipelines without explicit sanity
    # config: training on an empty input is always a bug worth aborting.
    DEFAULT_ML_SANITY_CONFIG = {
        "enabled": True,
        "fail_fast": True,
        "checks": {"empty_dataset": {}},
    }

    def __init__(self, context: Any, quality_output_manager: Optional[Any] = None) -> None:
        self.context = context
        self.quality_output_manager = quality_output_manager

    def _load_quality_profiles(self) -> Dict[str, Any]:
        """Load quality profiles from global_settings."""
        try:
            from ducta.check.profiles import load_profiles as _load_profiles

            gs = getattr(self.context, "global_settings", {}) or {}
            return _load_profiles(gs) if isinstance(gs, dict) else {}
        except Exception:
            return {}

    def _ml_default_sanity_enabled(self) -> bool:
        """Whether global settings allow the default ML sanity checks (on by default)."""
        gs = getattr(self.context, "global_settings", {}) or {}
        if isinstance(gs, dict):
            return bool(gs.get("ml_default_sanity_checks", True))
        return bool(getattr(gs, "ml_default_sanity_checks", True))

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
            results = getattr(self.context, "_quality_results", None)
            if isinstance(results, list):
                results.append(entry)
        except Exception as e:  # noqa: BLE001
            logger.debug("Could not deposit quality summary for '{}': {}", node_name, e)

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
                "global_settings.ml_default_sanity_checks=false.",
                node_name,
                ", ".join(sanity_config["checks"]),
            )
        # A declared sanity_checks block is active unless explicitly disabled
        # (matches SanityChecksSchema's enabled default of True).
        if not sanity_config or not sanity_config.get("enabled", True):
            return None

        profiles = self._load_quality_profiles()
        runner = SanityPhaseRunner(
            fail_fast=sanity_config.get("fail_fast", True), profiles=profiles
        )
        run_kwargs = {"pipeline_name": pipeline_name} if pipeline_name else {}
        report = runner.run_node_checks(dfs, node_config, node_name, **run_kwargs)

        QualityReporter().render_report(report)

        if not report.passed and sanity_config.get("fail_fast", True):
            raise Exception(
                f"Sanity checks failed for node '{node_name}': {report.errors_count} error(s)"
            )

        self._deposit_quality_summary(node_name, "sanity", report)
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
        # A declared data_quality block is active unless explicitly disabled
        # (matches DataQualitySchema's enabled default of True).
        dq_config = node_config.get("data_quality")
        if not dq_config or not dq_config.get("enabled", True):
            return None

        if result_df is None:
            logger.debug(f"Skipping DQ checks for '{node_name}': result_df is None")
            return None

        try:
            from ducta.check import ValidationPhaseRunner

            profiles = self._load_quality_profiles()

            # Extract global Quality Gate config from global_settings.quality.gate
            _global_settings = getattr(self.context, "global_settings", {}) or {}
            _global_gate_cfg = (
                (_global_settings.get("quality") or {}).get("gate")
                if isinstance(_global_settings, dict)
                else None
            )

            # Instantiate runner — uses context.output_path via ContextAwareStorageBackend
            runner = ValidationPhaseRunner(
                context=self.context,
                fail_fast=dq_config.get("fail_fast", False),
                profiles=profiles,
                global_gate_config=_global_gate_cfg,
            )

            # Run checks
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

            # Render report
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

            # Gate blocks and fail-fast aborts always propagate
            if isinstance(e, (QualityGateBlocked, QualityChecksFailed)):
                raise
            logger.error(f"Data quality check execution failed for node '{node_name}': {e}")
            if dq_config.get("fail_fast", False):
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
                global_quality = {}
                if self.context and hasattr(self.context, "global_settings"):
                    global_quality = (self.context.global_settings or {}).get("quality", {})
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


class OutputWriter:
    """Validates and persists node output DataFrames."""

    def __init__(self, output_manager: Any, context: Any, is_ml_layer: bool = False) -> None:
        self.output_manager = output_manager
        self.context = context
        self.is_ml_layer = is_ml_layer

    def display_schema(self, result_df: Any, node_name: str) -> None:
        """Print the 'DATA SCHEMA' panel for a node result (Spark or pandas)."""
        is_spark = hasattr(result_df, "printSchema")
        is_pandas = False
        if not is_spark:
            try:
                import pandas as pd  # type: ignore

                is_pandas = isinstance(result_df, pd.DataFrame)
            except Exception:
                is_pandas = False

        if not (is_spark or is_pandas):
            return

        node_display_name = node_name.replace(".", " › ")
        console = None
        try:
            from ducta.console.ux.rich_logger import RichLoggerManager, print_process_separator

            console = RichLoggerManager.get_console()
            console.print()
            print_process_separator("schema", "DATA SCHEMA", node_display_name, console)
            console.print()
        except Exception as e:
            logger.debug("Could not print schema separator: {}", e)

        try:
            if is_spark:
                schema_output = ""
                try:
                    schema_output = result_df._jdf.schema().treeString()
                except Exception as e:
                    logger.debug("Could not extract schema tree string: {}", e)

                from ducta.console.ux.schema_formatter import print_spark_schema

                print_spark_schema(schema_output, title=node_display_name, console=console)
            else:
                from ducta.console.ux.schema_formatter import print_pandas_schema

                print_pandas_schema(result_df, title=node_display_name, console=console)
        except Exception as e:
            logger.warning("Could not format schema as table: {}", e)

    def save(
        self,
        result_df: Any,
        node_config: Dict[str, Any],
        node_name: str,
        start_date: str,
        end_date: str,
        ml_info: Dict[str, Any],
    ) -> None:
        """Enhanced validation and output saving with ML metadata."""
        if isinstance(result_df, str) and ("://" in result_df or "model_registry" in result_df):
            logger.info("Node '{}' output is an artifact URI. Skipping standard saving.", node_name)
            return

        PipelineValidator.validate_dataframe_schema(result_df)
        self.display_schema(result_df, node_name)

        env = getattr(self.context, "env", None)
        if not env:
            gs = getattr(self.context, "global_settings", {}) or {}
            env = gs.get("env") or gs.get("environment")

        output_params = {
            "node": node_config,
            "dataframe": result_df,
            "start_date": start_date,
            "end_date": end_date,
        }

        if self.is_ml_layer:
            output_params["model_version"] = ml_info["model_version"]

        self.output_manager.save_output(env, **output_params)

        try:
            from rich.text import Text  # type: ignore

            from ducta.console.ux.rich_logger import RichLoggerManager

            console = RichLoggerManager.get_console()
            line = Text("  ")
            line.append("✓ ", style="bright_green")
            line.append(f"Output saved for node '{node_name}'", style="white")
            console.print(line)
            console.print()
        except Exception:
            logger.info("Output saved successfully for node '{}'", node_name)


class MLContextBuilder:
    """Builds ML commands and prepares per-node ML metadata."""

    def __init__(self, context: Any, mlops_context: Optional[Any], is_ml_layer: bool) -> None:
        self.context = context
        self.mlops_context = mlops_context
        self.is_ml_layer = is_ml_layer

    def is_ml_node(self, node_config: Dict[str, Any], ml_info: Dict[str, Any]) -> bool:
        """Decide whether a node must receive the ML context."""
        return (
            node_config.get("ml_stage") is not None
            or self.is_ml_layer
            or ml_info.get("pipeline_type") == "ml"
            or ml_info.get("split") is not None
        )

    def create_command(
        self,
        function: Callable,
        input_dfs: List[Any],
        start_date: str,
        end_date: str,
        node_name: str,
        ml_info: Dict[str, Any],
        node_config: Dict[str, Any],
        input_names: Optional[List[str]] = None,
    ) -> Command:
        """Create appropriate command based on ML stage or layer type."""
        if self.is_ml_node(node_config, ml_info):
            return self._create_ml_command(
                function,
                input_dfs,
                start_date,
                end_date,
                node_name,
                ml_info,
                node_config,
                input_names,
            )
        return NodeCommand(
            function=function,
            input_dfs=input_dfs,
            start_date=start_date,
            end_date=end_date,
            node_name=node_name,
            node_config=node_config,
            input_names=input_names,
        )

    def _create_ml_command(
        self,
        function: Callable,
        input_dfs: List[Any],
        start_date: str,
        end_date: str,
        node_name: str,
        ml_info: Dict[str, Any],
        node_config: Dict[str, Any],
        input_names: Optional[List[str]] = None,
    ) -> Command:
        """Create ML command (either standard or experiment)."""
        common_params = {
            "function": function,
            "input_dfs": input_dfs,
            "start_date": start_date,
            "end_date": end_date,
            "node_name": node_name,
            "model_version": ml_info.get("model_version"),
            "hyperparams": ml_info.get("hyperparams", {}),
            "hyperparams_config": ml_info.get("hyperparams_config"),
            "node_config": node_config,
            "pipeline_config": ml_info.get("pipeline_config", {}),
            "mlops_context": self.mlops_context,
            "mlops_run_id": ml_info.get("mlops_run_id"),
            "seed": ml_info.get("seed"),
            "split": ml_info.get("split"),
            "input_names": input_names,
        }

        if hasattr(self.context, "spark"):
            common_params["spark"] = self.context.spark

        return MLNodeCommand(**common_params)

    def prepare_node_ml_info(self, node_name: str, ml_info: Dict[str, Any]) -> Dict[str, Any]:
        """Prepare node-specific ML information."""
        node_config = self.context.nodes_config.get(node_name, {}) or {}
        if not self.is_ml_node(node_config, ml_info):
            return ml_info

        node_ml_config = self.context.get_node_ml_config(node_name)
        enhanced_ml_info = ml_info.copy()
        node_hyperparams = enhanced_ml_info.get("hyperparams", {}).copy()
        node_hyperparams.update(node_ml_config.get("hyperparams", {}))
        enhanced_ml_info["hyperparams"] = node_hyperparams
        enhanced_ml_info["node_config"] = node_ml_config

        return enhanced_ml_info


class IngestionExecutor:
    """Executes declarative JDBC ingestion nodes (``type: ingestion``) natively."""

    DEFAULT_SOURCES_PATH = "config/sources.yaml"

    def __init__(
        self,
        context: Any,
        output_writer: "OutputWriter",
        quality_executor: QualityCheckExecutor,
    ) -> None:
        self.context = context
        self.output_writer = output_writer
        self._quality_executor = quality_executor

    def _resolve_sources_path(self, node_config: Dict[str, Any]) -> Path:
        """Resolve the sources file path."""
        node_path = node_config.get("sources")
        if node_path:
            return Path(node_path)

        config_paths = getattr(self.context, "config_paths", None) or {}
        if isinstance(config_paths, dict) and config_paths.get("sources_config_path"):
            return Path(config_paths["sources_config_path"])

        gs = getattr(self.context, "global_settings", {}) or {}
        if isinstance(gs, dict):
            ingestion_cfg = gs.get("ingestion") or {}
            if isinstance(ingestion_cfg, dict) and ingestion_cfg.get("sources_path"):
                return Path(ingestion_cfg["sources_path"])

        return Path(self.DEFAULT_SOURCES_PATH)

    def _get_connection_manager(self, sources_path: Path) -> Any:
        """Get (or lazily create and cache) a ConnectionManager for a sources file."""
        from ducta.gate.gateway import ConnectionManager

        cache = getattr(self.context, "_ingestion_managers", None)
        if cache is None:
            cache = {}
            setattr(self.context, "_ingestion_managers", cache)

        key = str(sources_path)
        if key not in cache:
            cache[key] = ConnectionManager(sources_path)
        return cache[key]

    @staticmethod
    def _build_dbtable(node_name: str, table: str, columns, where) -> str:
        """Compose a `dbtable` value, optionally selecting columns / filtering rows."""
        if not columns and not where:
            return table

        if columns:
            if not isinstance(columns, (list, tuple)) or not all(
                isinstance(c, str) for c in columns
            ):
                raise ValueError(
                    f"Ingestion node '{node_name}': 'columns' must be a list of column names."
                )
            select = ", ".join(columns)
        else:
            select = "*"

        sql = f"SELECT {select} FROM {table}"
        if where:
            sql += f" WHERE {where}"
        return f"({sql}) AS q"

    def execute(
        self,
        node_name: str,
        node_config: Dict[str, Any],
        start_date: str,
        end_date: str,
        ml_info: Dict[str, Any],
        pipeline_name: Optional[str] = None,
    ) -> None:
        """Read a table/query from a configured JDBC source into Bronze."""
        source = node_config.get("source")
        table = node_config.get("table")
        query = node_config.get("query")
        columns = node_config.get("columns")
        where = node_config.get("where")
        options = node_config.get("options") or {}

        if not source:
            raise ValueError(
                f"Ingestion node '{node_name}' requires a 'source' field "
                "(a connection name defined in config/sources.yaml)."
            )
        if bool(table) == bool(query):
            raise ValueError(
                f"Ingestion node '{node_name}' requires exactly one of 'table' or 'query'."
            )
        if query and (columns or where):
            raise ValueError(
                f"Ingestion node '{node_name}': 'columns'/'where' cannot be combined "
                "with 'query' (put the projection/filter inside the query)."
            )
        if not isinstance(options, dict):
            raise ValueError(
                f"Ingestion node '{node_name}': 'options' must be a mapping of Spark "
                "JDBC read options."
            )

        spark = getattr(self.context, "spark", None)
        if spark is None:
            raise RuntimeError(
                f"Ingestion node '{node_name}': no SparkSession available in the Ducta context."
            )

        sources_path = self._resolve_sources_path(node_config)
        manager = self._get_connection_manager(sources_path)
        conn = manager.get(source)

        opts: Dict[str, str] = {
            "url": conn.jdbc_url,
            "user": conn.jdbc_properties["user"],
            "password": conn.jdbc_properties["password"],
            "driver": conn.jdbc_properties["driver"],
        }
        if query:
            opts["query"] = query
        else:
            opts["dbtable"] = self._build_dbtable(node_name, table, columns, where)

        opts.update({k: str(v) for k, v in options.items()})

        logger.info(
            "Ingestion node '{}': reading {} from source '{}'",
            node_name,
            f"table '{table}'" if table else "query",
            source,
        )

        result_df = spark.read.format("jdbc").options(**opts).load()

        # Sanity checks (e.g. empty_dataset) on the freshly read data.
        sanity_report = self._quality_executor.run_sanity_checks(
            [result_df], node_config, node_name, pipeline_name=pipeline_name
        )
        self._quality_executor.persist_report(
            sanity_report,
            "sanity",
            "sanity_checks",
            node_name,
            node_config,
            ml_info,
            pipeline_name=pipeline_name,
        )

        # Post-read data quality checks (before persisting, mirroring batch nodes).
        dq_report = self._quality_executor.run_dq_checks(
            result_df, node_config, node_name, pipeline_name=pipeline_name
        )
        self._quality_executor.persist_report(
            dq_report,
            "dq",
            "data_quality",
            node_name,
            node_config,
            ml_info,
            pipeline_name=pipeline_name,
        )

        # Persist to Bronze using the same path as regular nodes.
        self.output_writer.save(result_df, node_config, node_name, start_date, end_date, ml_info)

        logger.info("Ingestion node '{}' completed successfully", node_name)


class ParallelCoordinator:
    """Coordinates parallel execution of nodes respecting DAG dependencies."""

    def __init__(
        self,
        context: Any,
        max_workers: int,
        node_timeout: int,
        is_ml_layer: bool,
        execute_callback: Callable,
        ml_builder: MLContextBuilder,
    ) -> None:
        self.context = context
        self.max_workers = max_workers
        self.node_timeout = node_timeout
        self.is_ml_layer = is_ml_layer
        self._execute_single_node = execute_callback
        self._ml_builder = ml_builder

    def coordinate(
        self,
        executor: ThreadPoolExecutor,
        execution_state: ThreadSafeExecutionState,
        dag: Dict[str, Set[str]],
        node_configs: Dict[str, Dict[str, Any]],
        start_date: str,
        end_date: str,
        ml_info: Dict[str, Any],
    ) -> None:
        """Coordinate the main execution loop until all nodes complete or failure occurs."""
        while execution_state.has_work_pending():
            self._submit_ready_nodes(
                execution_state=execution_state,
                executor=executor,
                start_date=start_date,
                end_date=end_date,
                ml_info=ml_info,
                node_configs=node_configs,
            )

            if execution_state.get_running_count() > 0:
                self._process_completed_nodes(
                    execution_state=execution_state,
                    dag=dag,
                )

        if execution_state.get_running_count() > 0:
            logger.warning(
                "Pipeline ended with {} unfinished futures",
                execution_state.get_running_count(),
            )
            self._handle_unfinished_futures(execution_state)

    def cleanup(
        self,
        execution_state: ThreadSafeExecutionState,
        ml_info: Dict[str, Any],
    ) -> None:
        """Cleanup resources and handle final state after execution completes."""
        self._cleanup_futures(execution_state.get_running_items_snapshot())

        if execution_state.is_failed():
            raise RuntimeError("Pipeline execution failed due to node failures")

        # Every node must be accounted for: completed, skipped, or gate-blocked.
        # A node whose dependency lives outside the pipeline would otherwise
        # never become ready and the loop would end without executing it.
        unexecuted = execution_state.get_unaccounted_nodes()
        if unexecuted:
            raise RuntimeError(
                f"Pipeline ended with {len(unexecuted)} node(s) never executed: "
                f"{sorted(unexecuted)}. Check that their dependencies are part of "
                "this pipeline."
            )

        if self.is_ml_layer:
            self._log_ml_pipeline_summary(execution_state.execution_results, ml_info)

        try:
            from ducta.console.ux.rich_logger import RichLoggerManager, print_process_separator

            console = RichLoggerManager.get_console()
            console.print()
            total_nodes = execution_state.get_completed_count()
            print_process_separator("summary", "EXECUTION SUMMARY", f"{total_nodes} nodes", console)
            console.print()
        except Exception:
            pass

        logger.info(
            f"Pipeline execution completed. Processed {execution_state.get_completed_count()} nodes."
        )

    def cancel_all(self, running_snapshot: List) -> None:
        """Cancel all running futures from a snapshot of (future, node_info) pairs."""
        logger.warning("Cancelling {} running futures", len(running_snapshot))
        for future, node_info in running_snapshot:
            node_name = node_info["node_name"]
            logger.warning("Cancelling future for node '{}'", node_name)
            try:
                future.cancel()
            except Exception:
                logger.debug("Could not cancel future for node '{}'", node_name)

    def _submit_ready_nodes(
        self,
        execution_state: ThreadSafeExecutionState,
        executor: ThreadPoolExecutor,
        start_date: str,
        end_date: str,
        ml_info: Dict[str, Any],
        node_configs: Dict[str, Dict[str, Any]],
    ) -> None:
        """Submit ready nodes for execution with enhanced context."""
        while execution_state.get_running_count() < self.max_workers:
            node_name = execution_state.pop_ready_node()
            if not node_name:
                break

            try:
                from ducta.console.ux.rich_logger import log_node_start

                node_display = node_name.split(".")[-1] if "." in node_name else node_name
                log_node_start(node_display, "")
            except Exception:
                logger.info("Starting execution of node: {}", node_name)

            node_ml_info = self._ml_builder.prepare_node_ml_info(node_name, ml_info)

            future = executor.submit(
                self._execute_single_node, node_name, start_date, end_date, node_ml_info
            )
            execution_state.add_running_future(
                future,
                {
                    "node_name": node_name,
                    "start_time": time.time(),
                    "config": node_configs.get(node_name, {}),
                },
            )

    def _process_completed_nodes(
        self,
        execution_state: ThreadSafeExecutionState,
        dag: Dict[str, Set[str]],
    ) -> None:
        """Process completed nodes with timeout protection to prevent deadlock."""
        if execution_state.get_running_count() == 0:
            return

        future_list = execution_state.get_running_futures_snapshot()
        completed_futures = []
        gs = getattr(self.context, "global_settings", {}) or {}
        max_timeout = gs.get(
            "execution_timeout_seconds",
            getattr(self.context, "execution_timeout_seconds", 3600),
        )
        processing_timeout = min(30, max_timeout / 2)  # 30s or half of max

        try:
            for future in thread_as_completed(future_list, timeout=processing_timeout):
                completed_futures.append(future)
                node_info = execution_state.remove_running_future(future)
                if not node_info:
                    continue

                node_name = node_info["node_name"]
                should_break = self._handle_completed_future(
                    future, node_name, node_info, execution_state, dag
                )
                if should_break:
                    break

                if execution_state.has_ready_nodes():
                    break

        except TimeoutError:
            logger.warning(
                "Timeout ({}s) waiting for node completion. {} nodes still running.",
                processing_timeout,
                execution_state.get_running_count(),
            )
        except Exception as e:
            logger.error("Unexpected error in _process_completed_nodes: {}", e)
            execution_state.set_failed()

        for future in completed_futures:
            if execution_state.check_running_future(future):
                execution_state.remove_running_future(future)

        self._fail_timed_out_nodes(execution_state)

        if execution_state.is_failed():
            self.cancel_all(execution_state.get_running_items_snapshot())

    def _fail_timed_out_nodes(self, execution_state: ThreadSafeExecutionState) -> None:
        """Mark any running node that exceeded ``node_timeout`` as failed."""
        now = time.time()
        for future, node_info in execution_state.get_running_items_snapshot():
            elapsed = now - node_info["start_time"]
            if elapsed <= self.node_timeout:
                continue

            node_name = node_info["node_name"]
            logger.error(
                "Node '{}' exceeded node timeout ({:.0f}s > {}s) — aborting pipeline. "
                "The underlying thread cannot be killed and may keep running until "
                "the process exits.",
                node_name,
                elapsed,
                self.node_timeout,
            )
            execution_state.mark_failed(
                node_name,
                {
                    "status": "failed",
                    "error": f"Node execution timeout exceeded ({self.node_timeout}s)",
                    "error_type": "TimeoutError",
                    "start_time": node_info["start_time"],
                    "end_time": now,
                    "config": node_info.get("config", {}),
                },
            )
            execution_state.remove_running_future(future)
            try:
                future.cancel()
            except Exception:
                logger.debug("Could not cancel timed-out future for node '{}'", node_name)

    def _handle_completed_future(
        self,
        future,
        node_name: str,
        node_info: Dict[str, Any],
        execution_state: ThreadSafeExecutionState,
        dag: Dict[str, Set[str]],
    ) -> bool:
        """Handle a single completed future. Returns True if execution should break."""
        from ducta.check.core import QualityGateBlocked
        from ducta.gate.exceptions import MissingDependencyError

        try:
            future.result(timeout=5)
            self._handle_node_success(node_name, node_info, execution_state, dag)
            return False

        except TimeoutError as te:
            self._handle_node_timeout(node_name, node_info, execution_state, te)
            return True

        except QualityGateBlocked as gb:
            return self._handle_gate_block(node_name, node_info, execution_state, dag, gb)

        except MissingDependencyError as mde:
            return self._handle_missing_deps_skip(node_name, execution_state, dag, mde)

        except Exception as e:
            self._handle_node_failure(node_name, node_info, execution_state, e)
            return True

    def _handle_gate_block(
        self,
        node_name: str,
        node_info: Dict[str, Any],
        execution_state: ThreadSafeExecutionState,
        dag: Dict[str, Set[str]],
        gate_blocked: Exception,
    ) -> bool:
        """Apply a blocking quality gate's behavior. Returns True to abort the run.

        ``stop_all`` fails the pipeline (legacy behavior). ``skip_downstream`` (the
        default) records the block, marks the node's transitive descendants as
        skipped, and lets independent branches finish.
        """
        gate_result = getattr(gate_blocked, "gate_result", None)
        behavior = (
            getattr(getattr(gate_result, "behavior", None), "value", None) or "skip_downstream"
        )

        if behavior == "stop_all":
            self._handle_node_failure(node_name, node_info, execution_state, gate_blocked)
            return True

        info = {
            "status": "gate_blocked",
            "error": str(gate_blocked),
            "start_time": node_info.get("start_time"),
            "end_time": time.time(),
            "config": node_info.get("config", {}),
        }
        execution_state.mark_gate_blocked(node_name, info)
        # The blocked node already recorded its own "gate_blocked" trace from its
        # worker; here we only record the descendants we are skipping.
        descendants = self._transitive_descendants(node_name, dag)
        for dep in descendants:
            reason = f"skipped: upstream quality gate blocked at '{node_name}'"
            execution_state.mark_skipped(dep, reason)
            self._record_trace(dep, "skipped", reason)

        logger.warning(
            "Quality gate blocked node '{}' (behavior=skip_downstream); skipping {} "
            "descendant(s): {}",
            node_name,
            len(descendants),
            sorted(descendants),
        )
        return False

    def _handle_missing_deps_skip(
        self,
        node_name: str,
        execution_state: ThreadSafeExecutionState,
        dag: Dict[str, Set[str]],
        missing_deps: Exception,
    ) -> bool:
        """Skip a node whose declared inputs aren't available yet (e.g. an
        upstream dependency hasn't run), and cascade the skip to its
        transitive descendants — same mechanism as a blocked quality gate,
        different trigger. Never a failure; returns False (doesn't abort the
        run).
        """
        reason = f"skipped: missing inputs — {missing_deps}"
        execution_state.mark_skipped(node_name, reason)
        self._record_trace(node_name, "skipped", reason)

        descendants = self._transitive_descendants(node_name, dag)
        for dep in descendants:
            dep_reason = f"skipped: missing inputs — upstream node '{node_name}' skipped"
            execution_state.mark_skipped(dep, dep_reason)
            self._record_trace(dep, "skipped", dep_reason)

        logger.warning(
            "Node '{}' skipped (missing dependencies); skipping {} descendant(s): {}",
            node_name,
            len(descendants),
            sorted(descendants),
        )
        return False

    def _record_trace(self, node_name: str, status: str, error: Optional[str]) -> None:
        """Append a node outcome to ``context._run_node_details`` (for the certificate).

        Runs in the single coordinate loop; ``list.append`` is atomic under the GIL.
        """
        try:
            node_config = (getattr(self.context, "nodes_config", {}) or {}).get(node_name, {}) or {}
            raw_out = node_config.get("output", [])
            outputs = list(raw_out.values()) if isinstance(raw_out, dict) else list(raw_out or [])
            record = {
                "name": node_name,
                "type": node_config.get("type", "batch"),
                "status": status,
                "duration_seconds": 0.0,
                "outputs": outputs,
                "error": error,
            }
            trace = getattr(self.context, "_run_node_details", None)
            if isinstance(trace, list):
                trace.append(record)
        except Exception as e:  # noqa: BLE001
            logger.debug("Could not record trace for '{}': {}", node_name, e)

    @staticmethod
    def _transitive_descendants(node_name: str, dag: Dict[str, Set[str]]) -> Set[str]:
        """All nodes reachable from ``node_name`` via the dependents adjacency ``dag``."""
        seen: Set[str] = set()
        stack = list(dag.get(node_name, set()))
        while stack:
            nxt = stack.pop()
            if nxt in seen:
                continue
            seen.add(nxt)
            stack.extend(dag.get(nxt, set()))
        return seen

    def _handle_node_success(
        self,
        node_name: str,
        node_info: Dict[str, Any],
        execution_state: ThreadSafeExecutionState,
        dag: Dict[str, Set[str]],
    ) -> None:
        """Handle successful node completion."""
        result_dict = {
            "status": "success",
            "start_time": node_info["start_time"],
            "end_time": time.time(),
            "config": node_info["config"],
        }
        execution_state.mark_completed(node_name, result_dict)

        try:
            from ducta.console.ux.rich_logger import log_node_complete

            duration = time.time() - node_info["start_time"]
            node_display = node_name.split(".")[-1] if "." in node_name else node_name
            log_node_complete(node_display, duration)
        except Exception:
            logger.info("Node '{}' completed successfully", node_name)

        newly_ready = self._find_newly_ready_nodes(node_name, dag, execution_state)
        execution_state.add_to_ready_queue(newly_ready)

    def _handle_node_timeout(
        self,
        node_name: str,
        node_info: Dict[str, Any],
        execution_state: ThreadSafeExecutionState,
        timeout_error: TimeoutError,
    ) -> None:
        """Handle node timeout failure."""
        error_info = {
            "status": "failed",
            "error": "Node execution timeout exceeded",
            "error_type": "TimeoutError",
            "start_time": node_info["start_time"],
            "end_time": time.time(),
            "config": node_info["config"],
        }
        execution_state.mark_failed(node_name, error_info)
        logger.error("Node '{}' exceeded timeout: {}", node_name, timeout_error)

    def _handle_node_failure(
        self,
        node_name: str,
        node_info: Dict[str, Any],
        execution_state: ThreadSafeExecutionState,
        error: Exception,
    ) -> None:
        """Handle node execution failure with elegant error reporting."""
        error_info = {
            "status": "failed",
            "error": str(error),
            "error_type": type(error).__name__,
            "start_time": node_info["start_time"],
            "end_time": time.time(),
            "config": node_info.get("config", {}),
        }
        execution_state.mark_failed(node_name, error_info)

        try:
            from ducta.console.ux.error_analyzer import format_error_for_developer
            from ducta.console.ux.rich_logger import RichLoggerManager

            console = RichLoggerManager.get_console()
            format_error_for_developer(error, node_name, console)
        except Exception:
            logger.error("Node '{}' failed: {}", node_name, error)

    def _find_newly_ready_nodes(
        self,
        completed_node: str,
        dag: Dict[str, Set[str]],
        execution_state: ThreadSafeExecutionState,
    ) -> List[str]:
        """Find nodes that became ready after completing a node."""
        newly_ready = []
        running_nodes = execution_state.get_running_node_names()
        queued_nodes = execution_state.get_queued_node_names()

        for dependent in dag.get(completed_node, set()):
            if (
                execution_state.is_completed(dependent)
                or dependent in running_nodes
                or dependent in queued_nodes
            ):
                continue

            # node_deps holds the merged (explicit ∪ inferred) deps for every node
            # in the pipeline — authoritative, so never fall back to explicit-only.
            dependencies = execution_state.node_deps.get(dependent, [])

            if all(execution_state.is_completed(dep) for dep in dependencies):
                newly_ready.append(dependent)

        return newly_ready

    def _handle_unfinished_futures(self, execution_state: ThreadSafeExecutionState) -> None:
        """Handle any unfinished futures at the end of execution."""
        snapshot = execution_state.get_running_items_snapshot()
        if not snapshot:
            return

        logger.warning("Handling {} unfinished futures", len(snapshot))

        future_to_info = {future: info for future, info in snapshot}
        futures = list(future_to_info)

        try:
            for future in thread_as_completed(futures, timeout=5):
                node_info = future_to_info[future]
                node_name = node_info["node_name"]
                try:
                    future.result()
                    logger.info("Late completion of node '{}'", node_name)
                except Exception as e:
                    logger.error("Late failure of node '{}': {}", node_name, e)
                execution_state.remove_running_future(future)
        except TimeoutError:
            logger.warning("Grace period (5s) expired; cancelling remaining futures")

        for future in futures:
            if not future.done():
                node_info = future_to_info.get(future)
                if node_info:
                    logger.warning(
                        "Cancelling unfinished future for node '{}'",
                        node_info["node_name"],
                    )
                try:
                    future.cancel()
                except Exception:
                    pass

    def _cleanup_futures(self, running_snapshot: List) -> None:
        """Ensure all futures are properly cleaned up from a snapshot."""
        if not running_snapshot:
            return

        logger.debug("Cleaning up {} remaining futures", len(running_snapshot))

        for future, node_info in running_snapshot:
            node_name = node_info["node_name"]
            try:
                if not future.done():
                    future.cancel()
                else:
                    try:
                        future.result(timeout=0.1)
                    except Exception:
                        pass
            except Exception as e:
                logger.debug("Error during cleanup of future for '{}': {}", node_name, e)

    def _log_ml_pipeline_summary(
        self, execution_results: Dict[str, Any], ml_info: Dict[str, Any]
    ) -> None:
        """Log comprehensive ML pipeline execution summary."""
        successful_nodes = [
            name for name, result in execution_results.items() if result.get("status") == "success"
        ]
        failed_nodes = [
            name for name, result in execution_results.items() if result.get("status") == "failed"
        ]
        total_time = sum(
            r.get("end_time", 0) - r.get("start_time", 0) for r in execution_results.values()
        )

        logger.info(
            "ML pipeline summary — success: {}, failed: {}, project: {}, time: {:.2f}s",
            len(successful_nodes),
            len(failed_nodes),
            ml_info.get("project_name", "Unknown"),
            total_time,
        )
        if successful_nodes:
            logger.info("Successful nodes: {}", ", ".join(successful_nodes))
        if failed_nodes:
            logger.error("Failed nodes: {}", ", ".join(failed_nodes))

        try:
            from ducta.console.ux.rich_logger import RichLoggerManager, print_process_separator

            console = RichLoggerManager.get_console()
            console.print()
            print_process_separator(
                "summary",
                "ML PIPELINE SUMMARY",
                f"{len(successful_nodes)}/{len(successful_nodes) + len(failed_nodes)} nodes",
                console,
            )
            console.print()
        except Exception:
            pass


class NodeExecutor:
    """Thin orchestrator: initializes the 6 helper components and provides the public API."""

    DEFAULT_NODE_TIMEOUT = 1800
    # Mirrors BaseExecutor.MAX_TIMEOUT_SECONDS in executor.py (duplicated, not
    # imported, to avoid a circular import — executor.py imports NodeExecutor
    # from this module). A misconfigured node_timeout_seconds (e.g. a typo
    # adding extra zeros) was previously never clamped here, unlike the
    # whole-pipeline execution_timeout_seconds.
    MAX_NODE_TIMEOUT_SECONDS = 86400

    def __init__(
        self,
        context,
        input_loader,
        output_manager,
        max_workers: int = 4,
        timeout: Optional[int] = None,
        mlops_context: Optional[Any] = None,
        quality_output_manager: Optional[QualityOutputManager] = None,
    ):
        self.context = context
        self.input_loader = input_loader
        self.output_manager = output_manager
        self.quality_output_manager = quality_output_manager
        self.max_workers = max_workers
        self.mlops_context = mlops_context
        self.is_ml_layer = getattr(context, "is_ml_layer", False)
        # Set by the owning BaseExecutor (BatchExecutor/StreamingExecutor/
        # HybridExecutor) at the start of each .execute() call, mirroring
        # self._mlops_pipeline_name — lets sanity/DQ storage scope reports
        # per pipeline without threading pipeline_name through every
        # intermediate method signature down to execute_single_node.
        self.pipeline_name: Optional[str] = None
        # Populated at the end of execute_nodes_parallel from that call's
        # (otherwise-local, discarded) ThreadSafeExecutionState — the only
        # place a caller (e.g. the CLI) can learn that a `skip_downstream`
        # gate block happened, since that behavior deliberately lets the run
        # complete without raising.
        self.gate_blocked: Dict[str, Any] = {}
        gs = getattr(context, "global_settings", {}) or {}
        configured_timeout = timeout or gs.get("node_timeout_seconds", self.DEFAULT_NODE_TIMEOUT)
        self.node_timeout = min(configured_timeout, self.MAX_NODE_TIMEOUT_SECONDS)
        if self.node_timeout != configured_timeout:
            logger.warning(
                "Configured node_timeout_seconds {}s exceeds maximum, using {}s instead",
                configured_timeout,
                self.node_timeout,
            )
        logger.debug("NodeExecutor initialized with timeout: {}s", self.node_timeout)

        self._function_loader = FunctionLoader(context, is_ml_layer=self.is_ml_layer)
        self._quality_executor = QualityCheckExecutor(context, quality_output_manager)
        self._output_writer = OutputWriter(output_manager, context, is_ml_layer=self.is_ml_layer)
        self._ml_builder = MLContextBuilder(context, mlops_context, self.is_ml_layer)
        # Guards appends to context._run_node_details (nodes run on parallel threads).
        self._trace_lock = threading.Lock()
        self._ingestion_executor = IngestionExecutor(
            context=context,
            output_writer=self._output_writer,
            quality_executor=self._quality_executor,
        )
        self._coordinator = ParallelCoordinator(
            context=context,
            max_workers=max_workers,
            node_timeout=self.node_timeout,
            is_ml_layer=self.is_ml_layer,
            execute_callback=self.execute_single_node,
            ml_builder=self._ml_builder,
        )

    def set_mlops_context(self, mlops_context: Optional[Any]) -> None:
        """Wire the real MLOps context into node functions' ``ml_context['mlops_context']``.

        ``NodeExecutor`` is constructed at ``BaseExecutor.__init__`` time with
        ``mlops_context=None`` (MLOps isn't resolved until later, per pipeline
        run, via ``_start_mlops_integration``). Without this, the value baked
        into ``self._ml_builder`` at construction stays ``None`` for the
        executor's entire lifetime, and every ML node's ``ml_context['mlops_context']``
        is silently ``None`` even when MLOps is fully initialized. Call this
        once the real context is available, before executing nodes.
        """
        self.mlops_context = mlops_context
        self._ml_builder.mlops_context = mlops_context

    def execute_single_node(
        self,
        node_name: str,
        start_date: str,
        end_date: str,
        ml_info: Dict[str, Any],
    ) -> None:
        """Execute a single node with enhanced ML support and error handling."""
        start_time = time.perf_counter()
        node_status = "success"
        node_error: Optional[str] = None
        resource_manager = get_resource_manager()

        # Tags log lines with the node id so the API can stream them per node.
        # Imported from core, not from ducta.api.execution: pulling that in here
        # dragged the entire FastAPI app into every CLI pipeline run.
        node_id_var.set(node_name)

        logger.info("[node_status] node_id={} status=running", node_name)

        self._set_scheduler_pool(node_name)

        with resource_manager.resource_context(f"node_{node_name}"):
            try:
                node_config = self._get_node_config(node_name)
                node_type = node_config.get("type", "batch")
                if node_type == "ingestion":
                    self._ingestion_executor.execute(
                        node_name,
                        node_config,
                        start_date,
                        end_date,
                        ml_info,
                        pipeline_name=self.pipeline_name,
                    )
                    logger.info("[node_status] node_id={} status=success", node_name)
                    return

                function = self._function_loader.load(node_config)
                input_dfs = self.input_loader.load_inputs(node_config)
                input_param_names = self.input_loader.get_input_param_names(node_config)

                sanity_report = self._quality_executor.run_sanity_checks(
                    input_dfs,
                    node_config,
                    node_name,
                    pipeline_type=ml_info.get("pipeline_type"),
                    pipeline_name=self.pipeline_name,
                )

                self._quality_executor.persist_report(
                    sanity_report,
                    "sanity",
                    "sanity_checks",
                    node_name,
                    node_config,
                    ml_info,
                    pipeline_name=self.pipeline_name,
                )

                for idx, df in enumerate(input_dfs):
                    if df is not None:
                        resource_type = resource_manager.detect_resource_type(df)
                        resource_manager.register(
                            resource=df,
                            resource_type=resource_type,
                            context_id=f"node_{node_name}",
                            metadata={"index": idx, "stage": "input"},
                        )

                command = self._ml_builder.create_command(
                    function,
                    input_dfs,
                    start_date,
                    end_date,
                    node_name,
                    ml_info,
                    node_config,
                    input_param_names,
                )

                # Retries are opt-in per node via the documented `retry` field
                # (NodeSchema, 0-10). Deterministic user-function errors are not
                # retried unless the node asks for it.
                node_retries = int(node_config.get("retry", 0) or 0)
                if node_retries > 0:
                    from ducta.core.resilience import RetryPolicy

                    result_df = RetryPolicy(
                        max_retries=node_retries, delay=1, backoff_factor=2.0
                    ).execute(command.execute)
                else:
                    result_df = command.execute()

                dq_report = None
                if result_df is not None:
                    dq_report = self._quality_executor.run_dq_checks(
                        result_df, node_config, node_name, pipeline_name=self.pipeline_name
                    )

                self._quality_executor.persist_report(
                    dq_report,
                    "dq",
                    "data_quality",
                    node_name,
                    node_config,
                    ml_info,
                    pipeline_name=self.pipeline_name,
                )

                if result_df is not None:
                    resource_type = resource_manager.detect_resource_type(result_df)
                    resource_manager.register(
                        resource=result_df,
                        resource_type=resource_type,
                        context_id=f"node_{node_name}",
                        metadata={"stage": "output"},
                    )

                self._output_writer.save(
                    result_df,
                    node_config,
                    node_name,
                    start_date,
                    end_date,
                    ml_info,
                )

                logger.info("[node_status] node_id={} status=success", node_name)

            except Exception as e:
                # F2.3: Emit structured node status. A blocking quality gate is not
                # an execution failure — tag it so the certificate/trace reflect it.
                from ducta.check.core import QualityGateBlocked

                node_status = "gate_blocked" if isinstance(e, QualityGateBlocked) else "failed"
                node_error = str(e)
                logger.info("[node_status] node_id={} status={}", node_name, node_status)
                try:
                    from ducta.console.ux.error_analyzer import format_error_for_developer
                    from ducta.console.ux.rich_logger import RichLoggerManager

                    console = RichLoggerManager.get_console()
                    format_error_for_developer(e, node_name, console)
                except Exception:
                    logger.error("Failed to execute node '{}': {}", node_name, e)
                raise
            finally:
                duration = time.perf_counter() - start_time
                logger.debug("Node '{}' executed in {:.2f}s", node_name, duration)
                self._record_node_trace(node_name, node_status, duration, node_error)

    def _record_node_trace(
        self, node_name: str, status: str, duration: float, error: Optional[str]
    ) -> None:
        """Append this node's outcome to ``context._run_node_details`` for the certificate.

        Thread-safe (nodes run in parallel). Best-effort: never raises. The trace
        list is reset per run by the executor facade.
        """
        try:
            node_config = self.context.nodes_config.get(node_name, {}) or {}
            raw_out = node_config.get("output", [])
            outputs = list(raw_out.values()) if isinstance(raw_out, dict) else list(raw_out or [])
            record = {
                "name": node_name,
                "type": node_config.get("type", "batch"),
                "status": status,
                "duration_seconds": round(duration, 3),
                "outputs": outputs,
                "error": error,
            }
            with self._trace_lock:
                trace = getattr(self.context, "_run_node_details", None)
                if isinstance(trace, list):
                    trace.append(record)
        except Exception as e:  # noqa: BLE001 — bookkeeping must never break a node
            logger.debug("Could not record node trace for '{}': {}", node_name, e)

    def execute_nodes_parallel(
        self,
        execution_order: List[str],
        node_configs: Dict[str, Dict[str, Any]],
        dag: Dict[str, Set[str]],
        start_date: str,
        end_date: str,
        ml_info: Dict[str, Any],
    ) -> None:
        """
        Execute nodes in parallel while respecting dependencies with ML enhancements.
        Orchestrates parallel execution by delegating to ParallelCoordinator.
        """
        execution_state = self._initialize_execution_state(execution_order, node_configs)

        # Built and torn down manually (not `with ThreadPoolExecutor(...) as
        # executor:`) so a timed-out/hung node cannot block this call from
        # returning. `future.cancel()` on an already-started future is a
        # no-op — Python cannot forcibly stop a running thread — so exiting a
        # `with ThreadPoolExecutor` block would call `shutdown(wait=True)` and
        # block here until that hung thread finishes on its own, possibly
        # never. `shutdown(wait=False)` lets this call return promptly; the
        # thread (if truly stuck) keeps running in the background until it
        # exits by itself, which `_fail_timed_out_nodes` already warns about
        # per-node.
        executor = ThreadPoolExecutor(max_workers=self.max_workers)
        try:
            original_exc: Optional[BaseException] = None
            try:
                self._coordinator.coordinate(
                    executor=executor,
                    execution_state=execution_state,
                    dag=dag,
                    node_configs=node_configs,
                    start_date=start_date,
                    end_date=end_date,
                    ml_info=ml_info,
                )
            except Exception as e:
                original_exc = e
                logger.error("Pipeline execution failed: {}", e)
                self._coordinator.cancel_all(execution_state.get_running_items_snapshot())
                raise
            finally:
                # If coordinate() already raised a genuine exception, letting
                # cleanup()'s own exception (e.g. its generic "failed due to
                # node failures" RuntimeError) propagate from this `finally`
                # would silently replace it — Python's finally-block-raises
                # semantics discard whatever was already propagating. Log and
                # swallow it instead so the real root-cause exception/traceback
                # from coordinate() survives.
                try:
                    self._coordinator.cleanup(
                        execution_state=execution_state,
                        ml_info=ml_info,
                    )
                except Exception as cleanup_exc:
                    if original_exc is not None:
                        logger.error(
                            "cleanup() raised while an exception was already "
                            "propagating ({}); keeping the original exception: {}",
                            original_exc,
                            cleanup_exc,
                        )
                    else:
                        raise
        finally:
            executor.shutdown(wait=False)

        self.gate_blocked = dict(execution_state.gate_blocked)

    def _initialize_execution_state(
        self,
        execution_order: List[str],
        node_configs: Dict[str, Dict[str, Any]],
    ) -> ThreadSafeExecutionState:
        """Initialize thread-safe execution state with queues and tracking structures."""
        state = ThreadSafeExecutionState(execution_order, node_configs)
        logger.debug("Initial ready nodes: {}", list(state.ready_queue))
        return state

    def _set_scheduler_pool(self, node_name: str) -> None:
        """Bind the current worker thread to a per-node FAIR scheduler pool.

        No-op when Spark is unavailable (pure-Python test environments) or the
        scheduler is not FAIR — ``setLocalProperty`` is harmless in either case.
        """
        spark = getattr(self.context, "spark", None)
        if spark is None:
            return
        try:
            spark.sparkContext.setLocalProperty("spark.scheduler.pool", f"node_{node_name}")
        except Exception as e:
            logger.debug("Could not set scheduler pool for node '{}': {}", node_name, e)

    def _get_node_config(self, node_name: str) -> Dict[str, Any]:
        """Get configuration for a specific node with enhanced error handling."""
        node = self.context.nodes_config.get(node_name)
        if not node:
            available_nodes = list(self.context.nodes_config.keys())
            available_str = ", ".join(available_nodes[:10])
            if len(available_nodes) > 10:
                available_str += f", ... (total: {len(available_nodes)} nodes)"
            raise ValueError(
                f"Node '{node_name}' not found in configuration. Available nodes: {available_str}"
            )
        return node

    # -- Delegation shims (preserve call sites that access private methods directly) --

    def _run_sanity_checks_on_inputs(
        self,
        dfs: List[Any],
        node_config: Dict[str, Any],
        node_name: str,
        pipeline_type: Optional[str] = None,
    ) -> Optional[QualityReport]:
        return self._quality_executor.run_sanity_checks(
            dfs, node_config, node_name, pipeline_type, pipeline_name=self.pipeline_name
        )

    def _load_node_function(self, node: Dict[str, Any]) -> Callable:
        return self._function_loader.load(node)

    def _create_enhanced_command(
        self,
        function: Callable,
        input_dfs: List[Any],
        start_date: str,
        end_date: str,
        node_name: str,
        ml_info: Dict[str, Any],
        node_config: Dict[str, Any],
        input_names: Optional[List[str]] = None,
    ) -> Command:
        return self._ml_builder.create_command(
            function, input_dfs, start_date, end_date, node_name, ml_info, node_config, input_names
        )

    def _create_quality_output_config(
        self, config_dict: Dict[str, Any]
    ) -> Optional[QualityOutputConfig]:
        return self._quality_executor._create_quality_output_config(config_dict)
