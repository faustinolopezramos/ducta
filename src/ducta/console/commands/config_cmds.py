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
from typing import Any, Optional

from loguru import logger

from ducta.console import execution
from ducta.console.config import ConfigManager
from ducta.console.core import CLIConfig, ConfigurationError, ExitCode


def handle_config(parsed_args, config: Optional[CLIConfig] = None) -> int:
    cmd = getattr(parsed_args, "config_command", None)

    # The schema is static: it needs no loadable project.
    if cmd == "schema":
        return _handle_schema(parsed_args)

    config_manager = _init_config_manager(parsed_args, config)

    if cmd == "list-pipelines":
        return _handle_list_pipelines(parsed_args, config_manager)
    elif cmd == "pipeline-info":
        return _handle_pipeline_info(parsed_args, config_manager)
    elif cmd == "validate":
        return _handle_validate(parsed_args, config_manager)
    elif cmd in _INSPECT_COMMANDS:
        return _handle_inspect(cmd, parsed_args, config_manager)
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


def _handle_schema(parsed_args) -> int:
    import json

    from ducta.setting.project_decompile import write_schemas
    from ducta.setting.project_schema import json_schema

    out = getattr(parsed_args, "out", None)
    if out:
        write_schemas(Path(out))
        logger.success("JSON Schemas written under {}", Path(out).resolve() / ".ducta/schema")
    else:
        print(json.dumps(json_schema(), indent=2))
    return ExitCode.SUCCESS.value


_INSPECT_COMMANDS = ("show", "explain", "diff", "convert")


def _handle_inspect(cmd: str, parsed_args, config_manager: ConfigManager) -> int:
    """``show`` / ``explain`` / ``diff`` / ``convert``: what the project resolves to."""
    from ducta.setting.project_loader import ProjectConfigError

    assert config_manager.project_root is not None  # ConfigManager requires a project
    root = Path(config_manager.project_root)
    try:
        if cmd == "show":
            return _show(root, parsed_args)
        if cmd == "explain":
            return _explain(root, parsed_args)
        if cmd == "diff":
            return _diff(root, parsed_args)
        return _convert(root, parsed_args)
    except ProjectConfigError as e:
        for problem in e.problems:
            logger.error("{}", problem)
        return ExitCode.VALIDATION_ERROR.value


def _env(value: Optional[str]) -> Optional[str]:
    return None if value in (None, "base") else value


def _show(root: Path, parsed_args) -> int:
    from ducta.setting import project_inspect as inspect

    env = _env(getattr(parsed_args, "env", None))
    fmt = getattr(parsed_args, "output_format", "yaml")
    if getattr(parsed_args, "engine", False):
        from ducta.setting.project_loader import compile_project, validate_project

        data: Any = compile_project(validate_project(root, env))
    else:
        data = inspect.resolved_tree(root, env, getattr(parsed_args, "pipeline", None))
    print(inspect.dump(data, fmt), end="")
    return ExitCode.SUCCESS.value


def _explain(root: Path, parsed_args) -> int:
    import difflib

    from ducta.setting import project_inspect as inspect
    from ducta.setting.project_loader import apply_environment, read_project

    env = _env(getattr(parsed_args, "env", None))
    result = inspect.explain(root, parsed_args.path, env)
    dotted = ".".join(result.path)
    if not result.found:
        tree = apply_environment(read_project(root), env)
        parent: Any = tree
        for key in result.path[:-1]:
            parent = parent.get(key, {}) if isinstance(parent, dict) else {}
        siblings = list(parent) if isinstance(parent, dict) else []
        close = difflib.get_close_matches(result.path[-1], [str(k) for k in siblings], n=1)
        hint = f" — did you mean '{close[0]}'?" if close else ""
        logger.error("'{}' is not set{}", dotted, hint)
        return ExitCode.VALIDATION_ERROR.value
    print(f"{dotted} = {_short(result.value)}")
    for layer in result.layers:
        where = f"   {layer.at}" if layer.at else ""
        print(f"  {layer.name:<28} {_short(layer.value)}{where}")
    return ExitCode.SUCCESS.value


def _short(value: Any) -> str:
    import json

    text = json.dumps(value, default=str, ensure_ascii=False)
    return text if len(text) <= 100 else text[:97] + "..."


def _diff(root: Path, parsed_args) -> int:
    from ducta.setting import project_inspect as inspect

    a, b = _env(parsed_args.env_a), _env(parsed_args.env_b)
    changes = inspect.diff_trees(inspect.resolved_tree(root, a), inspect.resolved_tree(root, b))
    if not changes:
        print(f"{parsed_args.env_a} and {parsed_args.env_b} resolve to the same project")
        return ExitCode.SUCCESS.value
    for path, before, after in changes:
        left = "(not set)" if before is inspect.MISSING else _short(before)
        right = "(not set)" if after is inspect.MISSING else _short(after)
        print(f"{path}: {left} -> {right}")
    return ExitCode.SUCCESS.value


def _convert(root: Path, parsed_args) -> int:
    from ducta.setting import project_inspect as inspect

    written = inspect.convert_project(root, Path(parsed_args.out), parsed_args.to_format)
    logger.success(
        "{} file(s) written to {} as {}",
        len(written),
        Path(parsed_args.out).resolve(),
        parsed_args.to_format,
    )
    return ExitCode.SUCCESS.value
