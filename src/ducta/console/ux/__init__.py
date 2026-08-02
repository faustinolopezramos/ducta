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

from ducta.console.ux.error_analyzer import SparkErrorAnalyzer, format_error_for_developer
from ducta.console.ux.rich_logger import (
    ACCENT,
    BOLD_WHITE,
    DIM_WHITE,
    ERROR,
    ICONS,
    INFO,
    MUTED,
    NEUTRAL,
    PRIMARY,
    PRIMARY_BOLD,
    PRIMARY_DIM,
    PROCESS_GROUPS,
    SUCCESS,
    TEXT_DEFAULT,
    TEXT_SECONDARY,
    WARNING,
    Ducta_THEME,
    RichLoggerManager,
    log_node_complete,
    log_node_start,
    print_execution_header,
    print_process_separator,
)
from ducta.console.ux.schema_formatter import print_pandas_schema, print_spark_schema

__all__ = [
    # rich_logger
    "RichLoggerManager",
    "Ducta_THEME",
    "PRIMARY",
    "BOLD_WHITE",
    "PRIMARY_BOLD",
    "DIM_WHITE",
    "PRIMARY_DIM",
    "SUCCESS",
    "WARNING",
    "ERROR",
    "INFO",
    "ACCENT",
    "NEUTRAL",
    "MUTED",
    "TEXT_DEFAULT",
    "TEXT_SECONDARY",
    "ICONS",
    "PROCESS_GROUPS",
    "print_execution_header",
    "print_process_separator",
    "log_node_start",
    "log_node_complete",
    # error_analyzer
    "SparkErrorAnalyzer",
    "format_error_for_developer",
    # schema_formatter
    "print_spark_schema",
    "print_pandas_schema",
]
