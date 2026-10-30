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
from typing import Any, List, Optional, Tuple

from loguru import logger

from ducta.console.core import ValidationError as CoreValidationError

ALLOWED_LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
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


def validate_project_name(project_name: str) -> None:
    if not re.match(PROJECT_NAME_PATTERN, project_name):
        raise CoreValidationError(
            "Project name must contain only alphanumeric characters, underscores, or hyphens"
        )
