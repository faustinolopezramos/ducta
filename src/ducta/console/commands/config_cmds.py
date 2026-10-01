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
from typing import Optional

from loguru import logger

from ducta.console import execution
from ducta.console.config import ConfigManager
from ducta.console.core import CLIConfig, ConfigurationError, ExitCode


def handle_config(parsed_args, config: Optional[CLIConfig] = None) -> int:
    cmd = getattr(parsed_args, "config_command", None)

    # Neither needs a loadable project: migrate reads format 1 itself, and the
    # schema is static.
    if cmd == "migrate":
        return _handle_migrate(parsed_args)
    if cmd == "schema":
        return _handle_schema(parsed_args)

    config_manager = _init_config_manager(parsed_args, config)

    if cmd == "list-pipelines":
        return _handle_list_pipelines(parsed_args, config_manager)
    elif cmd == "pipeline-info":
        return _handle_pipeline_info(parsed_args, config_manager)
    elif cmd == "validate":
        return _handle_validate(parsed_args, config_manager)
    else:
        logger.error("Unknown config command: {}", cmd)
        return ExitCode.GENERAL_ERROR.value


def _init_config_manager(parsed_args, config: Optional[CLIConfig] = None) -> ConfigManager:
    config_manager = ConfigManager(
        base_path=getattr(parsed_args, "base_path", config.base_path if config else None)
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


def _log_preflight_report(name: str, report, prefix: str = "") -> None:
    """Log one preflight report's marker/count line and its error/warning
    bullets. Shared by the layered and non-layered ``config validate``
    paths; *prefix* carries the layered variant's ``"(layer) "`` tag."""
    marker = "✓" if report.ok and not report.warnings else ("✗" if report.errors else "⚠")
    logger.info(
        "{} {}{}: {} error(s), {} warning(s)",
        marker,
        prefix,
        name,
        len(report.errors),
        len(report.warnings),
    )
    for err in report.errors:
        logger.error("    ERROR  {}", err)
    for warn in report.warnings:
        logger.warning("    WARN   {}", warn)


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
            _log_preflight_report(name, report)

        if total_errors:
            logger.error("Preflight found {} error(s). Fix them before running.", total_errors)
            return ExitCode.VALIDATION_ERROR.value
        logger.info("Preflight passed — configuration is valid.")
        return ExitCode.SUCCESS.value
    except ConfigurationError as e:
        # The project does not load: the same code `ducta start` exits with.
        logger.error("Invalid configuration: {}", e)
        return ExitCode.CONFIGURATION_ERROR.value
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


def _handle_migrate(parsed_args) -> int:
    from ducta.setting.project_loader import find_project_root
    from ducta.setting.project_migrate import (
        MigrationError,
        migrate,
        replace_in_place,
        write_files,
    )

    root = Path(
        getattr(parsed_args, "path", None) or getattr(parsed_args, "base_path", None) or "."
    )
    root = root.resolve()
    if getattr(parsed_args, "check", False):
        if find_project_root(root) is not None:
            logger.success("{} uses configuration format 2", root)
            return ExitCode.SUCCESS.value
        logger.error("{} uses configuration format 1 — run `ducta config migrate`", root)
        return ExitCode.GENERAL_ERROR.value

    try:
        result = migrate(root)
    except MigrationError as e:
        logger.error("{}", e)
        return ExitCode.VALIDATION_ERROR.value

    before = len(result.legacy_files)
    after = 2 + len(result.pipelines)
    overrides = sorted((result.project.get("environments") or {}).keys())
    logger.info(
        "Verified: format 2 compiles to the same configuration in every environment ({})",
        ", ".join(["base", *result.environments]),
    )
    logger.info(
        "{} format-1 file(s) → {} format-2 file(s); {} pipeline(s), {} dataset(s); "
        "environments with overrides: {}",
        before,
        after,
        len(result.pipelines),
        len(result.catalog),
        ", ".join(overrides) or "none (identical to base)",
    )
    for note in result.notes:
        logger.warning("  {}", note)

    out = getattr(parsed_args, "out", None)
    if getattr(parsed_args, "write", False):
        written, backup = replace_in_place(result, root)
        logger.success(
            "Wrote {} file(s) in {}. Format-1 files moved to {}",
            len(written),
            root,
            backup.relative_to(root),
        )
    elif out:
        written = write_files(result, Path(out))
        logger.success("Wrote {} file(s) to {}", len(written), Path(out).resolve())
    else:
        logger.info("Nothing written. Re-run with --write (in place) or --out DIR.")
    return ExitCode.SUCCESS.value


def _handle_schema(parsed_args) -> int:
    import json

    from ducta.setting.project_migrate import write_schemas
    from ducta.setting.project_schema import json_schema

    out = getattr(parsed_args, "out", None)
    if out:
        write_schemas(Path(out))
        logger.success("JSON Schemas written under {}", Path(out).resolve() / ".ducta/schema")
    else:
        print(json.dumps(json_schema(), indent=2))
    return ExitCode.SUCCESS.value
