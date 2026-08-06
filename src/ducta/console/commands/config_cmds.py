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
from typing import Optional

from loguru import logger

from ducta.console import execution
from ducta.console.config import ConfigDiscovery, ConfigManager
from ducta.console.core import CLIConfig, ConfigCache, ExitCode


def handle_config(parsed_args, config: Optional[CLIConfig] = None) -> int:
    cmd = getattr(parsed_args, "config_command", None)

    if cmd == "list-configs":
        discovery = ConfigDiscovery(getattr(parsed_args, "base_path", None))
        discovery.list_all()
        return ExitCode.SUCCESS.value

    # Layered projects (ducta.yaml + per-layer configs) have no top-level
    # environment file, so normal config discovery fails. Route validate
    # through the layer detector instead — same routing `ducta start` uses.
    if cmd == "validate":
        layered_rc = _try_validate_layered(parsed_args)
        if layered_rc is not None:
            return layered_rc

    config_manager = _init_config_manager(parsed_args, config)

    if cmd == "list-pipelines":
        return _handle_list_pipelines(parsed_args, config_manager)
    elif cmd == "pipeline-info":
        return _handle_pipeline_info(parsed_args, config_manager)
    elif cmd == "validate":
        return _handle_validate(parsed_args, config_manager)
    elif cmd == "clear-cache":
        ConfigCache.invalidate_all()
        logger.info("Configuration cache cleared")
        return ExitCode.SUCCESS.value
    else:
        logger.error("Unknown config command: {}", cmd)
        return ExitCode.GENERAL_ERROR.value


def _init_config_manager(parsed_args, config: Optional[CLIConfig] = None) -> ConfigManager:
    layer_context = getattr(config, "layer_context", None) if config else None

    if layer_context:
        config_manager = ConfigManager.from_layer_config(layer_context)
        logger.info(f"Using layered project configuration: layer={layer_context.get('layer')}")
    else:
        config_manager = ConfigManager(
            base_path=getattr(parsed_args, "base_path", config.base_path if config else None),
            layer_name=getattr(parsed_args, "layer_name", config.layer_name if config else None),
            use_case=getattr(
                parsed_args, "use_case_name", config.use_case_name if config else None
            ),
            config_type=getattr(parsed_args, "config_type", config.config_type if config else None),
            interactive=getattr(parsed_args, "interactive", False)
            or (config.interactive if config else False),
            # Mirror `ducta start`: tolerate the absence of a canonical
            # environment.* root so list-pipelines/validate/pipeline-info also
            # work against a bundle / directory-convention / quickstart project,
            # resolved later by ContextInitializer's flexible fallback.
            require_config=False,
        )

    config_manager.change_to_config_directory()
    return config_manager


def _handle_list_pipelines(parsed_args, config_manager: ConfigManager) -> int:
    try:
        env = getattr(parsed_args, "env", None) or "base"
        filter_pattern = getattr(parsed_args, "filter_pattern", None)
        output_format = getattr(parsed_args, "output_format", "table")

        context_init = execution.ContextInitializer(config_manager)
        context = context_init.initialize(env)
        from ducta.core import PipelineExecutor

        exec_obj = PipelineExecutor(context, config_manager.get_config_directory())
        pipeline_names = exec_obj.list_pipelines()
        if filter_pattern:
            pipeline_names = [p for p in pipeline_names if filter_pattern.lower() in p.lower()]

        if not pipeline_names:
            msg = "No pipelines found"
            if filter_pattern:
                msg += f" matching '{filter_pattern}'"
            logger.warning(msg)
            return ExitCode.SUCCESS.value

        pipeline_infos = []
        for name in sorted(pipeline_names):
            info = exec_obj.get_pipeline_info(name)
            spec = context.pipelines.get(name, {}) if isinstance(context.pipelines, dict) else {}
            pipeline_infos.append(
                {
                    "name": name,
                    "type": spec.get("type", "batch") if isinstance(spec, dict) else "batch",
                    "nodes": info.get("nodes", []),
                    "description": info.get("description", ""),
                }
            )

        if output_format == "json":
            print(json.dumps(pipeline_infos, indent=2))
            return ExitCode.SUCCESS.value

        if output_format == "list":
            for p in pipeline_infos:
                logger.info("  - {}", p["name"])
            return ExitCode.SUCCESS.value

        from ducta.console.ux.formatters import create_table, get_console

        console = get_console()
        table = create_table(title=f"Pipelines (env: {env})", show_lines=False)
        if console and table:
            table.add_column("Name", style="cyan bold", no_wrap=True)
            table.add_column("Type", style="green")
            table.add_column("Nodes", style="dim", justify="right")
            table.add_column("Description", style="dim")
            for p in pipeline_infos:
                table.add_row(p["name"], p["type"], str(len(p["nodes"])), p["description"] or "")
            console.print(table)
        else:
            for p in pipeline_infos:
                logger.info("  - {} ({}, {} nodes)", p["name"], p["type"], len(p["nodes"]))

        return ExitCode.SUCCESS.value
    except Exception as e:
        logger.error("Failed to list pipelines: {}", e)
        return ExitCode.EXECUTION_ERROR.value


def _try_validate_layered(parsed_args) -> Optional[int]:
    """Preflight every layer of a layered project; None when not layered.

    Builds each layer's Context directly from its config paths (the same files
    ``ducta start --layer X`` would load) and reports per-layer results.
    """
    try:
        from ducta.setting.layered_config import LayerContextBuilder, LayeredProjectDetector

        detector = LayeredProjectDetector()
        if not detector.is_layered_project:
            return None

        env = getattr(parsed_args, "env", None) or "base"
        from ducta.core.preflight import validate_all_pipelines
        from ducta.setting.contexts import Context

        total_errors = 0
        for layer_name in detector.list_layers():
            context_args = LayerContextBuilder.build_context_args(detector, layer_name, env)
            if not context_args:
                logger.error("✗ layer '{}': config files incomplete", layer_name)
                total_errors += 1
                continue
            context = Context(
                global_settings=context_args["global_settings"],
                pipelines_config=context_args["pipelines_config"],
                nodes_config=context_args["nodes_config"],
                input_config=context_args["input_config"],
                output_config=context_args["output_config"],
                # Without this, `ducta config validate --env prod` resolved an
                # environment and then validated the base configuration, so any
                # error that only exists under an `environments:` override went
                # unreported.
                env=context_args["env"],
                validate=False,
            )
            # Layer node functions ("src.X") import relative to the layer root.
            # Put the layer root first on sys.path and purge any `src` package
            # cached from a previous layer (every layer names its package `src`,
            # and the workspace root may have one too).
            import importlib
            import os
            import sys as _sys
            from pathlib import Path as _Path

            layer_root = str(_Path(context_args["layer_path"]).resolve())
            _sys.path.insert(0, layer_root)
            for mod in [m for m in _sys.modules if m == "src" or m.startswith("src.")]:
                del _sys.modules[mod]
            importlib.invalidate_caches()

            prev_cwd = os.getcwd()
            os.chdir(layer_root)
            try:
                reports = validate_all_pipelines(context)
            finally:
                os.chdir(prev_cwd)
                try:
                    _sys.path.remove(layer_root)
                except ValueError:
                    pass
            for name in sorted(reports):
                report = reports[name]
                total_errors += len(report.errors)
                marker = (
                    "✓" if report.ok and not report.warnings else ("✗" if report.errors else "⚠")
                )
                # Parens, not brackets: Rich would swallow "[bronze]" as markup.
                logger.info(
                    "{} ({}) {}: {} error(s), {} warning(s)",
                    marker,
                    layer_name,
                    name,
                    len(report.errors),
                    len(report.warnings),
                )
                for err in report.errors:
                    logger.error("    ERROR  {}", err)
                for warn in report.warnings:
                    logger.warning("    WARN   {}", warn)

        if total_errors:
            logger.error("Preflight found {} error(s). Fix them before running.", total_errors)
            return ExitCode.VALIDATION_ERROR.value
        logger.info("Preflight passed — all layers valid.")
        return ExitCode.SUCCESS.value
    except Exception as e:  # noqa: BLE001 — fall back to normal discovery on any failure
        logger.debug("Layered validate not applicable: {}", e)
        return None


def _handle_validate(parsed_args, config_manager: ConfigManager) -> int:
    """Preflight-validate one pipeline (or all) and report configuration errors."""
    try:
        env = getattr(parsed_args, "env", None) or "base"
        target = getattr(parsed_args, "pipeline", None)

        context_init = execution.ContextInitializer(config_manager)
        context = context_init.initialize(env)

        from ducta.core.preflight import validate_all_pipelines, validate_pipeline

        if target:
            reports = {target: validate_pipeline(context, target)}
        else:
            reports = validate_all_pipelines(context)
            if not reports:
                logger.warning("No pipelines found to validate")
                return ExitCode.SUCCESS.value

        total_errors = 0
        for name in sorted(reports):
            report = reports[name]
            total_errors += len(report.errors)
            if report.ok and not report.warnings:
                logger.info("✓ {}: OK", name)
                continue
            marker = "✗" if report.errors else "⚠"
            logger.info(
                "{} {}: {} error(s), {} warning(s)",
                marker,
                name,
                len(report.errors),
                len(report.warnings),
            )
            for err in report.errors:
                logger.error("    ERROR  {}", err)
            for warn in report.warnings:
                logger.warning("    WARN   {}", warn)

        if total_errors:
            logger.error("Preflight found {} error(s). Fix them before running.", total_errors)
            return ExitCode.VALIDATION_ERROR.value
        logger.info("Preflight passed — configuration is valid.")
        return ExitCode.SUCCESS.value
    except Exception as e:
        logger.error("Failed to validate configuration: {}", e)
        return ExitCode.EXECUTION_ERROR.value


def _handle_pipeline_info(parsed_args, config_manager: ConfigManager) -> int:
    try:
        env = getattr(parsed_args, "env", None) or "base"
        logger.info("Fetching pipeline info for environment: '{}'", env)
        context_init = execution.ContextInitializer(config_manager)
        context = context_init.initialize(env)
        from ducta.core import PipelineExecutor

        exec_obj = PipelineExecutor(context, config_manager.get_config_directory())
        info = exec_obj.get_pipeline_info(parsed_args.pipeline)

        logger.info("Pipeline: {}", parsed_args.pipeline)
        logger.info("  Exists: {}", info["exists"])
        logger.info("  Description: {}", info["description"])
        if info["nodes"]:
            logger.info("  Nodes: {}", ", ".join(info["nodes"]))
        else:
            logger.info("  Nodes: None found")

        return ExitCode.SUCCESS.value
    except Exception as e:
        logger.error("Failed to get pipeline info: {}", e)
        return ExitCode.EXECUTION_ERROR.value
