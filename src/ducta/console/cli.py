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

import argparse
import os
import re
import sys
import traceback
from pathlib import Path
from typing import List, Optional

from loguru import logger

from ducta.console import execution, template
from ducta.console.commands import ExecutionCommands, QualityCommands, handle_config
from ducta.console.core import (
    ExitCode,
    LoggerManager,
    ValidationError,
    parse_iso_date,
    validate_date_range,
)
from ducta.console.validation import (
    validate_enum_field,
    validate_json_string,
    validate_positive_number,
    validate_required_field,
)
from ducta.core.errors import DuctaError as EngineError

HELP_BASE_PATH = "Base path for config discovery"
HELP_PIPELINE_NAME = "Pipeline name"
HELP_PIPELINE_NAME_TO_EXECUTE = "Pipeline name to execute"
HELP_TIMEOUT_SECONDS = "Timeout in seconds"
HELP_CONFIG_FILE = "Path to configuration file"


def validate_stream_run_arguments(args: argparse.Namespace) -> None:
    validate_enum_field(args.mode, ["sync", "async"], "mode")
    validate_json_string(args.hyperparams, "hyperparams")
    log_level = getattr(args, "log_level", None)
    if log_level:
        validate_enum_field(
            log_level, ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], "log-level"
        )


def validate_stream_status_arguments(args: argparse.Namespace) -> None:
    fmt = getattr(args, "format", None)
    if fmt:
        validate_enum_field(fmt, ["table", "json"], "format")


def validate_stream_stop_arguments(args: argparse.Namespace) -> None:
    timeout = getattr(args, "timeout", 60)
    validate_positive_number(timeout, max_val=3600, field_name="Timeout")


def validate_start_arguments(args: argparse.Namespace) -> None:
    validate_required_field(args.env, "env")
    validate_required_field(args.pipeline, "pipeline")
    if args.start_date or args.end_date:
        try:
            args.start_date = parse_iso_date(args.start_date) if args.start_date else None
            args.end_date = parse_iso_date(args.end_date) if args.end_date else None
            validate_date_range(args.start_date, args.end_date)
        except Exception as e:
            raise ValidationError(f"Date validation error: {e}")
    if args.validate_only and args.dry_run:
        logger.warning("Both --validate-only and --dry-run specified. Will validate only.")


validate_run_arguments = validate_start_arguments


def validate_template_arguments(args: argparse.Namespace) -> None:
    if getattr(args, "list_templates", False):
        return
    if not getattr(args, "template", None):
        raise ValidationError("--template is required for template generation")
    if not getattr(args, "project_name", None):
        raise ValidationError("--project-name is required for template generation")
    if not re.match(r"^[a-zA-Z0-9_-]+$", args.project_name):
        raise ValidationError(
            "Project name must contain only alphanumeric characters, underscores, or hyphens"
        )
    if getattr(args, "output_path", None):
        output = Path(args.output_path)
        if output.exists() and any(output.iterdir()):
            raise ValidationError(f"Output path '{output}' already exists and is not empty")


def validate_config_arguments(args: argparse.Namespace) -> None:
    if not getattr(args, "config_command", None):
        raise ValidationError(
            "A config subcommand is required (e.g., list-pipelines, validate, schema)"
        )


def validate_ui_arguments(args: argparse.Namespace) -> None:
    port = getattr(args, "port", 8000)
    validate_positive_number(port, max_val=65535, field_name="port")


validate_server_arguments = validate_ui_arguments


def validate_quality_arguments(args: argparse.Namespace) -> None:
    quality_cmd = getattr(args, "quality_command", None)
    if not quality_cmd:
        raise ValidationError(
            "A quality subcommand is required (e.g., list, run, report, trend, score, validate-config)"
        )
    if quality_cmd == "run":
        fmt = getattr(args, "format", "parquet")
        validate_enum_field(fmt, ["parquet", "csv", "json"], "format")
        output_fmt = getattr(args, "output_format", "rich")
        validate_enum_field(output_fmt, ["rich", "json"], "output-format")


def validate_experiment_arguments(args: argparse.Namespace) -> None:
    if not getattr(args, "experiment_command", None):
        raise ValidationError("An experiment subcommand is required (e.g., list)")


def validate_model_arguments(args: argparse.Namespace) -> None:
    if not getattr(args, "model_command", None):
        raise ValidationError("A model subcommand is required (e.g., promote, gc)")


def validate_profile_arguments(args: argparse.Namespace) -> None:
    validate_required_field(args.input, "input")
    validate_enum_field(args.format, ["parquet", "csv", "json"], "format")
    validate_enum_field(args.strictness, ["strict", "balanced", "lax"], "strictness")
    sample_rows = getattr(args, "sample_rows", None)
    if sample_rows is not None:
        validate_positive_number(sample_rows, field_name="sample-rows")


def validate_init_arguments(args: argparse.Namespace) -> None:
    if not getattr(args, "init_command", None):
        raise ValidationError("An init subcommand is required (e.g., project, ingestion)")


#: Subcommands that do not run inside an existing project, and so must not
#: create a `logs/` directory in whatever the current working directory is.
_PROJECTLESS_SUBCOMMANDS = frozenset({"template"})


def _is_projectless(parsed_args: argparse.Namespace) -> bool:
    """``template`` and ``init project`` run before the project they create exists."""
    if parsed_args.subcommand in _PROJECTLESS_SUBCOMMANDS:
        return True
    return (
        parsed_args.subcommand == "init" and getattr(parsed_args, "init_command", None) == "project"
    )


class UnifiedCLI:
    def run(self, args: Optional[List[str]] = None) -> int:
        parsed_args: Optional[argparse.Namespace] = None
        original_cwd = Path.cwd()
        try:
            parsed_args = self._parse_and_setup_logging(args)
            return self._dispatch_subcommand(parsed_args)
        except EngineError as e:
            logger.error("Ducta error: {}", e)
            if parsed_args is not None and getattr(parsed_args, "verbose", False):
                logger.debug(traceback.format_exc())
            return e.exit_code
        except KeyboardInterrupt:
            logger.warning("Execution interrupted by user")
            return ExitCode.GENERAL_ERROR.value
        except Exception as e:
            # `logger.error` is a no-op when no sink is attached, and there is a
            # real window where that is the case: LoggerManager.setup() calls
            # `logger.remove()` before adding its handlers, so anything raising
            # in between leaves the logger silent. The CLI then exited 1 having
            # printed nothing at all — the least debuggable failure possible.
            # Fall back to stderr whenever the logger cannot speak for itself.
            if not logger._core.handlers:  # type: ignore[attr-defined]
                print(f"Unexpected error: {e}", file=sys.stderr)
                traceback.print_exc(file=sys.stderr)
            else:
                logger.error("Unexpected error: {}", e)
                if parsed_args is not None and getattr(parsed_args, "verbose", False):
                    logger.debug(traceback.format_exc())
            return ExitCode.GENERAL_ERROR.value
        finally:
            try:
                os.chdir(original_cwd)
            except OSError:
                pass

    def _parse_and_setup_logging(self, args: Optional[List[str]]) -> argparse.Namespace:
        from ducta.console.parser import UnifiedArgumentParser

        parser = UnifiedArgumentParser.create()
        parsed_args = parser.parse_args(args)
        if parsed_args.version and not parsed_args.subcommand:
            return parsed_args
        LoggerManager.setup(
            level=getattr(parsed_args, "log_level", "INFO") or "INFO",
            log_file=getattr(parsed_args, "log_file", None),
            verbose=bool(getattr(parsed_args, "verbose", False)),
            quiet=bool(getattr(parsed_args, "quiet", False)),
            file_logging=not _is_projectless(parsed_args),
        )
        return parsed_args

    def _build_dispatch_table(self):
        """Map each subcommand to its (argument validator, handler)."""
        return {
            "start": (validate_start_arguments, lambda a: ExecutionCommands().handle_start(a)),
            "stream": (None, self._handle_stream_command),
            "template": (validate_template_arguments, self._handle_template_command),
            "config": (validate_config_arguments, lambda a: handle_config(a)),
            "ui": (validate_ui_arguments, self._handle_ui_command),
            "server": (validate_server_arguments, self._handle_server_command),
            "quality": (validate_quality_arguments, lambda a: QualityCommands.handle(a)),
            "experiment": (validate_experiment_arguments, self._handle_experiment_command),
            "model": (validate_model_arguments, self._handle_model_command),
            "init": (validate_init_arguments, self._handle_init_command),
            "certify": (None, self._handle_certify_command),
            "profile": (validate_profile_arguments, self._handle_profile_command),
        }

    def _dispatch_subcommand(self, parsed_args: argparse.Namespace) -> int:
        if parsed_args.version and not parsed_args.subcommand:
            self._print_signature()
            return ExitCode.SUCCESS.value
        subcommand = parsed_args.subcommand
        entry = self._build_dispatch_table().get(subcommand)
        if entry is None:
            logger.error("Unknown subcommand: {}", subcommand)
            return ExitCode.GENERAL_ERROR.value
        validator, handler = entry
        try:
            if validator is not None:
                validator(parsed_args)
            return handler(parsed_args)
        except ValidationError as e:
            from ducta.console.ux.error_analyzer import try_format_error

            if not try_format_error(e, "argument validation"):
                logger.error("Invalid arguments: {}", e)
            return ExitCode.VALIDATION_ERROR.value

    def _handle_experiment_command(self, parsed_args: argparse.Namespace) -> int:
        from ducta.console.mlops_commands import experiment_list

        cmd = getattr(parsed_args, "experiment_command", None)
        if cmd == "list":
            return experiment_list(
                parsed_args.storage_path,
                env=getattr(parsed_args, "env", None),
                limit=getattr(parsed_args, "limit", None),
                pipeline_name=getattr(parsed_args, "pipeline", None),
            )
        logger.error("Unknown experiment command: {}", cmd)
        return ExitCode.GENERAL_ERROR.value

    def _handle_model_command(self, parsed_args: argparse.Namespace) -> int:
        from ducta.console.mlops_commands import model_gc, model_promote

        cmd = getattr(parsed_args, "model_command", None)
        if cmd == "promote":
            return model_promote(
                parsed_args.name,
                parsed_args.version,
                parsed_args.stage,
                parsed_args.storage_path,
                force=getattr(parsed_args, "force", False),
                env=getattr(parsed_args, "env", None),
                pipeline_name=getattr(parsed_args, "pipeline", None),
            )
        elif cmd == "gc":
            return model_gc(
                parsed_args.storage_path,
                dry_run=parsed_args.dry_run,
                env=getattr(parsed_args, "env", None),
                pipeline_name=getattr(parsed_args, "pipeline", None),
            )
        logger.error("Unknown model command: {}", cmd)
        return ExitCode.GENERAL_ERROR.value

    def _handle_stream_command(self, parsed_args: argparse.Namespace) -> int:
        stream_cmd = parsed_args.stream_command
        try:
            if stream_cmd == "run":
                validate_stream_run_arguments(parsed_args)
                return execution.run_streaming_pipeline_cli(
                    config=getattr(parsed_args, "config", None),
                    pipeline=parsed_args.pipeline,
                    mode=getattr(parsed_args, "mode", "async"),
                    model_version=getattr(parsed_args, "model_version", None),
                    hyperparams=getattr(parsed_args, "hyperparams", None),
                    transforms_modules=getattr(parsed_args, "transforms_module", []) or [],
                    env=getattr(parsed_args, "env", "base") or "base",
                )
            elif stream_cmd == "status":
                validate_stream_status_arguments(parsed_args)
                return execution.get_streaming_pipeline_status_cli(
                    config=getattr(parsed_args, "config", None),
                    execution_id=getattr(parsed_args, "execution_id", None),
                    format_type=getattr(parsed_args, "format", "table"),
                    env=getattr(parsed_args, "env", "base") or "base",
                )
            elif stream_cmd == "stop":
                validate_stream_stop_arguments(parsed_args)
                return execution.stop_streaming_pipeline_cli(
                    config=getattr(parsed_args, "config", None),
                    execution_id=parsed_args.execution_id,
                    timeout=getattr(parsed_args, "timeout", 60),
                    env=getattr(parsed_args, "env", "base") or "base",
                )
            else:
                logger.error("Unknown stream command: {}", stream_cmd)
                return ExitCode.GENERAL_ERROR.value
        except ValidationError as e:
            logger.error(str(e))
            return ExitCode.VALIDATION_ERROR.value
        except Exception as e:
            logger.error("Unexpected error in streaming logic: {}", e)
            return ExitCode.GENERAL_ERROR.value

    def _handle_ui_command(self, parsed_args: argparse.Namespace) -> int:
        try:
            from ducta.console.ui import launch_ui

            return launch_ui(
                host=getattr(parsed_args, "host", "127.0.0.1"),
                port=getattr(parsed_args, "port", 8000),
                open_browser=not getattr(parsed_args, "no_browser", False),
                source=getattr(parsed_args, "source", None),
                db_path=getattr(parsed_args, "db_path", None),
                enable_terminal=getattr(parsed_args, "enable_terminal", False),
            )
        except ImportError as e:
            logger.error(
                "Failed to import UI dependencies. Are you sure Ducta-app is installed? {}", e
            )
            return ExitCode.GENERAL_ERROR.value
        except Exception as e:
            logger.error("Error launching UI: {}", e)
            return ExitCode.GENERAL_ERROR.value

    def _handle_server_command(self, parsed_args: argparse.Namespace) -> int:
        if getattr(parsed_args, "server_command", None) != "start":
            logger.error("Unknown server command: {}", getattr(parsed_args, "server_command", None))
            return ExitCode.GENERAL_ERROR.value
        return self._handle_ui_command(parsed_args)

    def _handle_template_command(self, parsed_args: argparse.Namespace) -> int:
        return template.handle_template_command(parsed_args)

    def _handle_init_command(self, parsed_args: argparse.Namespace) -> int:
        from ducta.console.commands.ingestion_cmds import InitCommands

        return InitCommands.handle(parsed_args)

    def _handle_profile_command(self, parsed_args: argparse.Namespace) -> int:
        from ducta.console.commands.profile_cmds import handle_profile

        return handle_profile(parsed_args)

    def _handle_certify_command(self, parsed_args: argparse.Namespace) -> int:
        from ducta.console.commands.certify_cmds import handle_certify

        return handle_certify(parsed_args)

    @staticmethod
    def _print_signature() -> None:
        from ducta import __version__

        _C = "\033[96m"
        _Y = "\033[93m"
        _G = "\033[92m"
        _R = "\033[0m"
        art = [
            f"{_C}╔════════════════════════════════╗{_R}".center(64),
            f"{_C}║  ══════════ Ducta ══════════   ║{_R}".center(64),
            f"{_C}╚════════════════════════════════╝{_R}".center(64),
            "",
            f"{_Y}Data Pipeline Framework{_R}".center(64),
            f"{_G}v{__version__}{_R}".center(64),
            "",
            "",
        ]
        print("\n".join(art))


def main() -> int:
    try:
        logger.remove(0)
    except ValueError:
        pass
    cli = UnifiedCLI()
    return cli.run()


if __name__ == "__main__":
    sys.exit(main())
