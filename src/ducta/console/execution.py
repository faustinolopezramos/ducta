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
from pathlib import Path
from typing import Optional, Union

from loguru import logger  # type: ignore

from ducta.console.config import ConfigManager
from ducta.console.core import ConfigurationError, ExitCode
from ducta.console.ux.error_analyzer import try_format_error

try:
    from ducta.console.ux.rich_logger import RichLoggerManager, print_process_separator

    _RICH_AVAILABLE = True
except ImportError:
    _RICH_AVAILABLE = False
from ducta.core import PipelineExecutor
from ducta.core.results import PipelineRunResult
from ducta.setting.contexts import Context
from ducta.setting.exceptions import ConfigurationError as SettingConfigurationError
from ducta.setting.project_loader import load_project_v2


def report_run_outcome(result: PipelineRunResult, *, pipeline: Optional[str] = None) -> int:
    """Log what a finished run actually did and return the matching exit code.

    Not every unsuccessful outcome raises. A ``skip_downstream`` quality gate and
    a run whose nodes had absent inputs both let ``run_pipeline`` return
    normally, so a caller that only wraps the call in ``try/except`` reports exit
    0 for a run that did not do its work.

    This lived inline in one of the five call sites; the other four discarded the
    result entirely. It is shared so that "what does this outcome mean" is
    answered once.
    """
    name = pipeline or result.pipeline

    if result.reused_pipelines:
        logger.info(
            "Reused {} materialized upstream pipeline(s): {}",
            len(result.reused_pipelines),
            ", ".join(result.reused_pipelines),
        )

    # Gate before skip, matching PipelineRunResult.resolve_status. A blocking
    # gate cascades skips onto its descendants, so both collections are
    # populated and only one of them names the *cause*.
    if result.gate_blocked:
        for node_name, info in result.gate_blocked.items():
            logger.warning(
                "Node '{}' was blocked by its quality gate: {}",
                node_name,
                info.get("error", "blocked") if isinstance(info, dict) else info,
            )
        for node_name, reason in result.skipped.items():
            logger.warning("Node '{}' was skipped as a consequence: {}", node_name, reason)
        return ExitCode.EXECUTION_ERROR.value

    if result.skipped:
        for node_name, reason in result.skipped.items():
            logger.warning("Node '{}' was skipped (missing dependencies): {}", node_name, reason)
        logger.error(
            "Pipeline '{}' did not complete: {} node(s) skipped for missing inputs",
            name,
            len(result.skipped),
        )
        # Used to be SUCCESS. A run that skipped its work is not a run that did
        # it, and exit 0 meant no script wrapping `ducta` could tell them apart.
        return ExitCode.DEPENDENCY_ERROR.value

    if _RICH_AVAILABLE:
        try:
            console = RichLoggerManager.get_console()
            console.print()
            print_process_separator("success", "EXECUTION COMPLETED", f"Pipeline: {name}", console)
            console.print()
        except Exception:  # noqa: BLE001 — decoration must never change the outcome
            pass

    logger.success("Ducta pipeline execution completed successfully")
    return ExitCode.SUCCESS.value


class ContextInitializer:
    def __init__(self, config_manager: ConfigManager):
        self.config_manager = config_manager

    def initialize(self, env: str) -> Context:
        try:
            if _RICH_AVAILABLE:
                console = RichLoggerManager.get_console()
                console.print()
                print_process_separator(
                    "configuration", "LOADING CONFIGURATION", f"Environment: {env}", console
                )
                console.print()
        except Exception:
            pass

        try:
            root = self.config_manager.project_root
            if root is None:
                raise ConfigurationError(
                    f"No Ducta project found in {Path(self.config_manager.base_path).resolve()}"
                )
            return load_project_v2(root, env)
        except ConfigurationError:
            raise
        except SettingConfigurationError as e:
            # Invalid format-2 files: the message already names file and line.
            raise ConfigurationError(str(e))
        except Exception as e:
            try_format_error(e, f"INIT:{env}")
            raise ConfigurationError(f"Context initialization failed: {e}")


def load_context(path: Optional[Union[str, Path]] = None, env: Optional[str] = None) -> Context:
    """The Context of the project containing ``path`` (a file or directory; default: cwd)."""
    start = Path(path) if path else Path.cwd()
    if start.is_file():
        start = start.parent
    return ContextInitializer(ConfigManager(str(start))).initialize(env or "base")


def _load_streaming_context(config: Optional[Union[str, Path]], env: str = "base") -> Context:
    """The project for a streaming command: --config names ducta.yaml (or any file in
    the project), or is omitted inside the project."""
    return load_context(config, env)


def run_streaming_pipeline_cli(
    config: Optional[Union[str, Path]],
    pipeline: str,
    mode: str = "async",
    model_version: Optional[str] = None,
    hyperparams: Optional[str] = None,
    transforms_modules: Optional[list] = None,
    env: str = "base",
) -> int:
    try:
        context = _load_streaming_context(config, env)
        executor = PipelineExecutor(context)
        if transforms_modules:
            executor.register_streaming_transforms(transforms_modules)
        parsed = json.loads(hyperparams) if hyperparams else None
        execution_id = executor.run_streaming_pipeline(
            pipeline_name=pipeline,
            mode=mode,
            model_version=model_version,
            hyperparams=parsed,
        )

        # `run_streaming_pipeline` returns once the startup work is queued, not
        # once anything is running. Reporting success on that id alone meant a
        # pipeline whose every node failed to start still exited 0, and no script
        # wrapping `ducta` could tell the two apart.
        startup = executor.wait_for_streaming_startup(execution_id, timeout=300.0)
        started, skipped, failed = (
            startup["started"],
            startup["skipped"],
            startup["failed"],
        )

        for node, reason in sorted(skipped.items()):
            logger.warning("Streaming node '{}' did not start: {}", node, reason)
        for node, reason in sorted(failed.items()):
            logger.error("Streaming node '{}' failed to start: {}", node, reason)

        if not started:
            logger.error(
                "Streaming pipeline '{}' started no queries (execution ID: {})",
                pipeline,
                execution_id,
            )
            return ExitCode.EXECUTION_ERROR.value

        if skipped or failed:
            logger.warning(
                "Streaming pipeline '{}' started {} of {} node(s)",
                pipeline,
                len(started),
                len(started) + len(skipped) + len(failed),
            )

        print(f"Streaming pipeline '{pipeline}' started with execution ID: {execution_id}")
        logger.info("Streaming pipeline '{}' started with execution ID: {}", pipeline, execution_id)
        return ExitCode.SUCCESS.value
    except json.JSONDecodeError as e:
        logger.error("Invalid hyperparams JSON: {}", e)
        return ExitCode.VALIDATION_ERROR.value
    except Exception as e:
        logger.error("Error running streaming pipeline: {}", e)
        return ExitCode.GENERAL_ERROR.value


def get_streaming_pipeline_status_cli(
    config: Optional[Union[str, Path]],
    execution_id: Optional[str] = None,
    format_type: str = "table",
    env: str = "base",
) -> int:
    try:
        context = _load_streaming_context(config, env)
        from ducta.console.ux.formatters import PipelineStatusFormatter

        executor = PipelineExecutor(context)

        if execution_id:
            status_info = executor.get_streaming_pipeline_status(execution_id)
            if not status_info:
                logger.error("Pipeline with execution_id '{}' not found", execution_id)
                return ExitCode.VALIDATION_ERROR.value
            if format_type == "json":
                print(json.dumps(status_info, indent=2, default=str))
            else:
                PipelineStatusFormatter.format_single_pipeline(status_info)
        else:
            status_list = executor.list_streaming_pipelines()
            if format_type == "json":
                print(json.dumps(status_list, indent=2, default=str))
            else:
                PipelineStatusFormatter.format_multiple_pipelines(status_list)

        return ExitCode.SUCCESS.value
    except Exception as e:
        logger.error("Error fetching status: {}", e)
        return ExitCode.GENERAL_ERROR.value


def stop_streaming_pipeline_cli(
    config: Optional[Union[str, Path]],
    execution_id: str,
    timeout: int = 60,
    env: str = "base",
) -> int:
    try:
        context = _load_streaming_context(config, env)
        executor = PipelineExecutor(context)
        graceful = not (timeout > 0 and timeout < 5)
        if executor.stop_streaming_pipeline(execution_id, graceful=graceful):
            logger.info(
                "Pipeline '{}' stopped successfully{}.",
                execution_id,
                f" (timeout: {timeout}s)" if timeout > 0 else "",
            )
            return ExitCode.SUCCESS.value
        logger.error("Failed to stop pipeline '{}' within {}s.", execution_id, timeout)
        return ExitCode.EXECUTION_ERROR.value
    except Exception as e:
        logger.error("Error stopping pipeline: {}", e)
        return ExitCode.GENERAL_ERROR.value
