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

from ducta.console.config import AppConfigManager, ConfigManager
from ducta.console.core import ConfigurationError, ExitCode, ValidationError
from ducta.console.ux.error_analyzer import format_error_for_developer

try:
    from ducta.console.ux.rich_logger import RichLoggerManager, print_process_separator

    _RICH_AVAILABLE = True
except ImportError:
    _RICH_AVAILABLE = False
from ducta.core import PipelineExecutor
from ducta.core.results import PipelineRunResult
from ducta.setting.context_loader import ContextLoader
from ducta.setting.contexts import Context


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
        self.context_loader = ContextLoader()

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
            context = self._resolve_context(env)
            if context is None:
                raise ConfigurationError(
                    "No configuration found. Provide an 'environment.*' root with "
                    "an env_config block, a single-file bundle, a config/ directory "
                    "with the 5 standard files, or a global.* + pipeline.* quickstart."
                )
            return context
        except ConfigurationError:
            raise
        except Exception as e:
            try:
                format_error_for_developer(e, f"INIT:{env}", RichLoggerManager.get_console())
            except Exception:
                pass
            raise ConfigurationError(f"Context initialization failed: {e}")

    def _resolve_context(self, env: str) -> Optional[Context]:
        """Resolve a Context from whichever configuration form is present."""
        from ducta.console.config import load_config_file
        from ducta.setting.config_forms import FlexibleConfigResolver

        # A canonical root was discovered.
        config_file_path: Optional[str] = None
        try:
            config_file_path = self.config_manager.get_config_file_path()
        except ConfigurationError:
            config_file_path = None

        if config_file_path is not None:
            data = load_config_file(config_file_path)
            if isinstance(data, dict) and "env_config" in data:
                app_config = AppConfigManager(config_file_path)
                return self.context_loader.load_from_paths(app_config.get_env_config(env), env)
            # Discovered file is not an env_config root (e.g. a bundle or a bare
            # global settings file): resolve it as a flexible form.
            flexible = FlexibleConfigResolver.resolve_file(Path(config_file_path), data, env)
            if flexible is not None:
                return flexible

        # No usable root discovered: resolve flexibly from the base directory.
        return FlexibleConfigResolver.resolve_dir(self.config_manager.base_path, env)


def load_context(
    config_path: Optional[Union[str, Path]],
    validate: bool = True,
    env: Optional[str] = None,
) -> Context:
    """Load a Context from *config_path*.

    Validates the resolved config against its pydantic schema by default —
    this used to always pass ``validate=False`` unconditionally, silently
    skipping schema validation for every caller regardless of whether they
    actually wanted that. Pass ``validate=False`` explicitly for a caller
    that has its own reason to defer/skip it (e.g. a preflight command that
    wants to collect every validation error into one report instead of
    aborting on the first schema violation).

    ``env`` selects the ``environments:`` override block. It used not to be
    accepted at all, so the streaming fallback that reaches this function
    dropped whatever ``--env`` the user asked for.
    """
    if config_path is None:
        raise ValidationError("Configuration path must be provided")

    config_path_str = str(config_path)
    from ducta.setting.loaders import ConfigLoaderFactory

    config_data = ConfigLoaderFactory().load_config(config_path_str)

    if all(
        k in config_data
        for k in (
            "global_settings",
            "pipelines_config",
            "nodes_config",
            "input_config",
            "output_config",
        )
    ):
        context = Context(
            global_settings=config_data["global_settings"],
            pipelines_config=config_data["pipelines_config"],
            nodes_config=config_data["nodes_config"],
            input_config=config_data["input_config"],
            output_config=config_data["output_config"],
            validate=validate,
            env=env,
        )
    else:
        base = Path(config_path_str).parent
        ext = Path(config_path_str).suffix
        context = Context(
            global_settings=str(base / f"global_settings{ext}"),
            pipelines_config=str(base / f"pipelines{ext}"),
            nodes_config=str(base / f"nodes{ext}"),
            input_config=str(base / f"input{ext}"),
            output_config=str(base / f"output{ext}"),
            validate=validate,
            env=env,
        )

    context._config_file_path = str(Path(config_path_str).resolve())
    return context


def _config_or_empty(config: Optional[Union[str, Path]]) -> str:
    return str(config) if config is not None else ""


def _find_environment_file(config: Optional[Union[str, Path]]) -> Optional[Path]:
    """Walk from the --config file's directory up to CWD looking for environment.toml/yml."""
    names = ["environment.toml", "environment.yml", "environment.yaml"]
    candidates: list[Path] = []
    if config:
        config_path = Path(config).resolve()
        # Check config's own dir, then each parent up to the filesystem root
        current = config_path.parent
        cwd = Path.cwd().resolve()
        while True:
            candidates.append(current)
            if current == cwd or current == current.parent:
                break
            current = current.parent
    candidates.append(Path.cwd().resolve())
    for directory in candidates:
        for name in names:
            candidate = directory / name
            if candidate.is_file():
                return candidate
    return None


def _load_streaming_context(config: Optional[Union[str, Path]], env: str = "base") -> Context:
    """Load context using environment overlay when environment.toml exists, otherwise direct load."""
    env_file = _find_environment_file(config)
    if env_file is not None:
        try:
            from ducta.console.config import AppConfigManager

            app_config = AppConfigManager(str(env_file))
            context_loader = ContextLoader()
            return context_loader.load_from_paths(app_config.get_env_config(env), env)
        except Exception as e:
            logger.warning(
                "Environment overlay failed ({}); falling back to direct config load: {}", env, e
            )
    return load_context(_config_or_empty(config), env=env)


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
