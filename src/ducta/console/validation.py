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
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, List, Optional, Tuple

from loguru import logger

from ducta.console.config import load_config_file
from ducta.console.core import ConfigurationError, get_fallback_chain
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


class ValidationSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class ValidationIssue:
    severity: ValidationSeverity
    message: str
    environment: Optional[str] = None
    path: Optional[Path] = None
    suggestion: Optional[str] = None

    def __str__(self) -> str:
        base = f"[{self.severity.upper()}] {self.message}"
        if self.path:
            base += f" ({self.path})"
        if self.suggestion:
            base += f"\nSuggestion: {self.suggestion}"
        return base


class EnvironmentConfigValidator:
    def __init__(self, project_path: Path):
        self.project_path = Path(project_path)
        self.config_dir = self.project_path / "config"
        self.settings_file = self._find_settings_file()
        self.errors: List[ValidationIssue] = []

    REQUIRED_CONFIG_SECTIONS = [
        "global_config",
        "pipelines",
        "nodes",
        "input",
        "output",
    ]

    _EXT_TOML: str = ".toml"
    SUPPORTED_EXTENSIONS = [".yaml", ".yml", ".json", _EXT_TOML]
    _YAML_EXTS: frozenset = frozenset({".yaml", ".yml"})

    def validate_project(self) -> List[ValidationIssue]:
        self.errors = []
        self._validate_base_exists()
        if self.settings_file:
            self._validate_settings_file()
        else:
            self.errors.append(
                ValidationIssue(
                    severity=ValidationSeverity.WARNING,
                    message="No settings file found (settings.json, settings_yml.json, etc.)",
                    path=self.config_dir,
                    suggestion="Create one of: settings.json, settings_yml.json, or settings_dsl.json",
                )
            )
        self._validate_environments()
        self._validate_fallback_chains()
        self._validate_config_syntax()
        return self.errors

    def _find_settings_file(self) -> Optional[Path]:
        for candidate in [
            self.project_path / "settings_yml.json",
            self.project_path / "settings_json.json",
            self.project_path / "settings_dsl.json",
            self.project_path / "settings.json",
            self.project_path / "config.json",
            self.project_path / "ducta.json",
        ]:
            if candidate.exists():
                return candidate
        return None

    def _has_required_sections(self, directory: Path) -> bool:
        return any(
            (directory / f"{section}{ext}").exists()
            for section in self.REQUIRED_CONFIG_SECTIONS
            for ext in self.SUPPORTED_EXTENSIONS
        )

    def _validate_base_exists(self) -> None:
        base_dir = self.config_dir / "base"
        has_base_files = self._has_required_sections(self.config_dir) or (
            base_dir.exists() and self._has_required_sections(base_dir)
        )
        if not has_base_files:
            self.errors.append(
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    message="Base configuration not found",
                    path=self.config_dir,
                    suggestion="Create config/global_config.yaml (or .json/.toml) with base configuration",
                )
            )

    def _load_settings_content(self) -> Optional[dict]:
        if self.settings_file is None:
            raise ConfigurationError("Settings file not initialized before loading content")
        try:
            data = load_config_file(str(self.settings_file))
            return data if isinstance(data, dict) else None
        except Exception as e:
            self.errors.append(
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    message=f"Error reading settings file: {e}",
                    path=self.settings_file,
                )
            )
            return None

    def _validate_settings_file(self) -> None:
        if not self.settings_file or not self.settings_file.exists():
            return
        settings = self._load_settings_content()
        if settings is None:
            return
        if "env_config" not in settings:
            self.errors.append(
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    message="Missing 'env_config' section in settings file",
                    path=self.settings_file,
                    suggestion="Add 'env_config' dict with environment mappings",
                )
            )
            return
        env_config = settings.get("env_config", {})
        if not isinstance(env_config, dict):
            self.errors.append(
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    message="'env_config' must be a dictionary",
                    path=self.settings_file,
                )
            )
            return
        if "base" not in env_config:
            self.errors.append(
                ValidationIssue(
                    severity=ValidationSeverity.WARNING,
                    message="'base' environment not declared in env_config",
                    path=self.settings_file,
                    suggestion="Add 'base' to env_config with paths to base configuration files",
                )
            )

    def _validate_environments(self) -> None:
        if not self.config_dir.exists():
            return
        env_dirs = [
            d.name for d in self.config_dir.iterdir() if d.is_dir() and not d.name.startswith(".")
        ]
        canonical_envs = set(env_dirs)
        if any(
            (self.config_dir / f"global_config{ext}").exists() for ext in self.SUPPORTED_EXTENSIONS
        ):
            canonical_envs.add("base")
        for env in canonical_envs:
            if env == "base":
                continue
            if not (self.config_dir / env).exists():
                self.errors.append(
                    ValidationIssue(
                        severity=ValidationSeverity.WARNING,
                        message=f"Environment '{env}' is empty (no files)",
                        path=self.config_dir / env,
                        suggestion=f"Add configuration files to {self.config_dir / env}",
                    )
                )

    def _validate_fallback_chains(self) -> None:
        if not self.settings_file or not self.settings_file.exists():
            return
        settings = self._load_settings_content()
        if settings is None:
            return
        declared_envs = list(settings.get("env_config", {}).keys())
        for env in declared_envs:
            try:
                for fallback_env in get_fallback_chain(env):
                    if fallback_env not in declared_envs and fallback_env != "base":
                        self.errors.append(
                            ValidationIssue(
                                severity=ValidationSeverity.WARNING,
                                environment=env,
                                message=f"Fallback environment '{fallback_env}' not declared",
                                path=self.config_dir,
                                suggestion=f"Add configuration for '{fallback_env}' or remove reference",
                            )
                        )
            except ValueError:
                self.errors.append(
                    ValidationIssue(
                        severity=ValidationSeverity.WARNING,
                        environment=env,
                        message=f"Unknown environment '{env}' may not have proper fallback chain",
                        path=self.config_dir,
                    )
                )

    def _validate_config_syntax(self) -> None:
        if not self.config_dir.exists():
            return
        validated_exts = self._YAML_EXTS | {".json", self._EXT_TOML}
        for config_file in self.config_dir.rglob("*.*"):
            ext = config_file.suffix
            if ext in validated_exts:
                self._validate_file_syntax(config_file, ext)

    def _validate_file_syntax(self, file_path: Path, ext: str) -> None:
        try:
            load_config_file(str(file_path))
        except Exception as e:
            sev = (
                ValidationSeverity.WARNING
                if "PyYAML not installed" in str(e)
                else ValidationSeverity.ERROR
            )
            self.errors.append(
                ValidationIssue(
                    severity=sev,
                    message=f"Invalid {ext} syntax: {e}",
                    path=file_path,
                    suggestion=(
                        f"Fix {ext} syntax"
                        if sev == ValidationSeverity.ERROR
                        else "pip install PyYAML"
                    ),
                )
            )

    def get_summary(self) -> dict:
        return summarize_issues(self.errors)


def summarize_issues(issues: List[ValidationIssue]) -> dict:
    """Tally *issues* by severity. ``is_valid`` is False if any ``ERROR`` or
    ``CRITICAL`` issue is present — the single definition of what invalidates
    a project, shared by ``get_summary`` and ``print_validation_report``."""
    return {
        "total": len(issues),
        "critical": sum(1 for e in issues if e.severity == ValidationSeverity.CRITICAL),
        "errors": sum(1 for e in issues if e.severity == ValidationSeverity.ERROR),
        "warnings": sum(1 for e in issues if e.severity == ValidationSeverity.WARNING),
        "info": sum(1 for e in issues if e.severity == ValidationSeverity.INFO),
        "is_valid": all(
            e.severity not in (ValidationSeverity.CRITICAL, ValidationSeverity.ERROR)
            for e in issues
        ),
    }


def print_validation_report(issues: List[ValidationIssue], project_path: Path) -> None:
    summary = (
        EnvironmentConfigValidator(project_path).get_summary()
        if not issues
        else summarize_issues(issues)
    )
    print(f"\n{'=' * 70}")
    print(f"Environment Configuration Validation Report\nProject: {project_path}\n{'=' * 70}")
    if not issues:
        print("✓ All checks passed!")
    else:
        print(f"\nFound {len(issues)} issues:")
        print(
            f"  • Critical: {summary['critical']}\n  • Errors:   {summary['errors']}\n  • Warnings: {summary['warnings']}\n  • Info:     {summary['info']}"
        )
        for severity in (
            ValidationSeverity.CRITICAL,
            ValidationSeverity.ERROR,
            ValidationSeverity.WARNING,
            ValidationSeverity.INFO,
        ):
            filtered = [e for e in issues if e.severity == severity]
            if filtered:
                print(f"\n{severity.upper()}:")
                for issue in filtered:
                    print(f"  • {issue}")
    print(f"{'=' * 70}\n")
