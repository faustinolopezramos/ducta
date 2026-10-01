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
import re
from datetime import datetime
from typing import Any, List, Optional, Tuple

from loguru import logger

from ducta.console.core import ValidationError as CoreValidationError

ALLOWED_MODES = ["sync", "async"]
ALLOWED_LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
ALLOWED_FORMATS = ["table", "json"]
ALLOWED_CONFIG_TYPES = ["yaml", "json", "toml", "dsl"]
ALLOWED_TEMPLATES = ["medallion_basic"]
PROJECT_NAME_PATTERN = r"^[a-zA-Z0-9_-]+$"


def validate_enum_field(
    value: str, allowed: List[str], field_name: str, raise_error: bool = True
) -> Tuple[bool, Optional[str]]:
    if value not in allowed:
        allowed_str = "', '".join(allowed)
        error_msg = f"Invalid {field_name} '{value}'. Use '{allowed_str}'"
        if raise_error:
            raise CoreValidationError(error_msg)
        return False, error_msg
    return True, None


def validate_json_string(
    json_str: Optional[str], field_name: str = "JSON", raise_error: bool = True
) -> Tuple[bool, Optional[str]]:
    if not json_str:
        return True, None
    try:
        json.loads(json_str)
        return True, None
    except json.JSONDecodeError as e:
        error_msg = f"Invalid {field_name} JSON: {e}"
        if raise_error:
            raise CoreValidationError(error_msg)
        return False, error_msg


def validate_positive_number(
    value: int,
    max_val: Optional[int] = None,
    field_name: str = "value",
    warn_on_exceed: bool = True,
) -> Tuple[bool, Optional[str]]:
    if value <= 0:
        raise CoreValidationError(f"{field_name} must be positive, got {value}")
    if max_val and value > max_val:
        warn_msg = f"{field_name} {value} exceeds recommended max {max_val}"
        if warn_on_exceed:
            logger.warning(warn_msg)
        return True, warn_msg
    return True, None


def validate_required_field(value: Any, field_name: str) -> None:
    if not value:
        raise CoreValidationError(f"--{field_name} is required")


def validate_timeout(timeout: int, max_val: int = 3600) -> None:
    validate_positive_number(timeout, max_val=max_val, field_name="Timeout")


def validate_project_name(project_name: str) -> None:
    if not re.match(PROJECT_NAME_PATTERN, project_name):
        raise CoreValidationError(
            "Project name must contain only alphanumeric characters, underscores, or hyphens"
        )


def validate_date_iso(date_str: Optional[str], field_name: str = "Date") -> Optional[datetime]:
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str)
    except ValueError as e:
        raise CoreValidationError(f"Invalid {field_name} format (expected YYYY-MM-DD): {e}")


def validate_conflicting_options(
    *args: Tuple[bool, str],
    message: str = "Conflicting options specified",
    raise_error: bool = False,
) -> bool:
    enabled_options = [name for flag, name in args if flag]
    if len(enabled_options) > 1:
        if raise_error:
            raise CoreValidationError(f"{message}: {', '.join(enabled_options)}")
        logger.warning("{}: {}", message, ", ".join(enabled_options))
        return False
    return True


def _validate_choice(
    value: Optional[str],
    allowed: List[str],
    field_name: str,
    normalize,
    raise_error: bool,
) -> bool:
    if value is None:
        return True
    if normalize(str(value)) not in allowed:
        if raise_error:
            raise CoreValidationError(
                f"Invalid {field_name} '{value}'. Allowed: {', '.join(allowed)}"
            )
        return False
    return True


def validate_mode(value: Optional[str], raise_error: bool = True) -> bool:
    return _validate_choice(value, ALLOWED_MODES, "mode", str.lower, raise_error)


def validate_log_level(value: Optional[str], raise_error: bool = True) -> bool:
    return _validate_choice(value, ALLOWED_LOG_LEVELS, "log level", str.upper, raise_error)


def validate_format(value: Optional[str], raise_error: bool = True) -> bool:
    return _validate_choice(value, ALLOWED_FORMATS, "format", str.lower, raise_error)
