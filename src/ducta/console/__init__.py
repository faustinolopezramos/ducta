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

from __future__ import annotations

# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
from ducta.console.cli import UnifiedCLI, main

# ---------------------------------------------------------------------------
# Commands subpackage
# ---------------------------------------------------------------------------
from ducta.console.commands import (
    ExecutionCommands,
    InitCommands,
    QualityCommands,
    handle_config,
)

# ---------------------------------------------------------------------------
# Config management
# ---------------------------------------------------------------------------
from ducta.console.config import ConfigManager

# ---------------------------------------------------------------------------
# CLI core types
# ---------------------------------------------------------------------------
from ducta.console.core import (
    CLIConfig,
    ConfigFormat,
    ConfigurationError,
    DuctaError,
    ExecutionError,
    ExitCode,
    LoggerManager,
    LogLevel,
    PathManager,
    SecurityError,
    SecurityValidator,
    ValidationError,
    parse_iso_date,
    validate_date_range,
)

# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------
from ducta.console.execution import (
    ContextInitializer,
    get_streaming_pipeline_status_cli,
    load_context,
    run_streaming_pipeline_cli,
    stop_streaming_pipeline_cli,
)

# ---------------------------------------------------------------------------
# MLOps commands
# ---------------------------------------------------------------------------
from ducta.console.mlops_commands import experiment_list, model_gc, model_promote

# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------
from ducta.console.parser import UnifiedArgumentParser

# ---------------------------------------------------------------------------
# Template
# ---------------------------------------------------------------------------
from ducta.console.template import (
    MedallionBasicTemplate,
    TemplateCommand,
    TemplateError,
    TemplateFactory,
    TemplateGenerator,
    TemplateType,
    handle_template_command,
)

# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
from ducta.console.ui import launch_ui

# ---------------------------------------------------------------------------
# UX subpackage
# ---------------------------------------------------------------------------
from ducta.console.ux import (
    RichLoggerManager,
    SparkErrorAnalyzer,
    format_error_for_developer,
    log_node_complete,
    log_node_start,
    print_execution_header,
    print_pandas_schema,
    print_process_separator,
    print_spark_schema,
)

# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

__all__ = [
    "CLIConfig",
    "ConfigFormat",
    "ConfigurationError",
    "DuctaError",
    "ExecutionError",
    "ExitCode",
    "LogLevel",
    "LoggerManager",
    "PathManager",
    "SecurityError",
    "SecurityValidator",
    "ValidationError",
    "parse_iso_date",
    "validate_date_range",
    "ConfigManager",
    "validate_conflicting_options",
    "validate_date_iso",
    "validate_enum_field",
    "validate_format",
    "validate_json_string",
    "validate_log_level",
    "validate_mode",
    "validate_positive_number",
    "validate_project_name",
    "validate_required_field",
    "validate_timeout",
    "UnifiedArgumentParser",
    "ContextInitializer",
    "get_streaming_pipeline_status_cli",
    "load_context",
    "run_streaming_pipeline_cli",
    "stop_streaming_pipeline_cli",
    "MedallionBasicTemplate",
    "TemplateCommand",
    "TemplateError",
    "TemplateFactory",
    "TemplateGenerator",
    "TemplateType",
    "handle_template_command",
    "launch_ui",
    "experiment_list",
    "model_gc",
    "model_promote",
    "UnifiedCLI",
    "main",
    # from commands subpackage
    "ExecutionCommands",
    "InitCommands",
    "QualityCommands",
    "handle_config",
    # from UX subpackage
    "RichLoggerManager",
    "SparkErrorAnalyzer",
    "format_error_for_developer",
    "log_node_complete",
    "log_node_start",
    "print_execution_header",
    "print_pandas_schema",
    "print_process_separator",
    "print_spark_schema",
]
